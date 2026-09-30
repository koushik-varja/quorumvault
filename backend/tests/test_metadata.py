from sqlalchemy import select
from app.db import Base,SessionLocal,engine
from app.models import Chunk,FileVersion,FileVersionChunk,LogicalFile,Snapshot,SnapshotEntry,UploadSession,UploadSessionChunk,UploadStatus,User
from app.services.gc import chunk_gc_eligible
from app.services.snapshots import create_snapshot,restore_snapshot

def setup_function():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

def make_user_file(db):
    u=User(email='u@example.com',password_hash='x');db.add(u);db.flush()
    f=LogicalFile(owner_id=u.id,name='report.pdf');db.add(f);db.flush()
    c=Chunk(hash='a'*64,size_bytes=3);db.add(c);db.flush()
    v=FileVersion(logical_file_id=f.id,version_number=1,size_bytes=3,file_sha256='b'*64);db.add(v);db.flush()
    db.add(FileVersionChunk(file_version_id=v.id,chunk_hash=c.hash,chunk_index=0,size_bytes=3));db.commit();return u,f,c,v

def test_snapshot_is_immutable_reference_and_restore_creates_new_version():
    with SessionLocal() as db:
        u,f,c,v=make_user_file(db)
        s=create_snapshot(db,u.id,'Before change')
        assert len(s.entries)==1 and s.entries[0].file_version_id==v.id
        restored=restore_snapshot(db,s,u.id)
        assert len(restored)==1 and restored[0].version_number==2
        refreshed=db.get(Snapshot,s.id)
        assert refreshed.entries[0].file_version_id==v.id

def test_gc_rejects_retained_version_reference():
    with SessionLocal() as db:
        u,f,c,v=make_user_file(db)
        assert chunk_gc_eligible(db,c.hash) is False

def test_gc_rejects_active_upload_reference_and_allows_orphan():
    with SessionLocal() as db:
        u=User(email='u@example.com',password_hash='x');db.add(u);db.flush()
        c=Chunk(hash='c'*64,size_bytes=1);db.add(c);db.flush()
        s=UploadSession(owner_id=u.id,file_name='x',expected_size=1,chunk_size=4,status=UploadStatus.ACTIVE);db.add(s);db.flush()
        db.add(UploadSessionChunk(session_id=s.id,chunk_index=0,chunk_hash=c.hash,size_bytes=1,received=True));db.commit()
        assert chunk_gc_eligible(db,c.hash) is False
        s.status=UploadStatus.ABORTED;db.commit()
        assert chunk_gc_eligible(db,c.hash) is True
