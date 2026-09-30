from ..config import settings
try:
    from redis import Redis
except Exception:  # allows pure unit tests without Redis client installed
    Redis = None
class Metrics:
    def __init__(self):
        self.redis = Redis.from_url(settings.redis_url,decode_responses=True,socket_connect_timeout=1,socket_timeout=1) if Redis else None
    def incr(self,name:str,amount:int=1):
        if not self.redis:return
        try:self.redis.hincrby('qv:metrics',name,amount)
        except Exception:pass
    def set(self,name:str,value:int|float):
        if not self.redis:return
        try:self.redis.hset('qv:metrics',name,value)
        except Exception:pass
    def snapshot(self)->dict[str,str]:
        if not self.redis:return {}
        try:return self.redis.hgetall('qv:metrics')
        except Exception:return {}
metrics=Metrics()
