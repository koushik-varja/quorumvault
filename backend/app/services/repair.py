import time
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import settings
from ..models import Chunk, ChunkReplica, NodeStatus, RepairJob, RepairState, ReplicaState, StorageNode
from .placement import ConsistentHashRing
from .storage_client import StorageClient
from .audit import record
from .metrics import metrics

async def repair_chunk(db: Session, chunk_hash: str) -> bool:
    active = db.scalar(select(RepairJob).where(RepairJob.chunk_hash == chunk_hash, RepairJob.state.in_([RepairState.PENDING, RepairState.RUNNING])))
    if active: return False
    chunk = db.get(Chunk, chunk_hash)
    if not chunk: return False
    nodes = db.scalars(select(StorageNode).where(StorageNode.status == NodeStatus.HEALTHY, StorageNode.simulated_down.is_(False))).all()
    node_map = {n.id: n for n in nodes}
    valid_replicas = [r for r in chunk.replicas if r.state == ReplicaState.HEALTHY and r.node_id in node_map]
    if len(valid_replicas) >= min(settings.replication_factor, len(nodes)): return False
    client = StorageClient(); source = None; data = None
    for replica in valid_replicas:
        try:
            data = await client.get(node_map[replica.node_id].base_url, chunk_hash); source = replica; break
        except Exception:
            replica.state = ReplicaState.CORRUPTED
    if data is None:
        db.commit(); return False
    occupied = {r.node_id for r in chunk.replicas if r.state in (ReplicaState.HEALTHY, ReplicaState.REPAIRING)}
    ring = ConsistentHashRing(list(node_map))
    candidates = [nid for nid in ring.replicas(chunk_hash, len(node_map)) if nid not in occupied]
    if not candidates: db.commit(); return False
    target_id = candidates[0]
    job = RepairJob(chunk_hash=chunk_hash, source_node_id=source.node_id, target_node_id=target_id, state=RepairState.RUNNING)
    db.add(job); db.commit(); start = time.perf_counter()
    try:
        await client.put(node_map[target_id].base_url, chunk_hash, data)
        check = await client.check(node_map[target_id].base_url, chunk_hash)
        if not check.get('valid'): raise ValueError('repair target checksum failed')
        existing = db.scalar(select(ChunkReplica).where(ChunkReplica.chunk_hash == chunk_hash, ChunkReplica.node_id == target_id))
        if existing:
            existing.state = ReplicaState.HEALTHY; existing.checksum_verified_at = datetime.now(timezone.utc)
        else:
            db.add(ChunkReplica(chunk_hash=chunk_hash, node_id=target_id, state=ReplicaState.HEALTHY, checksum_verified_at=datetime.now(timezone.utc)))
        job = db.get(RepairJob, job.id); job.state = RepairState.SUCCEEDED; job.finished_at = datetime.now(timezone.utc); job.duration_ms = int((time.perf_counter()-start)*1000)
        record(db, 'REPAIR_SUCCEEDED', f'Repaired {chunk_hash[:12]} from {source.node_id} to {target_id}')
        db.commit(); metrics.incr('repairs_succeeded'); metrics.set('last_repair_duration_ms', job.duration_ms or 0); return True
    except Exception as exc:
        job = db.get(RepairJob, job.id); job.state = RepairState.FAILED; job.error = str(exc); job.finished_at = datetime.now(timezone.utc); job.duration_ms = int((time.perf_counter()-start)*1000)
        record(db, 'REPAIR_FAILED', f'Repair failed for {chunk_hash[:12]}: {exc}')
        db.commit(); metrics.incr('repairs_failed'); return False

async def repair_scan(db: Session, limit: int = 100) -> dict:
    chunks = db.scalars(select(Chunk).limit(limit)).all(); attempted = repaired = 0
    for chunk in chunks:
        healthy = sum(1 for r in chunk.replicas if r.state == ReplicaState.HEALTHY and r.node and r.node.status == NodeStatus.HEALTHY and not r.node.simulated_down)
        if healthy < settings.replication_factor:
            attempted += 1
            deficit=settings.replication_factor-healthy
            for _ in range(deficit):
                if await repair_chunk(db,chunk.hash):
                    repaired+=1;db.expire_all()
                else:break
    metrics.set('degraded_chunks', attempted)
    return {'under_replicated': attempted, 'repaired': repaired}
