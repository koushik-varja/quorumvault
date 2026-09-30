import asyncio
from datetime import datetime, timezone
import logging
from sqlalchemy import select
from .config import settings
from .db import SessionLocal
from .models import ChunkReplica, NodeStatus, ReplicaState, StorageNode
from .services.storage_client import StorageClient
from .services.repair import repair_scan
from .services.integrity import integrity_scan

log = logging.getLogger('quorumvault.background')

async def heartbeat_once() -> None:
    client = StorageClient(timeout=3.0)
    with SessionLocal() as db:
        nodes = db.scalars(select(StorageNode)).all()
        for node in nodes:
            if node.simulated_down:
                node.status = NodeStatus.SIMULATED_DOWN
                for r in db.scalars(select(ChunkReplica).where(ChunkReplica.node_id == node.id)).all(): r.state = ReplicaState.UNAVAILABLE
                continue
            previous = node.status
            try:
                health = await client.health(node.base_url)
                node.status = NodeStatus.HEALTHY; node.last_heartbeat = datetime.now(timezone.utc)
                node.storage_used_bytes = int(health.get('storage_used_bytes', 0)); node.chunk_count = int(health.get('chunk_count', 0))
                if previous != NodeStatus.HEALTHY:
                    for r in db.scalars(select(ChunkReplica).where(ChunkReplica.node_id == node.id, ChunkReplica.state == ReplicaState.UNAVAILABLE)).all(): r.state = ReplicaState.DEGRADED
            except Exception:
                now=datetime.now(timezone.utc)
                last=node.last_heartbeat
                if last is not None and last.tzinfo is None: last=last.replace(tzinfo=timezone.utc)
                timed_out=last is None or (now-last).total_seconds()>=settings.heartbeat_timeout_seconds
                if timed_out:
                    node.status=NodeStatus.UNHEALTHY
                    for r in db.scalars(select(ChunkReplica).where(ChunkReplica.node_id==node.id)).all():
                        if r.state==ReplicaState.HEALTHY:r.state=ReplicaState.UNAVAILABLE
        db.commit()

async def heartbeat_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try: await heartbeat_once()
        except Exception as exc: log.warning('heartbeat_loop_error: %s', exc)
        try: await asyncio.wait_for(stop.wait(), timeout=settings.heartbeat_interval_seconds)
        except asyncio.TimeoutError: pass

async def repair_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            with SessionLocal() as db: await repair_scan(db)
        except Exception as exc: log.warning('repair_loop_error: %s', exc)
        try: await asyncio.wait_for(stop.wait(), timeout=settings.repair_interval_seconds)
        except asyncio.TimeoutError: pass

async def integrity_loop(stop: asyncio.Event) -> None:
    if settings.integrity_interval_seconds <= 0: return
    while not stop.is_set():
        try:
            with SessionLocal() as db: await integrity_scan(db)
        except Exception as exc: log.warning('integrity_loop_error: %s', exc)
        try: await asyncio.wait_for(stop.wait(), timeout=settings.integrity_interval_seconds)
        except asyncio.TimeoutError: pass
