from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..dependencies import admin_user, current_user
from ..models import ChunkReplica, FileVersion, LogicalFile, ReplicaState, StorageNode, User
from ..services.health import aggregate_data_health, version_health
from ..services.project_metrics import project_metrics
from ..services.storage_client import StorageClient

router = APIRouter(prefix='/api')


class DemoReplicaRequest(BaseModel):
    chunk_hash: str = Field(min_length=64, max_length=64)
    node_id: str = Field(min_length=1, max_length=64)


def require_demo() -> None:
    if not settings.demo_mode:
        raise HTTPException(404, 'Demo mode disabled')


@router.get('/metrics')
def metrics_endpoint(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    return project_metrics(db)


@router.get('/data-health')
def data_health(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    return aggregate_data_health(db)


@router.get('/files/{file_id}/versions/{version_number}/health')
def file_version_health(
    file_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    logical = db.get(LogicalFile, file_id)
    if logical is None or logical.owner_id != user.id:
        raise HTTPException(404, 'File not found')
    version = db.scalar(
        select(FileVersion).where(
            FileVersion.logical_file_id == file_id,
            FileVersion.version_number == version_number,
        )
    )
    if version is None:
        raise HTTPException(404, 'Version not found')
    return version_health(db, version)


@router.post('/demo/delete-replica')
async def demo_delete_replica(
    payload: DemoReplicaRequest,
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
    if replica is None or node is None:
        raise HTTPException(404, 'Replica not found')
    await StorageClient().delete(node.base_url, payload.chunk_hash)
    replica.state = ReplicaState.UNAVAILABLE
    db.commit()
    return {
        'deleted': True,
        'chunk_hash': payload.chunk_hash,
        'node_id': payload.node_id,
        'state': replica.state.value,
    }
