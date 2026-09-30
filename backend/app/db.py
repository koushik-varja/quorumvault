from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool
from .config import settings
class Base(DeclarativeBase): pass
_engine_kwargs={'pool_pre_ping':True}
if settings.database_url.startswith('sqlite'):
    _engine_kwargs.update({'connect_args':{'check_same_thread':False},'poolclass':StaticPool})
else:
    _engine_kwargs.update({'pool_size':10,'max_overflow':20})
engine=create_engine(settings.database_url,**_engine_kwargs)
SessionLocal=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()
