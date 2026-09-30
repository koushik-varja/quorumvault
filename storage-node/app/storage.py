from __future__ import annotations
import hashlib
import os
import re
from pathlib import Path

HEX64=re.compile(r'^[0-9a-f]{64}$')

class ChunkStore:
    def __init__(self,data_dir:str):
        self.root=Path(data_dir); self.root.mkdir(parents=True,exist_ok=True)
    def _validate(self,h:str)->str:
        h=h.lower()
        if not HEX64.fullmatch(h): raise ValueError('invalid SHA-256 key')
        return h
    def path(self,h:str)->Path:
        h=self._validate(h); folder=self.root/h[:2]/h[2:4]; folder.mkdir(parents=True,exist_ok=True); return folder/h
    @staticmethod
    def digest(data:bytes)->str: return hashlib.sha256(data).hexdigest()
    def put(self,h:str,data:bytes)->dict:
        h=self._validate(h)
        if self.digest(data)!=h: raise ValueError('content checksum does not match key')
        target=self.path(h)
        if target.exists():
            valid=self.check(h)
            if valid['valid']: return {'stored':False,'deduplicated':True,'size_bytes':target.stat().st_size}
        tmp=target.with_suffix('.tmp')
        with open(tmp,'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,target)
        check=self.check(h)
        if not check['valid']:
            target.unlink(missing_ok=True); raise IOError('post-write checksum verification failed')
        return {'stored':True,'deduplicated':False,'size_bytes':len(data)}
    def get(self,h:str)->bytes:
        p=self.path(h)
        if not p.exists(): raise FileNotFoundError(h)
        data=p.read_bytes()
        if self.digest(data)!=h: raise ValueError('stored chunk checksum mismatch')
        return data
    def check(self,h:str)->dict:
        p=self.path(h)
        if not p.exists(): return {'exists':False,'valid':False,'size_bytes':0}
        data=p.read_bytes(); actual=self.digest(data)
        return {'exists':True,'valid':actual==h,'size_bytes':len(data),'actual_sha256':actual}
    def delete(self,h:str)->bool:
        p=self.path(h)
        if not p.exists(): return False
        p.unlink(); return True
    def corrupt(self,h:str)->None:
        p=self.path(h)
        if not p.exists(): raise FileNotFoundError(h)
        data=bytearray(p.read_bytes())
        if data: data[0]^=0xFF
        else: data.extend(b'corrupt')
        p.write_bytes(bytes(data))
    def stats(self)->dict:
        count=total=0
        for p in self.root.rglob('*'):
            if p.is_file() and not p.name.endswith('.tmp'):
                count+=1; total+=p.stat().st_size
        return {'chunk_count':count,'storage_used_bytes':total}
