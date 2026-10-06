import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import Chunk, ChunkReplica, NodeStatus, RepairJob, RepairState, ReplicaState, StorageNode
from app.services.hashing import sha256_bytes
from app.services.health import DataHealth, chunk_health
from app.services.placement import ConsistentHashRing
from app.services.repair import repair_chunk


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _nodes(db, count=4):
    rows = []
    for index in range(1, count + 1):
        row = StorageNode(
            id=f'node-{index}',
            base_url=f'http://node-{index}:900{index}',
            status=NodeStatus.HEALTHY,
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def test_consistent_hash_is_deterministic_and_membership_change_is_bounded():
    keys = [sha256_bytes(f'chunk-{i}'.encode()) for i in range(5000)]
    ring_a = ConsistentHashRing(['node-1', 'node-2', 'node-3', 'node-4'])
    ring_b = ConsistentHashRing(['node-4', 'node-2', 'node-1', 'node-3'])
    assert [ring_a.replicas(key, 3) for key in keys] == [ring_b.replicas(key, 3) for key in keys]

    joined = ConsistentHashRing(['node-1', 'node-2', 'node-3', 'node-4', 'node-5'])
    changed = sum(ring_a.replicas(key, 3) != joined.replicas(key, 3) for key in keys)
    assert 0 < changed < len(keys)


def test_data_health_transitions_degraded_repairing_healthy_and_unrecoverable():
    with SessionLocal() as db:
        nodes = _nodes(db)
        data = b'health-state'
        chunk_hash = sha256_bytes(data)
        db.add(Chunk(hash=chunk_hash, size_bytes=len(data)))
        db.flush()
        for node in nodes[:2]:
            db.add(ChunkReplica(chunk_hash=chunk_hash, node_id=node.id, state=ReplicaState.HEALTHY))
        db.commit()

        assert chunk_health(db, chunk_hash)['status'] == DataHealth.DEGRADED.value

        db.add(
            RepairJob(
                chunk_hash=chunk_hash,
                source_node_id='node-1',
                target_node_id='node-3',
                state=RepairState.RUNNING,
            )
        )
        db.commit()
        assert chunk_health(db, chunk_hash)['status'] == DataHealth.REPAIRING.value

        db.query(RepairJob).delete()
        db.add(ChunkReplica(chunk_hash=chunk_hash, node_id='node-3', state=ReplicaState.HEALTHY))
        db.commit()
        assert chunk_health(db, chunk_hash)['status'] == DataHealth.HEALTHY.value

        for replica in db.scalars(select(ChunkReplica).where(ChunkReplica.chunk_hash == chunk_hash)).all():
            replica.state = ReplicaState.CORRUPTED
        db.commit()
        assert chunk_health(db, chunk_hash)['status'] == DataHealth.UNRECOVERABLE.value


def test_active_repair_suppresses_duplicate_work():
    with SessionLocal() as db:
        nodes = _nodes(db)
        data = b'repair-lock'
        chunk_hash = sha256_bytes(data)
        db.add(Chunk(hash=chunk_hash, size_bytes=len(data)))
        db.flush()
        db.add_all(
            [
                ChunkReplica(chunk_hash=chunk_hash, node_id=nodes[0].id, state=ReplicaState.HEALTHY),
                ChunkReplica(chunk_hash=chunk_hash, node_id=nodes[1].id, state=ReplicaState.HEALTHY),
                RepairJob(
                    chunk_hash=chunk_hash,
                    source_node_id=nodes[0].id,
                    target_node_id=nodes[2].id,
                    state=RepairState.RUNNING,
                ),
            ]
        )
        db.commit()
        with patch('app.services.repair.StorageClient.put', new=AsyncMock()) as put:
            assert asyncio.run(repair_chunk(db, chunk_hash)) is False
            put.assert_not_awaited()


def test_repair_retry_is_idempotent_after_success():
    with SessionLocal() as db:
        nodes = _nodes(db)
        data = b'idempotent-repair'
        chunk_hash = sha256_bytes(data)
        db.add(Chunk(hash=chunk_hash, size_bytes=len(data)))
        db.flush()
        db.add_all(
            [
                ChunkReplica(chunk_hash=chunk_hash, node_id=nodes[0].id, state=ReplicaState.HEALTHY),
                ChunkReplica(chunk_hash=chunk_hash, node_id=nodes[1].id, state=ReplicaState.HEALTHY),
            ]
        )
        db.commit()
        with (
            patch('app.services.repair.StorageClient.get', new=AsyncMock(return_value=data)),
            patch('app.services.repair.StorageClient.put', new=AsyncMock(return_value={'stored': True})),
            patch('app.services.repair.StorageClient.check', new=AsyncMock(return_value={'exists': True, 'valid': True})),
        ):
            assert asyncio.run(repair_chunk(db, chunk_hash)) is True
            assert asyncio.run(repair_chunk(db, chunk_hash)) is False

        replicas = db.scalars(
            select(ChunkReplica).where(
                ChunkReplica.chunk_hash == chunk_hash,
                ChunkReplica.state == ReplicaState.HEALTHY,
            )
        ).all()
        assert len(replicas) == 3
        assert len({replica.node_id for replica in replicas}) == 3
