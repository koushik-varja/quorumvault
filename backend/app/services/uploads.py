from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Chunk,
    ChunkReplica,
    LogicalFile,
    NodeStatus,
    ReplicaState,
    StorageNode,
    UploadSession,
    UploadSessionChunk,
    UploadStatus,
)
from ..schemas import UploadSessionCreate
from .audit import record
from .hashing import sha256_bytes
from .metrics import metrics
from .placement import ConsistentHashRing
from .storage_client import StorageClient
from .versioning import create_version, get_or_create_logical_file, transaction_key_lock

SAFE_NAME = re.compile(r'[^A-Za-z0-9._()\- ]+')


def safe_filename(name: str) -> str:
    cleaned = SAFE_NAME.sub('_', name).strip(' .')
    if not cleaned or cleaned in {'.', '..'}:
        raise HTTPException(status_code=400, detail='Invalid filename')
    return cleaned[:255]


def healthy_replica_count(chunk: Chunk) -> int:
    return sum(
        1
        for r in chunk.replicas
        if r.state == ReplicaState.HEALTHY
        and r.node
        and r.node.status == NodeStatus.HEALTHY
        and not r.node.simulated_down
    )


def _get_or_create_chunk(db: Session, chunk_hash: str, size_bytes: int) -> Chunk:
    dialect = db.bind.dialect.name if db.bind is not None else ''
    values = {'hash': chunk_hash, 'size_bytes': size_bytes}
    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert

        db.execute(insert(Chunk).values(**values).on_conflict_do_nothing(index_elements=[Chunk.hash]))
        db.flush()
    elif dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert

        db.execute(insert(Chunk).values(**values).on_conflict_do_nothing(index_elements=[Chunk.hash]))
        db.flush()
    else:
        chunk = db.get(Chunk, chunk_hash)
        if chunk is None:
            db.add(Chunk(**values))
            db.flush()
    chunk = db.get(Chunk, chunk_hash)
    if chunk is None:
        raise RuntimeError('chunk metadata creation failed')
    if chunk.size_bytes != size_bytes:
        raise HTTPException(status_code=409, detail='Hash collision metadata mismatch')
    return chunk


def _upsert_replica(db: Session, chunk_hash: str, node_id: str) -> None:
    verified = datetime.now(timezone.utc)
    dialect = db.bind.dialect.name if db.bind is not None else ''
    values = {
        'chunk_hash': chunk_hash,
        'node_id': node_id,
        'state': ReplicaState.HEALTHY,
        'checksum_verified_at': verified,
    }
    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(ChunkReplica).values(**values).on_conflict_do_update(
            index_elements=[ChunkReplica.chunk_hash, ChunkReplica.node_id],
            set_={'state': ReplicaState.HEALTHY, 'checksum_verified_at': verified},
        )
        db.execute(stmt)
    elif dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert

        stmt = insert(ChunkReplica).values(**values).on_conflict_do_update(
            index_elements=[ChunkReplica.chunk_hash, ChunkReplica.node_id],
            set_={'state': ReplicaState.HEALTHY, 'checksum_verified_at': verified},
        )
        db.execute(stmt)
    else:
        existing = db.scalar(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == chunk_hash,
                ChunkReplica.node_id == node_id,
            )
        )
        if existing:
            existing.state = ReplicaState.HEALTHY
            existing.checksum_verified_at = verified
        else:
            db.add(ChunkReplica(**values))
    db.flush()


def create_session(db: Session, owner_id: str, payload: UploadSessionCreate) -> tuple[UploadSession, list[int]]:
    name = safe_filename(payload.file_name)
    if payload.expected_size > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail='Upload exceeds configured limit')
    if sum(c.size for c in payload.chunks) != payload.expected_size:
        raise HTTPException(status_code=400, detail='Chunk sizes do not match expected file size')
    indexes = [c.index for c in payload.chunks]
    if indexes != list(range(len(indexes))):
        raise HTTPException(status_code=400, detail='Chunk indexes must be contiguous from zero')
    session = UploadSession(
        owner_id=owner_id,
        file_name=name,
        content_type=payload.content_type,
        expected_size=payload.expected_size,
        chunk_size=settings.chunk_size_bytes,
    )
    db.add(session)
    db.flush()
    missing: list[int] = []
    for c in payload.chunks:
        existing = db.get(Chunk, c.hash)
        received = bool(existing and healthy_replica_count(existing) >= settings.replication_factor)
        db.add(
            UploadSessionChunk(
                session_id=session.id,
                chunk_index=c.index,
                chunk_hash=c.hash,
                size_bytes=c.size,
                received=received,
            )
        )
        if not received:
            missing.append(c.index)
    record(db, 'UPLOAD_SESSION_CREATED', f'Upload session {session.id} created for {name}', owner_id)
    db.commit()
    return session, missing


async def store_session_chunk(db: Session, session: UploadSession, item: UploadSessionChunk, data: bytes) -> dict:
    if session.status != UploadStatus.ACTIVE:
        raise HTTPException(status_code=409, detail='Upload session is not active')
    if len(data) != item.size_bytes:
        raise HTTPException(status_code=400, detail='Chunk size mismatch')
    if sha256_bytes(data) != item.chunk_hash:
        raise HTTPException(status_code=400, detail='Chunk SHA-256 mismatch')

    _get_or_create_chunk(db, item.chunk_hash, len(data))
    nodes = db.scalars(
        select(StorageNode).where(
            StorageNode.status == NodeStatus.HEALTHY,
            StorageNode.simulated_down.is_(False),
        )
    ).all()
    if len(nodes) < settings.replication_factor:
        raise HTTPException(status_code=503, detail='Insufficient healthy storage nodes')

    healthy_existing: set[str] = set()
    for replica in db.scalars(
        select(ChunkReplica).where(
            ChunkReplica.chunk_hash == item.chunk_hash,
            ChunkReplica.state == ReplicaState.HEALTHY,
        )
    ).all():
        node = next((n for n in nodes if n.id == replica.node_id), None)
        if node is not None:
            healthy_existing.add(replica.node_id)

    ring = ConsistentHashRing([n.id for n in nodes])
    selected = ring.replicas(item.chunk_hash, len(nodes))
    client = StorageClient()
    node_map = {n.id: n for n in nodes}
    satisfied = set(healthy_existing)

    for node_id in selected:
        if len(satisfied) >= settings.replication_factor:
            break
        if node_id in satisfied:
            continue
        try:
            await client.put(node_map[node_id].base_url, item.chunk_hash, data)
            check = await client.check(node_map[node_id].base_url, item.chunk_hash)
            if not check.get('valid'):
                raise ValueError('post-write verification failed')
            _upsert_replica(db, item.chunk_hash, node_id)
            satisfied.add(node_id)
        except Exception as exc:
            record(db, 'REPLICA_WRITE_FAILED', f'{item.chunk_hash[:12]} to {node_id}: {exc}', session.owner_id)

    if len(satisfied) < settings.replication_factor:
        db.rollback()
        raise HTTPException(status_code=503, detail='Could not establish required replicas')

    item = db.scalar(
        select(UploadSessionChunk).where(
            UploadSessionChunk.session_id == session.id,
            UploadSessionChunk.chunk_index == item.chunk_index,
        )
    )
    assert item is not None
    item.received = True
    record(db, 'CHUNK_STORED', f'Chunk {item.chunk_hash[:12]} replicated to {len(satisfied)} nodes', session.owner_id)
    db.commit()
    metrics.incr('chunks_uploaded')
    metrics.incr('bytes_uploaded', len(data))
    return {
        'chunk_hash': item.chunk_hash,
        'replicas': sorted(satisfied),
        'deduplicated': bool(healthy_existing),
    }


async def finalize_session(db: Session, session: UploadSession):
    if session.status != UploadStatus.ACTIVE:
        raise HTTPException(status_code=409, detail='Upload session already finalized')
    items = db.scalars(
        select(UploadSessionChunk)
        .where(UploadSessionChunk.session_id == session.id)
        .order_by(UploadSessionChunk.chunk_index)
    ).all()
    missing = [i.chunk_index for i in items if not i.received]
    if missing:
        raise HTTPException(status_code=409, detail={'missing_chunks': missing})

    client = StorageClient()
    file_hasher = hashlib.sha256()
    for item in items:
        replicas = db.scalars(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == item.chunk_hash,
                ChunkReplica.state == ReplicaState.HEALTHY,
            )
        ).all()
        data = None
        for replica in replicas:
            node = db.get(StorageNode, replica.node_id)
            if not node or node.status != NodeStatus.HEALTHY or node.simulated_down:
                continue
            try:
                data = await client.get(node.base_url, item.chunk_hash)
                break
            except Exception:
                continue
        if data is None:
            raise HTTPException(status_code=503, detail=f'No verified replica for chunk {item.chunk_hash[:12]}')
        file_hasher.update(data)

    lock_key = f'file:{session.owner_id}:{session.file_name}'
    with transaction_key_lock(db, lock_key):
        db.refresh(session)
        if session.status != UploadStatus.ACTIVE:
            raise HTTPException(status_code=409, detail='Upload session already finalized')
        logical = get_or_create_logical_file(
            db,
            owner_id=session.owner_id,
            name=session.file_name,
            content_type=session.content_type,
        )
        if db.bind is not None and db.bind.dialect.name == 'postgresql':
            logical = db.scalar(select(LogicalFile).where(LogicalFile.id == logical.id).with_for_update())
            assert logical is not None
        version = create_version(
            db,
            logical=logical,
            size_bytes=session.expected_size,
            file_sha256=file_hasher.hexdigest(),
            chunks=[(i.chunk_hash, i.chunk_index, i.size_bytes) for i in items],
        )
        session.status = UploadStatus.FINALIZED
        record(db, 'FILE_VERSION_CREATED', f'{logical.name} v{version.version_number} finalized', session.owner_id)
        db.commit()
    metrics.incr('files_uploaded')
    return version
