import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth import create_access_token
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import (
    AuditEvent,
    Chunk,
    FileVersion,
    FileVersionChunk,
    LogicalFile,
    User,
    UserRole,
)
from app.services.uploads import _get_or_create_chunk
from app.services.versioning import create_version, restore_file_version, transaction_key_lock


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _register(client: TestClient, email: str) -> tuple[str, str]:
    response = client.post('/api/auth/register', json={'email': email, 'password': 'very-strong-password'})
    assert response.status_code == 200
    token = response.json()['access_token']
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user.id, token


def _admin_token() -> str:
    with SessionLocal() as db:
        admin = User(email='admin-test@example.com', password_hash='x', role=UserRole.ADMIN)
        db.add(admin)
        db.commit()
        return create_access_token(admin.id, admin.role.value)


def test_dashboard_activity_is_isolated_per_user_and_audit_is_admin_only():
    with TestClient(app) as client:
        user_a, token_a = _register(client, 'alice@example.com')
        user_b, token_b = _register(client, 'bob@example.com')
        admin_token = _admin_token()
        with SessionLocal() as db:
            db.add(AuditEvent(actor_id=user_a, event_type='FILE_PRIVATE_A', message='alice-secret-name.pdf uploaded'))
            db.add(AuditEvent(actor_id=user_b, event_type='FILE_PRIVATE_B', message='bob-file.pdf uploaded'))
            db.add(AuditEvent(actor_id=None, event_type='SYSTEM_EVENT', message='cluster maintenance'))
            db.commit()
        dashboard_b = client.get('/api/dashboard', headers={'Authorization': f'Bearer {token_b}'})
        assert dashboard_b.status_code == 200
        messages = [row['message'] for row in dashboard_b.json()['activity']]
        assert any('bob-file.pdf' in message for message in messages)
        assert all('alice-secret-name.pdf' not in message for message in messages)
        assert all('cluster maintenance' not in message for message in messages)
        assert client.get('/api/audit', headers={'Authorization': f'Bearer {token_a}'}).status_code == 403
        admin_audit = client.get('/api/audit', headers={'Authorization': f'Bearer {admin_token}'})
        assert admin_audit.status_code == 200
        assert {row['event_type'] for row in admin_audit.json()} >= {'FILE_PRIVATE_A', 'FILE_PRIVATE_B', 'SYSTEM_EVENT'}


def test_cluster_maintenance_routes_require_admin():
    with TestClient(app) as client:
        _, user_token = _register(client, 'ordinary@example.com')
        headers = {'Authorization': f'Bearer {user_token}'}
        assert client.get('/api/integrity', headers=headers).status_code == 403
        assert client.post('/api/integrity/scan', headers=headers).status_code == 403
        assert client.post('/api/repairs/scan', headers=headers).status_code == 403
        assert client.post('/api/gc/scan', headers=headers).status_code == 403


def test_direct_version_restore_creates_new_version_without_changing_history():
    with SessionLocal() as db:
        user = User(email='restore@example.com', password_hash='x')
        db.add(user)
        db.flush()
        logical = LogicalFile(owner_id=user.id, name='resume.pdf')
        chunk_a = Chunk(hash='a' * 64, size_bytes=3)
        chunk_b = Chunk(hash='b' * 64, size_bytes=4)
        db.add_all([logical, chunk_a, chunk_b])
        db.flush()
        v1 = FileVersion(logical_file_id=logical.id, version_number=1, size_bytes=3, file_sha256='1' * 64)
        v2 = FileVersion(logical_file_id=logical.id, version_number=2, size_bytes=4, file_sha256='2' * 64)
        db.add_all([v1, v2])
        db.flush()
        db.add(FileVersionChunk(file_version_id=v1.id, chunk_hash=chunk_a.hash, chunk_index=0, size_bytes=3))
        db.add(FileVersionChunk(file_version_id=v2.id, chunk_hash=chunk_b.hash, chunk_index=0, size_bytes=4))
        db.commit()
        restored = restore_file_version(db, v1, user.id)
        assert restored.version_number == 3
        restored_chunk = db.scalar(select(FileVersionChunk).where(FileVersionChunk.file_version_id == restored.id))
        assert restored_chunk is not None and restored_chunk.chunk_hash == chunk_a.hash
        assert db.get(FileVersion, v1.id).file_sha256 == '1' * 64
        assert db.get(FileVersion, v2.id).file_sha256 == '2' * 64
        event = db.scalar(select(AuditEvent).where(AuditEvent.event_type == 'FILE_VERSION_RESTORED'))
        assert event is not None and 'restored as v3' in event.message


def _thread_db(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'concurrency.db'}"
    local_engine = create_engine(db_url, connect_args={'check_same_thread': False, 'timeout': 10})
    Base.metadata.create_all(local_engine)
    return local_engine, sessionmaker(bind=local_engine, autoflush=False, expire_on_commit=False)


def test_concurrent_identical_chunk_creation_is_idempotent(tmp_path):
    local_engine, LocalSession = _thread_db(tmp_path)

    def worker() -> str:
        with LocalSession() as db:
            chunk = _get_or_create_chunk(db, 'c' * 64, 4096)
            db.commit()
            return chunk.hash

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert results == ['c' * 64, 'c' * 64]
    with LocalSession() as db:
        assert len(db.scalars(select(Chunk).where(Chunk.hash == 'c' * 64)).all()) == 1
    local_engine.dispose()


def test_concurrent_version_allocation_is_unique_and_monotonic(tmp_path):
    local_engine, LocalSession = _thread_db(tmp_path)
    with LocalSession() as db:
        user = User(email='versions-thread@example.com', password_hash='x')
        db.add(user)
        db.flush()
        logical = LogicalFile(owner_id=user.id, name='same-name.bin')
        chunk = Chunk(hash='d' * 64, size_bytes=1)
        db.add_all([logical, chunk])
        db.commit()
        logical_id = logical.id

    def worker() -> int:
        with LocalSession() as db:
            with transaction_key_lock(db, f'version-test:{logical_id}'):
                logical = db.get(LogicalFile, logical_id)
                assert logical is not None
                version = create_version(
                    db,
                    logical=logical,
                    size_bytes=1,
                    file_sha256='e' * 64,
                    chunks=[('d' * 64, 0, 1)],
                )
                db.commit()
                return version.version_number

    with ThreadPoolExecutor(max_workers=2) as pool:
        numbers = sorted(pool.map(lambda _: worker(), range(2)))
    assert numbers == [1, 2]
    with LocalSession() as db:
        stored = db.scalars(select(FileVersion).where(FileVersion.logical_file_id == logical_id)).all()
        assert sorted(v.version_number for v in stored) == [1, 2]
    local_engine.dispose()



def test_version_restore_endpoint_enforces_ownership_and_returns_new_version():
    with TestClient(app) as client:
        owner_id, owner_token = _register(client, 'restore-owner@example.com')
        _, other_token = _register(client, 'restore-other@example.com')
        with SessionLocal() as db:
            logical = LogicalFile(owner_id=owner_id, name='history.txt', content_type='text/plain')
            chunk = Chunk(hash='f' * 64, size_bytes=5)
            db.add_all([logical, chunk])
            db.flush()
            source = FileVersion(logical_file_id=logical.id, version_number=1, size_bytes=5, file_sha256='9' * 64)
            current = FileVersion(logical_file_id=logical.id, version_number=2, size_bytes=5, file_sha256='8' * 64)
            db.add_all([source, current])
            db.flush()
            db.add_all([
                FileVersionChunk(file_version_id=source.id, chunk_hash=chunk.hash, chunk_index=0, size_bytes=5),
                FileVersionChunk(file_version_id=current.id, chunk_hash=chunk.hash, chunk_index=0, size_bytes=5),
            ])
            db.commit()
            file_id = logical.id
        denied = client.post(
            f'/api/files/{file_id}/versions/1/restore',
            headers={'Authorization': f'Bearer {other_token}'},
        )
        assert denied.status_code == 404
        restored = client.post(
            f'/api/files/{file_id}/versions/1/restore',
            headers={'Authorization': f'Bearer {owner_token}'},
        )
        assert restored.status_code == 200
        assert restored.json()['version_number'] == 3
        assert restored.json()['restored_from_version'] == 1
