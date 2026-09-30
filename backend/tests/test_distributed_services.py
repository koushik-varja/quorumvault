import asyncio
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,patch
from sqlalchemy import select
from app.db import Base,SessionLocal,engine
from app.models import Chunk,ChunkReplica,FileVersion,LogicalFile,NodeStatus,RepairJob,RepairState,ReplicaState,StorageNode,UploadSessionChunk,User
from app.schemas import ChunkDescriptor,UploadSessionCreate
from app.services.hashing import sha256_bytes
from app.services.repair import repair_chunk
from app.services.uploads import create_session,finalize_session
from app.background import heartbeat_once

def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

def add_nodes(db,count=4):
    nodes=[]
    for i in range(1,count+1):
        n=StorageNode(id=f'node-{i}',base_url=f'http://node-{i}:900{i}',status=NodeStatus.HEALTHY,last_heartbeat=datetime.now(timezone.utc));db.add(n);nodes.append(n)
    db.flush();return nodes

def test_upload_manifest_reuses_chunk_with_three_healthy_replicas():
    with SessionLocal() as db:
        u=User(email='dedup@example.com',password_hash='x');db.add(u);nodes=add_nodes(db);data=b'same chunk';h=sha256_bytes(data);c=Chunk(hash=h,size_bytes=len(data));db.add(c);db.flush()
        for n in nodes[:3]:db.add(ChunkReplica(chunk_hash=h,node_id=n.id,state=ReplicaState.HEALTHY))
        db.commit();payload=UploadSessionCreate(file_name='copy.bin',expected_size=len(data),chunks=[ChunkDescriptor(index=0,hash=h,size=len(data))])
        session,missing=create_session(db,u.id,payload)
        item=db.scalar(select(UploadSessionChunk).where(UploadSessionChunk.session_id==session.id))
        assert missing==[] and item.received is True

def test_finalize_appends_versions_without_copying_chunk_metadata_identity():
    with SessionLocal() as db:
        u=User(email='versions@example.com',password_hash='x');db.add(u);nodes=add_nodes(db);data=b'versioned';h=sha256_bytes(data);c=Chunk(hash=h,size_bytes=len(data));db.add(c);db.flush()
        for n in nodes[:3]:db.add(ChunkReplica(chunk_hash=h,node_id=n.id,state=ReplicaState.HEALTHY))
        db.commit()
        payload=UploadSessionCreate(file_name='report.pdf',expected_size=len(data),chunks=[ChunkDescriptor(index=0,hash=h,size=len(data))])
        s1,_=create_session(db,u.id,payload);s2,_=create_session(db,u.id,payload)
        with patch('app.services.uploads.StorageClient.get',new=AsyncMock(return_value=data)):
            v1=asyncio.run(finalize_session(db,s1));v2=asyncio.run(finalize_session(db,s2))
        assert (v1.version_number,v2.version_number)==(1,2)
        assert db.scalar(select(LogicalFile).where(LogicalFile.owner_id==u.id)).name=='report.pdf'
        assert len(db.scalars(select(FileVersion)).all())==2

def test_repair_creates_verified_third_replica():
    with SessionLocal() as db:
        nodes=add_nodes(db);data=b'repair-me';h=sha256_bytes(data);c=Chunk(hash=h,size_bytes=len(data));db.add(c);db.flush()
        db.add_all([ChunkReplica(chunk_hash=h,node_id='node-1',state=ReplicaState.HEALTHY),ChunkReplica(chunk_hash=h,node_id='node-2',state=ReplicaState.HEALTHY)]);db.commit()
        with patch('app.services.repair.StorageClient.get',new=AsyncMock(return_value=data)),patch('app.services.repair.StorageClient.put',new=AsyncMock(return_value={'stored':True})),patch('app.services.repair.StorageClient.check',new=AsyncMock(return_value={'exists':True,'valid':True})):
            assert asyncio.run(repair_chunk(db,h)) is True
        reps=db.scalars(select(ChunkReplica).where(ChunkReplica.chunk_hash==h,ChunkReplica.state==ReplicaState.HEALTHY)).all();job=db.scalar(select(RepairJob).where(RepairJob.chunk_hash==h))
        assert len(reps)==3 and len({r.node_id for r in reps})==3
        assert job.state==RepairState.SUCCEEDED and job.duration_ms is not None

def test_heartbeat_timeout_marks_node_and_replicas_unavailable():
    with SessionLocal() as db:
        old=datetime.now(timezone.utc)-timedelta(seconds=60);n=StorageNode(id='node-x',base_url='http://dead',status=NodeStatus.HEALTHY,last_heartbeat=old);db.add(n);data=b'x';h=sha256_bytes(data);db.add(Chunk(hash=h,size_bytes=1));db.flush();db.add(ChunkReplica(chunk_hash=h,node_id=n.id,state=ReplicaState.HEALTHY));db.commit()
        with patch('app.background.StorageClient.health',new=AsyncMock(side_effect=RuntimeError('down'))):asyncio.run(heartbeat_once())
    with SessionLocal() as db:
        n=db.get(StorageNode,'node-x');r=db.scalar(select(ChunkReplica).where(ChunkReplica.node_id=='node-x'));assert n.status==NodeStatus.UNHEALTHY and r.state==ReplicaState.UNAVAILABLE
