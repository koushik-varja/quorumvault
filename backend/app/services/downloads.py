import hashlib
from collections.abc import AsyncIterator
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import ChunkReplica, FileVersion, FileVersionChunk, ReplicaState, StorageNode, NodeStatus
from .storage_client import StorageClient
from .audit import record
from .metrics import metrics

async def iter_version_bytes(db: Session, version: FileVersion, actor_id: str | None = None) -> AsyncIterator[bytes]:
    items = db.scalars(select(FileVersionChunk).where(FileVersionChunk.file_version_id == version.id).order_by(FileVersionChunk.chunk_index)).all()
    client = StorageClient(); file_hasher = hashlib.sha256()
    total = 0
    for item in items:
        replicas = db.scalars(select(ChunkReplica).where(ChunkReplica.chunk_hash == item.chunk_hash).order_by(ChunkReplica.created_at)).all()
        data = None
        for replica in replicas:
            if replica.state not in (ReplicaState.HEALTHY, ReplicaState.DEGRADED): continue
            node = db.get(StorageNode, replica.node_id)
            if not node or node.status != NodeStatus.HEALTHY or node.simulated_down: continue
            try:
                data = await client.get(node.base_url, item.chunk_hash)
                replica.state = ReplicaState.HEALTHY
                break
            except Exception:
                replica.state = ReplicaState.CORRUPTED
                record(db, 'READ_REPLICA_REJECTED', f'Rejected replica {replica.node_id} for {item.chunk_hash[:12]}', actor_id)
        if data is None:
            db.commit()
            raise HTTPException(status_code=503, detail=f'No valid replica available for chunk {item.chunk_index}')
        file_hasher.update(data); total += len(data); yield data
    if file_hasher.hexdigest() != version.file_sha256:
        raise HTTPException(status_code=500, detail='Reconstructed file checksum mismatch')
    db.commit(); metrics.incr('files_downloaded'); metrics.incr('bytes_downloaded', total)
