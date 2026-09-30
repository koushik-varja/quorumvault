from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import ChunkReplica, NodeStatus, ReplicaState, StorageNode
from .storage_client import StorageClient
from .audit import record
from .metrics import metrics

async def integrity_scan(db: Session, limit: int = 1000) -> dict:
    replicas = db.scalars(select(ChunkReplica).limit(limit)).all(); checked = corrupted = unavailable = 0
    client = StorageClient()
    for replica in replicas:
        node = db.get(StorageNode, replica.node_id)
        if not node or node.status != NodeStatus.HEALTHY or node.simulated_down:
            replica.state = ReplicaState.UNAVAILABLE; unavailable += 1; continue
        checked += 1
        try:
            result = await client.check(node.base_url, replica.chunk_hash)
            if result.get('valid'):
                replica.state = ReplicaState.HEALTHY; replica.checksum_verified_at = datetime.now(timezone.utc)
            else:
                replica.state = ReplicaState.CORRUPTED; corrupted += 1
                record(db, 'CORRUPTION_DETECTED', f'Checksum failed for {replica.chunk_hash[:12]} on {replica.node_id}')
        except Exception:
            replica.state = ReplicaState.UNAVAILABLE; unavailable += 1
    db.commit(); metrics.incr('integrity_scans'); metrics.incr('integrity_errors', corrupted)
    return {'checked': checked, 'corrupted': corrupted, 'unavailable': unavailable}
