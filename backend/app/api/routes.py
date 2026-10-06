from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import create_access_token, hash_password, verify_password
from ..config import settings
from ..db import get_db
from ..dependencies import admin_user, current_user
from ..models import (
    AuditEvent,
    Chunk,
    ChunkReplica,
    FileVersion,
    FileVersionChunk,
    LogicalFile,
    NodeStatus,
    RepairJob,
    RepairState,
    ReplicaState,
    Snapshot,
    StorageNode,
    UploadSession,
    UploadSessionChunk,
    UploadStatus,
    User,
    UserRole,
)
from ..schemas import (
    ChunkDescriptor,
    DemoCorruptRequest,
    DemoNodeRequest,
    LoginRequest,
    RegisterRequest,
    SnapshotCreate,
    TokenResponse,
    UploadSessionCreate,
)
from ..services.audit import record
from ..services.cache import cache
from ..services.downloads import iter_version_bytes
from ..services.gc import collect_garbage
from ..services.integrity import integrity_scan
from ..services.health import aggregate_data_health, version_health
from ..services.metrics import metrics
from ..services.placement import ConsistentHashRing
from ..services.project_metrics import project_metrics
from ..services.repair import repair_scan
from ..services.snapshots import create_snapshot, restore_snapshot
from ..services.storage_client import StorageClient
from ..services.uploads import create_session, finalize_session, store_session_chunk
from ..services.versioning import restore_file_version

router = APIRouter(prefix='/api')


def serialize_node(n: StorageNode) -> dict:
    return {
        'id': n.id,
        'base_url': n.base_url,
        'status': n.status.value,
        'last_heartbeat': n.last_heartbeat,
        'storage_used_bytes': n.storage_used_bytes,
        'chunk_count': n.chunk_count,
        'simulated_down': n.simulated_down,
    }


@router.get('/health')
def health():
    return {'status': 'ok', 'service': 'quorumvault-control-plane'}


@router.post('/auth/register', response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(409, 'Email already registered')
    user = User(email=payload.email.lower(), password_hash=hash_password(payload.password), role=UserRole.USER)
    db.add(user)
    db.flush()
    record(db, 'USER_REGISTERED', f'Account registered for {user.email}', user.id)
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id, user.role.value))


@router.post('/auth/login', response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    return TokenResponse(access_token=create_access_token(user.id, user.role.value))


@router.get('/me')
def me(user: User = Depends(current_user)):
    return {'id': user.id, 'email': user.email, 'role': user.role.value}


@router.get('/dashboard')
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    cache_key = f'qv:dashboard:{user.id}'
    cached = cache.get_json(cache_key)
    if cached is not None:
        return cached
    files = db.scalars(select(LogicalFile).where(LogicalFile.owner_id == user.id)).all()
    latest_versions: list[FileVersion] = []
    for logical in files:
        latest = db.scalar(
            select(FileVersion)
            .where(FileVersion.logical_file_id == logical.id)
            .order_by(FileVersion.version_number.desc())
            .limit(1)
        )
        if latest:
            latest_versions.append(latest)
    logical_bytes = sum(v.size_bytes for v in latest_versions)
    referenced_hashes: set[str] = set()
    for version in latest_versions:
        referenced_hashes.update(
            db.scalars(
                select(FileVersionChunk.chunk_hash).where(FileVersionChunk.file_version_id == version.id)
            ).all()
        )
    unique_physical = sum((db.get(Chunk, h).size_bytes if db.get(Chunk, h) else 0) for h in referenced_hashes)
    degraded = db.scalar(
        select(func.count(func.distinct(ChunkReplica.chunk_hash))).where(ChunkReplica.state != ReplicaState.HEALTHY)
    ) or 0
    repairs = db.scalar(
        select(func.count())
        .select_from(RepairJob)
        .where(RepairJob.state.in_([RepairState.PENDING, RepairState.RUNNING]))
    ) or 0
    snapshots = db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.owner_id == user.id)) or 0
    nodes = db.scalars(select(StorageNode).order_by(StorageNode.id)).all()
    event_query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(8)
    if user.role != UserRole.ADMIN:
        event_query = event_query.where(AuditEvent.actor_id == user.id)
    events = db.scalars(event_query).all()
    result = {
        'logical_storage_bytes': logical_bytes,
        'physical_storage_bytes': sum(n.storage_used_bytes for n in nodes),
        'unique_chunk_bytes': unique_physical,
        'dedup_savings_bytes': max(0, logical_bytes - unique_physical),
        'file_count': len(files),
        'snapshot_count': snapshots,
        'degraded_chunks': degraded,
        'active_repairs': repairs,
        'healthy_nodes': sum(1 for n in nodes if n.status == NodeStatus.HEALTHY),
        'node_count': len(nodes),
        'activity': [
            {
                'type': event.event_type,
                'message': event.message,
                'created_at': event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
        'metrics': metrics.snapshot(),
    }
    cache.set_json(cache_key, result, ttl=2)
    return result


@router.get('/files')
def list_files(db: Session = Depends(get_db), user: User = Depends(current_user)):
    files = db.scalars(
        select(LogicalFile)
        .where(LogicalFile.owner_id == user.id)
        .order_by(LogicalFile.created_at.desc())
    ).all()
    out = []
    for logical in files:
        latest = db.scalar(
            select(FileVersion)
            .where(FileVersion.logical_file_id == logical.id)
            .order_by(FileVersion.version_number.desc())
            .limit(1)
        )
        out.append(
            {
                'id': logical.id,
                'name': logical.name,
                'content_type': logical.content_type,
                'created_at': logical.created_at,
                'latest_version': latest.version_number if latest else None,
                'size_bytes': latest.size_bytes if latest else 0,
            }
        )
    return out


@router.get('/files/{file_id}')
def file_detail(file_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    logical = db.get(LogicalFile, file_id)
    if not logical or logical.owner_id != user.id:
        raise HTTPException(404, 'File not found')
    versions = db.scalars(
        select(FileVersion)
        .where(FileVersion.logical_file_id == logical.id)
        .order_by(FileVersion.version_number.desc())
    ).all()
    result = {'id': logical.id, 'name': logical.name, 'content_type': logical.content_type, 'versions': []}
    for version in versions:
        chunks = []
        for item in db.scalars(
            select(FileVersionChunk)
            .where(FileVersionChunk.file_version_id == version.id)
            .order_by(FileVersionChunk.chunk_index)
        ).all():
            replicas = db.scalars(select(ChunkReplica).where(ChunkReplica.chunk_hash == item.chunk_hash)).all()
            chunks.append(
                {
                    'index': item.chunk_index,
                    'hash': item.chunk_hash,
                    'size_bytes': item.size_bytes,
                    'replicas': [{'node_id': r.node_id, 'state': r.state.value} for r in replicas],
                }
            )
        result['versions'].append(
            {
                'id': version.id,
                'version_number': version.version_number,
                'size_bytes': version.size_bytes,
                'file_sha256': version.file_sha256,
                'created_at': version.created_at,
                'health': version_health(db, version),
                'chunks': chunks,
            }
        )
    return result


@router.get('/files/{file_id}/versions/{version_number}/download')
async def download(
    file_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    logical = db.get(LogicalFile, file_id)
    if not logical or logical.owner_id != user.id:
        raise HTTPException(404, 'File not found')
    version = db.scalar(
        select(FileVersion).where(
            FileVersion.logical_file_id == file_id,
            FileVersion.version_number == version_number,
        )
    )
    if not version:
        raise HTTPException(404, 'Version not found')
    headers = {'Content-Disposition': f'attachment; filename="{logical.name}"', 'X-Content-SHA256': version.file_sha256}
    return StreamingResponse(
        iter_version_bytes(db, version, user.id),
        media_type=logical.content_type or 'application/octet-stream',
        headers=headers,
    )


@router.post('/files/{file_id}/versions/{version_number}/restore')
def restore_version(
    file_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    logical = db.get(LogicalFile, file_id)
    if not logical or logical.owner_id != user.id:
        raise HTTPException(404, 'File not found')
    source = db.scalar(
        select(FileVersion).where(
            FileVersion.logical_file_id == file_id,
            FileVersion.version_number == version_number,
        )
    )
    if source is None:
        raise HTTPException(404, 'Version not found')
    try:
        restored = restore_file_version(db, source, user.id)
    except LookupError:
        raise HTTPException(404, 'Version not found')
    return {
        'file_version_id': restored.id,
        'version_number': restored.version_number,
        'restored_from_version': source.version_number,
        'file_sha256': restored.file_sha256,
    }


@router.post('/uploads/sessions')
def new_upload(payload: UploadSessionCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    session, missing = create_session(db, user.id, payload)
    return {
        'session_id': session.id,
        'missing_chunks': missing,
        'chunk_size': session.chunk_size,
        'status': session.status.value,
        'created_at': session.created_at,
    }


@router.get('/uploads/sessions/{session_id}')
def upload_status(session_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    session = db.get(UploadSession, session_id)
    if not session or session.owner_id != user.id:
        raise HTTPException(404, 'Upload session not found')
    items = db.scalars(
        select(UploadSessionChunk)
        .where(UploadSessionChunk.session_id == session.id)
        .order_by(UploadSessionChunk.chunk_index)
    ).all()
    return {
        'session_id': session.id,
        'status': session.status.value,
        'file_name': session.file_name,
        'expected_size': session.expected_size,
        'chunk_size': session.chunk_size,
        'created_at': session.created_at,
        'missing_chunks': [i.chunk_index for i in items if not i.received],
        'received_chunks': [i.chunk_index for i in items if i.received],
    }


@router.delete('/uploads/sessions/{session_id}')
def abort_upload(session_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    session = db.get(UploadSession, session_id)
    if not session or session.owner_id != user.id:
        raise HTTPException(404, 'Upload session not found')
    if session.status == UploadStatus.ACTIVE:
        session.status = UploadStatus.ABORTED
        record(db, 'UPLOAD_SESSION_ABORTED', f'Upload session {session.id} aborted for {session.file_name}', user.id)
        db.commit()
    return {'session_id': session.id, 'status': session.status.value}


@router.put('/uploads/sessions/{session_id}/chunks/{chunk_index}')
async def upload_chunk(
    session_id: str,
    chunk_index: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    session = db.get(UploadSession, session_id)
    if not session or session.owner_id != user.id:
        raise HTTPException(404, 'Upload session not found')
    item = db.scalar(
        select(UploadSessionChunk).where(
            UploadSessionChunk.session_id == session.id,
            UploadSessionChunk.chunk_index == chunk_index,
        )
    )
    if not item:
        raise HTTPException(404, 'Chunk not in upload manifest')
    data = await request.body()
    if len(data) > settings.chunk_size_bytes:
        raise HTTPException(413, 'Chunk exceeds configured chunk size')
    return await store_session_chunk(db, session, item, data)


@router.post('/uploads/sessions/{session_id}/finalize')
async def finalize(session_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    session = db.get(UploadSession, session_id)
    if not session or session.owner_id != user.id:
        raise HTTPException(404, 'Upload session not found')
    version = await finalize_session(db, session)
    return {
        'file_version_id': version.id,
        'version_number': version.version_number,
        'file_sha256': version.file_sha256,
    }


@router.get('/snapshots')
def snapshots(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(Snapshot).where(Snapshot.owner_id == user.id).order_by(Snapshot.created_at.desc())
    ).all()
    return [{'id': s.id, 'name': s.name, 'created_at': s.created_at, 'entry_count': len(s.entries)} for s in rows]


@router.post('/snapshots')
def snapshot_create(payload: SnapshotCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    snapshot = create_snapshot(db, user.id, payload.name)
    return {'id': snapshot.id, 'name': snapshot.name, 'entry_count': len(snapshot.entries)}


@router.post('/snapshots/{snapshot_id}/restore')
def snapshot_restore(snapshot_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    snapshot = db.get(Snapshot, snapshot_id)
    if not snapshot or snapshot.owner_id != user.id:
        raise HTTPException(404, 'Snapshot not found')
    versions = restore_snapshot(db, snapshot, user.id)
    return {'restored_versions': [{'id': v.id, 'version_number': v.version_number} for v in versions]}


@router.get('/cluster')
def cluster(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [serialize_node(n) for n in db.scalars(select(StorageNode).order_by(StorageNode.id)).all()]


@router.get('/data-health')
def data_health(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return aggregate_data_health(db, user.id)


@router.get('/metrics')
def metrics_state(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    return project_metrics(db)


@router.get('/integrity')
def integrity_state(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    states = {
        state.value: (db.scalar(select(func.count()).select_from(ChunkReplica).where(ChunkReplica.state == state)) or 0)
        for state in ReplicaState
    }
    jobs = db.scalars(select(RepairJob).order_by(RepairJob.created_at.desc()).limit(20)).all()
    return {
        'replica_states': states,
        'data_health': aggregate_data_health(db),
        'repairs': [
            {
                'id': job.id,
                'chunk_hash': job.chunk_hash,
                'source': job.source_node_id,
                'target': job.target_node_id,
                'state': job.state.value,
                'duration_ms': job.duration_ms,
                'created_at': job.created_at,
            }
            for job in jobs
        ],
    }


@router.post('/integrity/scan')
async def run_integrity(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    return await integrity_scan(db)


@router.post('/repairs/scan')
async def run_repairs(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    return await repair_scan(db)


@router.post('/gc/scan')
async def gc_scan(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    return await collect_garbage(db)


@router.get('/audit')
def audit(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200)).all()
    return [
        {
            'id': event.id,
            'event_type': event.event_type,
            'message': event.message,
            'actor_id': event.actor_id,
            'correlation_id': event.correlation_id,
            'created_at': event.created_at,
        }
        for event in rows
    ]


@router.get('/placement/{chunk_hash}')
def placement(chunk_hash: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    nodes = db.scalars(
        select(StorageNode).where(StorageNode.status == NodeStatus.HEALTHY, StorageNode.simulated_down.is_(False))
    ).all()
    ring = ConsistentHashRing([n.id for n in nodes])
    desired = ring.replicas(chunk_hash, settings.replication_factor)
    actual = db.scalars(select(ChunkReplica).where(ChunkReplica.chunk_hash == chunk_hash)).all()
    return {
        'chunk_hash': chunk_hash,
        'desired_nodes': desired,
        'actual_replicas': [{'node_id': r.node_id, 'state': r.state.value} for r in actual],
    }


def require_demo() -> None:
    if not settings.demo_mode:
        raise HTTPException(404, 'Demo mode disabled')


@router.post('/demo/node/unavailable')
def demo_node_down(payload: DemoNodeRequest, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    require_demo()
    node = db.get(StorageNode, payload.node_id)
    if not node:
        raise HTTPException(404, 'Node not found')
    node.simulated_down = True
    node.status = NodeStatus.SIMULATED_DOWN
    for replica in db.scalars(select(ChunkReplica).where(ChunkReplica.node_id == node.id)).all():
        replica.state = ReplicaState.UNAVAILABLE
    record(db, 'DEMO_NODE_UNAVAILABLE', f'{node.id} simulated unavailable', admin.id)
    db.commit()
    return serialize_node(node)


@router.post('/demo/node/restore')
def demo_node_restore(payload: DemoNodeRequest, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    require_demo()
    node = db.get(StorageNode, payload.node_id)
    if not node:
        raise HTTPException(404, 'Node not found')
    node.simulated_down = False
    node.status = NodeStatus.UNHEALTHY
    record(db, 'DEMO_NODE_RESTORED', f'{node.id} simulation cleared; heartbeat will re-evaluate health', admin.id)
    db.commit()
    return serialize_node(node)


@router.post('/demo/corrupt')
async def demo_corrupt(payload: DemoCorruptRequest, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    require_demo()
    replica = db.scalar(
        select(ChunkReplica).where(
            ChunkReplica.chunk_hash == payload.chunk_hash,
            ChunkReplica.node_id == payload.node_id,
        )
    )
    node = db.get(StorageNode, payload.node_id)
    if not replica or not node:
        raise HTTPException(404, 'Replica not found')
    await StorageClient().corrupt(node.base_url, payload.chunk_hash)
    replica.state = ReplicaState.DEGRADED
    record(db, 'DEMO_REPLICA_CORRUPTED', f'Corrupted {payload.chunk_hash[:12]} on {payload.node_id}', admin.id)
    db.commit()
    return {'ok': True}


@router.post('/demo/delete-replica')
async def demo_delete_replica(
    payload: DemoCorruptRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_user),
):
    require_demo()
    replica = db.scalar(
        select(ChunkReplica).where(
            ChunkReplica.chunk_hash == payload.chunk_hash,
            ChunkReplica.node_id == payload.node_id,
        )
    )
    node = db.get(StorageNode, payload.node_id)
    if not replica or not node:
        raise HTTPException(404, 'Replica not found')
    await StorageClient().delete(node.base_url, payload.chunk_hash)
    replica.state = ReplicaState.UNAVAILABLE
    record(
        db,
        'DEMO_REPLICA_DELETED',
        f'Deleted {payload.chunk_hash[:12]} from {payload.node_id}',
        admin.id,
    )
    db.commit()
    return {'ok': True, 'chunk_hash': payload.chunk_hash, 'node_id': payload.node_id}


@router.post('/demo/generate-duplicate')
async def demo_duplicate(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    require_demo()
    blobs = [
        b'QuorumVault-demo-A\n' * 4096,
        b'QuorumVault-demo-B\n' * 4096,
        b'QuorumVault-demo-C\n' * 4096,
    ]
    chunks = [
        ChunkDescriptor(index=i, hash=hashlib.sha256(blob).hexdigest(), size=len(blob))
        for i, blob in enumerate(blobs)
    ]
    payload = UploadSessionCreate(
        file_name='dedup-demo.bin',
        expected_size=sum(len(blob) for blob in blobs),
        content_type='application/octet-stream',
        chunks=chunks,
    )
    session, missing = create_session(db, admin.id, payload)
    for index in missing:
        item = db.scalar(
            select(UploadSessionChunk).where(
                UploadSessionChunk.session_id == session.id,
                UploadSessionChunk.chunk_index == index,
            )
        )
        assert item is not None
        await store_session_chunk(db, session, item, blobs[index])
    version = await finalize_session(db, session)
    return {
        'file_name': 'dedup-demo.bin',
        'version_number': version.version_number,
        'missing_chunks_transferred': len(missing),
        'deduplicated_chunks': len(blobs) - len(missing),
    }
