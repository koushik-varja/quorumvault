import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Chunk, ChunkReplica, NodeStatus, RepairJob, RepairState, ReplicaState, StorageNode
from .audit import record
from .metrics import metrics
from .placement import ConsistentHashRing
from .storage_client import StorageClient
from .versioning import transaction_key_lock


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _expire_stale_repairs(db: Session, chunk_hash: str) -> None:
    now = datetime.now(timezone.utc)
    active = db.scalars(
        select(RepairJob).where(
            RepairJob.chunk_hash == chunk_hash,
            RepairJob.state.in_([RepairState.PENDING, RepairState.RUNNING]),
        )
    ).all()
    for job in active:
        created = _aware(job.created_at)
        if created is None or (now - created).total_seconds() <= settings.repair_lease_seconds:
            continue
        job.state = RepairState.FAILED
        job.error = 'repair lease expired before completion'
        job.finished_at = now
        if job.target_node_id:
            reserved = db.scalar(
                select(ChunkReplica).where(
                    ChunkReplica.chunk_hash == chunk_hash,
                    ChunkReplica.node_id == job.target_node_id,
                    ChunkReplica.state == ReplicaState.REPAIRING,
                )
            )
            if reserved is not None:
                reserved.state = ReplicaState.UNAVAILABLE


async def repair_chunk(db: Session, chunk_hash: str) -> bool:
    source_ids: list[str] = []
    target_id: str | None = None
    job_id: str | None = None
    node_map: dict[str, StorageNode] = {}

    with transaction_key_lock(db, f'repair:{chunk_hash}'):
        _expire_stale_repairs(db, chunk_hash)
        active = db.scalar(
            select(RepairJob).where(
                RepairJob.chunk_hash == chunk_hash,
                RepairJob.state.in_([RepairState.PENDING, RepairState.RUNNING]),
            )
        )
        if active is not None:
            db.commit()
            return False

        chunk = db.get(Chunk, chunk_hash)
        if chunk is None:
            db.commit()
            return False

        nodes = db.scalars(
            select(StorageNode).where(
                StorageNode.status == NodeStatus.HEALTHY,
                StorageNode.simulated_down.is_(False),
            )
        ).all()
        node_map = {node.id: node for node in nodes}
        replicas = db.scalars(
            select(ChunkReplica).where(ChunkReplica.chunk_hash == chunk_hash)
        ).all()
        valid = [
            replica
            for replica in replicas
            if replica.state == ReplicaState.HEALTHY and replica.node_id in node_map
        ]
        if len(valid) >= settings.replication_factor:
            db.commit()
            return False
        if not valid:
            db.commit()
            return False

        occupied = {
            replica.node_id
            for replica in replicas
            if replica.state in (ReplicaState.HEALTHY, ReplicaState.REPAIRING)
        }
        ring = ConsistentHashRing(list(node_map))
        candidates = [
            node_id
            for node_id in ring.replicas(chunk_hash, len(node_map))
            if node_id not in occupied
        ]
        if not candidates:
            db.commit()
            return False

        source_ids = [replica.node_id for replica in valid]
        target_id = candidates[0]
        reserved = db.scalar(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == chunk_hash,
                ChunkReplica.node_id == target_id,
            )
        )
        if reserved is None:
            db.add(
                ChunkReplica(
                    chunk_hash=chunk_hash,
                    node_id=target_id,
                    state=ReplicaState.REPAIRING,
                )
            )
        else:
            reserved.state = ReplicaState.REPAIRING

        job = RepairJob(
            chunk_hash=chunk_hash,
            source_node_id=source_ids[0],
            target_node_id=target_id,
            state=RepairState.RUNNING,
        )
        db.add(job)
        db.commit()
        job_id = job.id

    assert target_id is not None and job_id is not None
    client = StorageClient()
    started = time.perf_counter()
    data = None
    source_id = None

    for candidate in source_ids:
        try:
            data = await client.get(node_map[candidate].base_url, chunk_hash)
            source_id = candidate
            break
        except Exception:
            replica = db.scalar(
                select(ChunkReplica).where(
                    ChunkReplica.chunk_hash == chunk_hash,
                    ChunkReplica.node_id == candidate,
                )
            )
            if replica is not None:
                replica.state = ReplicaState.CORRUPTED
            db.commit()

    job = db.get(RepairJob, job_id)
    if job is None:
        return False

    if data is None or source_id is None:
        job.state = RepairState.FAILED
        job.error = 'no verified source replica available'
        job.finished_at = datetime.now(timezone.utc)
        job.duration_ms = int((time.perf_counter() - started) * 1000)
        reserved = db.scalar(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == chunk_hash,
                ChunkReplica.node_id == target_id,
            )
        )
        if reserved is not None and reserved.state == ReplicaState.REPAIRING:
            reserved.state = ReplicaState.UNAVAILABLE
        record(db, 'REPAIR_FAILED', f'No verified source for {chunk_hash[:12]}')
        db.commit()
        metrics.incr('repairs_failed')
        return False

    job.source_node_id = source_id
    try:
        await client.put(node_map[target_id].base_url, chunk_hash, data)
        check = await client.check(node_map[target_id].base_url, chunk_hash)
        if not check.get('valid'):
            raise ValueError('repair target checksum failed')

        reserved = db.scalar(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == chunk_hash,
                ChunkReplica.node_id == target_id,
            )
        )
        if reserved is None:
            reserved = ChunkReplica(chunk_hash=chunk_hash, node_id=target_id)
            db.add(reserved)
        reserved.state = ReplicaState.HEALTHY
        reserved.checksum_verified_at = datetime.now(timezone.utc)

        job.state = RepairState.SUCCEEDED
        job.finished_at = datetime.now(timezone.utc)
        job.duration_ms = int((time.perf_counter() - started) * 1000)
        record(db, 'REPAIR_SUCCEEDED', f'Repaired {chunk_hash[:12]} from {source_id} to {target_id}')
        db.commit()
        metrics.incr('repairs_succeeded')
        metrics.set('last_repair_duration_ms', job.duration_ms or 0)
        return True
    except Exception as exc:
        job.state = RepairState.FAILED
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        job.duration_ms = int((time.perf_counter() - started) * 1000)
        reserved = db.scalar(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == chunk_hash,
                ChunkReplica.node_id == target_id,
            )
        )
        if reserved is not None and reserved.state == ReplicaState.REPAIRING:
            reserved.state = ReplicaState.UNAVAILABLE
        record(db, 'REPAIR_FAILED', f'Repair failed for {chunk_hash[:12]}: {exc}')
        db.commit()
        metrics.incr('repairs_failed')
        return False


async def repair_scan(db: Session, limit: int = 100) -> dict:
    chunks = db.scalars(select(Chunk).limit(limit)).all()
    under_replicated = repaired = unrecoverable = 0
    for chunk in chunks:
        replicas = db.scalars(
            select(ChunkReplica).where(ChunkReplica.chunk_hash == chunk.hash)
        ).all()
        healthy = sum(
            1
            for replica in replicas
            if replica.state == ReplicaState.HEALTHY
            and replica.node is not None
            and replica.node.status == NodeStatus.HEALTHY
            and not replica.node.simulated_down
        )
        if healthy >= settings.replication_factor:
            continue
        under_replicated += 1
        if healthy == 0:
            unrecoverable += 1
            continue
        deficit = settings.replication_factor - healthy
        for _ in range(deficit):
            if await repair_chunk(db, chunk.hash):
                repaired += 1
                db.expire_all()
            else:
                break
    metrics.set('degraded_chunks', under_replicated)
    return {
        'under_replicated': under_replicated,
        'repaired': repaired,
        'unrecoverable': unrecoverable,
    }
