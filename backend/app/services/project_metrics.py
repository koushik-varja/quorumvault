from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Chunk,
    ChunkReplica,
    FileVersion,
    FileVersionChunk,
    NodeStatus,
    RepairJob,
    RepairState,
    ReplicaState,
    StorageNode,
)
from .health import aggregate_data_health
from .metrics import metrics


def project_metrics(db: Session) -> dict:
    logical_bytes = int(db.scalar(select(func.coalesce(func.sum(FileVersion.size_bytes), 0))) or 0)
    unique_chunk_bytes = int(db.scalar(select(func.coalesce(func.sum(Chunk.size_bytes), 0))) or 0)
    total_chunks = int(db.scalar(select(func.count()).select_from(FileVersionChunk)) or 0)
    unique_chunks = int(db.scalar(select(func.count()).select_from(Chunk)) or 0)
    nodes = db.scalars(select(StorageNode)).all()
    physical_bytes = sum(int(node.storage_used_bytes or 0) for node in nodes)
    dedup_saved = max(0, logical_bytes - unique_chunk_bytes)
    dedup_pct = (dedup_saved / logical_bytes * 100.0) if logical_bytes else 0.0

    data_health = aggregate_data_health(db)
    corrupted_chunks = int(
        db.scalar(
            select(func.count(func.distinct(ChunkReplica.chunk_hash)))
            .where(ChunkReplica.state == ReplicaState.CORRUPTED)
        )
        or 0
    )
    active_repairs = int(
        db.scalar(
            select(func.count())
            .select_from(RepairJob)
            .where(RepairJob.state.in_([RepairState.PENDING, RepairState.RUNNING]))
        )
        or 0
    )
    completed_repairs = int(
        db.scalar(
            select(func.count()).select_from(RepairJob).where(RepairJob.state == RepairState.SUCCEEDED)
        )
        or 0
    )
    failed_repairs = int(
        db.scalar(
            select(func.count()).select_from(RepairJob).where(RepairJob.state == RepairState.FAILED)
        )
        or 0
    )
    healthy_nodes = sum(1 for node in nodes if node.status == NodeStatus.HEALTHY and not node.simulated_down)

    return {
        'nodes': {
            'healthy': healthy_nodes,
            'unhealthy': len(nodes) - healthy_nodes,
            'total': len(nodes),
        },
        'storage': {
            'total_chunks': total_chunks,
            'unique_chunks': unique_chunks,
            'logical_bytes_stored': logical_bytes,
            'unique_chunk_bytes': unique_chunk_bytes,
            'physical_bytes_stored': physical_bytes,
            'dedup_saved_bytes': dedup_saved,
            'dedup_percentage': round(dedup_pct, 3),
        },
        'data_health': data_health,
        'integrity': {
            'corrupted_chunks_current': corrupted_chunks,
            'corrupted_chunks_found_total': int(metrics.snapshot().get('integrity_errors', '0') or 0),
        },
        'repairs': {
            'active': active_repairs,
            'completed': completed_repairs,
            'failed': failed_repairs,
        },
        'counters': metrics.snapshot(),
    }
