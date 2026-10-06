from __future__ import annotations

from collections import Counter
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Chunk,
    ChunkReplica,
    FileVersion,
    FileVersionChunk,
    LogicalFile,
    NodeStatus,
    RepairJob,
    RepairState,
    ReplicaState,
)


class DataHealth(str, Enum):
    HEALTHY = 'HEALTHY'
    DEGRADED = 'DEGRADED'
    REPAIRING = 'REPAIRING'
    UNRECOVERABLE = 'UNRECOVERABLE'


def chunk_health(db: Session, chunk_hash: str) -> dict:
    replicas = db.scalars(select(ChunkReplica).where(ChunkReplica.chunk_hash == chunk_hash)).all()
    healthy_nodes = {
        replica.node_id
        for replica in replicas
        if replica.state == ReplicaState.HEALTHY
        and replica.node is not None
        and replica.node.status == NodeStatus.HEALTHY
        and not replica.node.simulated_down
    }
    active_repair = db.scalar(
        select(RepairJob.id)
        .where(
            RepairJob.chunk_hash == chunk_hash,
            RepairJob.state.in_([RepairState.PENDING, RepairState.RUNNING]),
        )
        .limit(1)
    ) is not None
    desired = settings.replication_factor
    healthy = len(healthy_nodes)
    if healthy == 0:
        status = DataHealth.UNRECOVERABLE
    elif healthy >= desired:
        status = DataHealth.HEALTHY
    elif active_repair or any(replica.state == ReplicaState.REPAIRING for replica in replicas):
        status = DataHealth.REPAIRING
    else:
        status = DataHealth.DEGRADED
    return {
        'chunk_hash': chunk_hash,
        'desired_replicas': desired,
        'healthy_replicas': healthy,
        'status': status.value,
    }


def version_health(db: Session, version: FileVersion) -> dict:
    hashes = db.scalars(
        select(FileVersionChunk.chunk_hash)
        .where(FileVersionChunk.file_version_id == version.id)
        .order_by(FileVersionChunk.chunk_index)
    ).all()
    chunk_states = [chunk_health(db, chunk_hash) for chunk_hash in hashes]
    states = {row['status'] for row in chunk_states}
    if DataHealth.UNRECOVERABLE.value in states:
        status = DataHealth.UNRECOVERABLE
    elif DataHealth.REPAIRING.value in states:
        status = DataHealth.REPAIRING
    elif DataHealth.DEGRADED.value in states:
        status = DataHealth.DEGRADED
    else:
        status = DataHealth.HEALTHY
    return {
        'status': status.value,
        'chunks': chunk_states,
    }


def aggregate_data_health(db: Session, owner_id: str | None = None) -> dict:
    logical_query = select(LogicalFile)
    if owner_id is not None:
        logical_query = logical_query.where(LogicalFile.owner_id == owner_id)
    logical_files = db.scalars(logical_query).all()

    object_counts: Counter[str] = Counter()
    latest_versions: list[FileVersion] = []
    referenced_hashes: set[str] = set()
    for logical in logical_files:
        latest = db.scalar(
            select(FileVersion)
            .where(FileVersion.logical_file_id == logical.id)
            .order_by(FileVersion.version_number.desc())
            .limit(1)
        )
        if latest is None:
            continue
        latest_versions.append(latest)
        state = version_health(db, latest)
        object_counts[state['status']] += 1
        referenced_hashes.update(
            db.scalars(
                select(FileVersionChunk.chunk_hash).where(FileVersionChunk.file_version_id == latest.id)
            ).all()
        )

    if owner_id is None:
        chunk_hashes = db.scalars(select(Chunk.hash)).all()
    else:
        chunk_hashes = sorted(referenced_hashes)
    chunk_counts: Counter[str] = Counter()
    for chunk_hash in chunk_hashes:
        chunk_counts[chunk_health(db, chunk_hash)['status']] += 1

    def normalized(counter: Counter[str]) -> dict[str, int]:
        return {state.value: int(counter.get(state.value, 0)) for state in DataHealth}

    return {
        'objects': normalized(object_counts),
        'chunks': normalized(chunk_counts),
        'object_count': len(latest_versions),
        'chunk_count': len(chunk_hashes),
    }
