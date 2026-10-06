import asyncio
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, SessionLocal, engine
from app.models import (
    Chunk,
    ChunkReplica,
    FileVersion,
    FileVersionChunk,
    LogicalFile,
    NodeStatus,
    RepairJob,
    RepairState,
    ReplicaState,
    StorageNode,
    User,
)
from app.services.health import DataHealth, chunk_health, version_health
from app.services.placement import ConsistentHashRing
from app.services.project_metrics import project_metrics
from app.services.repair import repair_chunk


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def add_nodes(db, count=4):
    rows = []
    for index in range(1, count + 1):
        node = StorageNode(
            id=f'node-{index}',
            base_url=f'http://node-{index}:900{index}',
            status=NodeStatus.HEALTHY,
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(node)
        rows.append(node)
    db.flush()
    return rows


def test_explicit_data_health_transitions():
    with SessionLocal() as db:
        nodes = add_nodes(db)
        chunk_hash = hashlib.sha256(b'health').hexdigest()
        db.add(Chunk(hash=chunk_hash, size_bytes=6))
        db.flush()
        for node in nodes[:3]:
            db.add(ChunkReplica(chunk_hash=chunk_hash, node_id=node.id, state=ReplicaState.HEALTHY))
        db.commit()
        assert chunk_health(db, chunk_hash)['status'] == DataHealth.HEALTHY.value

        replica = db.scalar(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == chunk_hash,
                ChunkReplica.node_id == 'node-1',
            )
        )
        replica.state = ReplicaState.UNAVAILABLE
        db.commit()
        assert chunk_health(db, chunk_hash)['status'] == DataHealth.DEGRADED.value

        db.add(RepairJob(chunk_hash=chunk_hash, state=RepairState.RUNNING))
        db.commit()
        assert chunk_health(db, chunk_hash)['status'] == DataHealth.REPAIRING.value

        for row in db.scalars(select(ChunkReplica).where(ChunkReplica.chunk_hash == chunk_hash)).all():
            row.state = ReplicaState.UNAVAILABLE
        for job in db.scalars(select(RepairJob)).all():
            job.state = RepairState.FAILED
        db.commit()
        assert chunk_health(db, chunk_hash)['status'] == DataHealth.UNRECOVERABLE.value


def test_version_health_is_worst_constituent_chunk():
    with SessionLocal() as db:
        user = User(email='health-version@example.com', password_hash='x')
        db.add(user)
        nodes = add_nodes(db)
        logical = LogicalFile(owner_id=user.id, name='health.bin')
        db.add(logical)
        hashes = [hashlib.sha256(b'a').hexdigest(), hashlib.sha256(b'b').hexdigest()]
        for chunk_hash in hashes:
            db.add(Chunk(hash=chunk_hash, size_bytes=1))
        db.flush()
        version = FileVersion(
            logical_file_id=logical.id,
            version_number=1,
            size_bytes=2,
            file_sha256=hashlib.sha256(b'ab').hexdigest(),
        )
        db.add(version)
        db.flush()
        for idx, chunk_hash in enumerate(hashes):
            db.add(FileVersionChunk(file_version_id=version.id, chunk_hash=chunk_hash, chunk_index=idx, size_bytes=1))
            for node in nodes[:3]:
                db.add(ChunkReplica(chunk_hash=chunk_hash, node_id=node.id, state=ReplicaState.HEALTHY))
        db.commit()
        first = db.scalar(select(ChunkReplica).where(ChunkReplica.chunk_hash == hashes[1]))
        first.state = ReplicaState.UNAVAILABLE
        db.commit()
        assert version_health(db, version)['status'] == DataHealth.DEGRADED.value


def test_consistent_hash_is_deterministic_and_membership_change_is_partial():
    keys = [hashlib.sha256(f'key-{i}'.encode()).hexdigest() for i in range(5000)]
    before_a = ConsistentHashRing(['node-1', 'node-2', 'node-3', 'node-4'])
    before_b = ConsistentHashRing(['node-4', 'node-2', 'node-1', 'node-3'])
    assert [before_a.replicas(key, 3) for key in keys] == [before_b.replicas(key, 3) for key in keys]

    joined = ConsistentHashRing(['node-1', 'node-2', 'node-3', 'node-4', 'node-5'])
    moved = sum(before_a.replicas(key, 1) != joined.replicas(key, 1) for key in keys)
    assert 0 < moved < len(keys)


def test_project_metrics_reports_real_counts_without_fake_values():
    with SessionLocal() as db:
        nodes = add_nodes(db)
        user = User(email='metrics@example.com', password_hash='x')
        db.add(user)
        logical = LogicalFile(owner_id=user.id, name='m.bin')
        chunk = Chunk(hash='a' * 64, size_bytes=10)
        db.add_all([logical, chunk])
        db.flush()
        version = FileVersion(logical_file_id=logical.id, version_number=1, size_bytes=20, file_sha256='b' * 64)
        db.add(version)
        db.flush()
        db.add(FileVersionChunk(file_version_id=version.id, chunk_hash=chunk.hash, chunk_index=0, size_bytes=10))
        for node in nodes[:3]:
            db.add(ChunkReplica(chunk_hash=chunk.hash, node_id=node.id, state=ReplicaState.HEALTHY))
        db.commit()
        snapshot = project_metrics(db)
        assert snapshot['storage']['logical_bytes_stored'] == 20
        assert snapshot['storage']['unique_chunk_bytes'] == 10
        assert snapshot['storage']['dedup_saved_bytes'] == 10
        assert snapshot['storage']['dedup_percentage'] == 50.0
        assert snapshot['data_health']['chunks']['HEALTHY'] == 1


def test_concurrent_repair_schedules_at_most_one_active_copy(tmp_path):
    db_path = tmp_path / 'repair-race.db'
    local_engine = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'check_same_thread': False, 'timeout': 10},
    )
    Base.metadata.create_all(local_engine)
    LocalSession = sessionmaker(bind=local_engine, autoflush=False, expire_on_commit=False)

    data = b'repair-race'
    chunk_hash = hashlib.sha256(data).hexdigest()
    with LocalSession() as db:
        nodes = add_nodes(db)
        db.add(Chunk(hash=chunk_hash, size_bytes=len(data)))
        db.flush()
        for node in nodes[:2]:
            db.add(ChunkReplica(chunk_hash=chunk_hash, node_id=node.id, state=ReplicaState.HEALTHY))
        db.commit()

    async def slow_get(*_args, **_kwargs):
        await asyncio.sleep(0.08)
        return data

    async def ok_put(*_args, **_kwargs):
        await asyncio.sleep(0.02)
        return {'stored': True}

    async def ok_check(*_args, **_kwargs):
        return {'exists': True, 'valid': True}

    def worker():
        with LocalSession() as db:
            return asyncio.run(repair_chunk(db, chunk_hash))

    with patch('app.services.repair.StorageClient.get', new=slow_get), patch(
        'app.services.repair.StorageClient.put', new=ok_put
    ), patch('app.services.repair.StorageClient.check', new=ok_check):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))

    assert sorted(results) == [False, True]
    with LocalSession() as db:
        succeeded = db.scalars(
            select(RepairJob).where(
                RepairJob.chunk_hash == chunk_hash,
                RepairJob.state == RepairState.SUCCEEDED,
            )
        ).all()
        assert len(succeeded) == 1
        healthy = db.scalars(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == chunk_hash,
                ChunkReplica.state == ReplicaState.HEALTHY,
            )
        ).all()
        assert len({replica.node_id for replica in healthy}) == 3
    local_engine.dispose()
