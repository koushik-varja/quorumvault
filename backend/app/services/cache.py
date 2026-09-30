import json
from ..config import settings
try: from redis import Redis
except Exception: Redis=None
class Cache:
    def __init__(self): self.redis=Redis.from_url(settings.redis_url,decode_responses=True,socket_connect_timeout=1,socket_timeout=1) if Redis else None
    def get_json(self,key:str):
        if not self.redis:return None
        try:
            raw=self.redis.get(key);return json.loads(raw) if raw else None
        except Exception:return None
    def set_json(self,key:str,value,ttl:int=2):
        if not self.redis:return
        try:self.redis.setex(key,ttl,json.dumps(value,default=str))
        except Exception:pass
    def delete(self,key:str):
        if not self.redis:return
        try:self.redis.delete(key)
        except Exception:pass
cache=Cache()
