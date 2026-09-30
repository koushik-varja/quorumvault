from sqlalchemy import exists,select
from sqlalchemy.orm import Session
from ..models import Chunk,FileVersionChunk,StorageNode,UploadSession,UploadSessionChunk,UploadStatus
from .storage_client import StorageClient
from .audit import record

def chunk_gc_eligible(db:Session,chunk_hash:str)->bool:
    version_ref=db.scalar(select(exists().where(FileVersionChunk.chunk_hash==chunk_hash)))
    active_upload_ref=db.scalar(select(exists().where(UploadSessionChunk.chunk_hash==chunk_hash,UploadSessionChunk.session_id==UploadSession.id,UploadSession.status==UploadStatus.ACTIVE)))
    return not version_ref and not active_upload_ref

async def collect_garbage(db:Session,limit:int=100)->dict:
    client=StorageClient();eligible=deleted=deferred=0
    for chunk in db.scalars(select(Chunk).limit(limit)).all():
        if not chunk_gc_eligible(db,chunk.hash):continue
        eligible+=1;ok=True
        for replica in list(chunk.replicas):
            node=db.get(StorageNode,replica.node_id)
            if not node:continue
            try:await client.delete(node.base_url,chunk.hash)
            except Exception:ok=False
        if ok:
            record(db,'CHUNK_GARBAGE_COLLECTED',f'Deleted unreferenced chunk {chunk.hash[:12]}');db.delete(chunk);deleted+=1
        else:deferred+=1
    db.commit();return {'eligible':eligible,'deleted':deleted,'deferred':deferred}
