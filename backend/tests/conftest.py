import os
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:///:memory:')
os.environ.setdefault('REDIS_URL','redis://localhost:6379/15')
os.environ.setdefault('JWT_SECRET','test-secret-not-for-production-0123456789')
os.environ.setdefault('STORAGE_NODE_URLS','')
os.environ.setdefault('DEMO_MODE','false')
