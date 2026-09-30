import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api.routes import router
from .auth import hash_password
from .background import heartbeat_loop, integrity_loop, repair_loop
from .config import settings
from .db import SessionLocal
from .logging_config import configure_logging, correlation_id_var
from .models import StorageNode, User, UserRole
from .services.storage_client import StorageClient

configure_logging()
log = logging.getLogger('quorumvault')


def seed_runtime_metadata() -> None:
    with SessionLocal() as db:
        for i, url in enumerate(settings.node_urls, 1):
            node_id = f'node-{i}'
            node = db.get(StorageNode, node_id)
            if not node:
                db.add(StorageNode(id=node_id, base_url=url))
            else:
                node.base_url = url
        if settings.demo_mode:
            admin = db.scalar(select(User).where(User.email == settings.demo_admin_email.lower()))
            if not admin:
                db.add(
                    User(
                        email=settings.demo_admin_email.lower(),
                        password_hash=hash_password(settings.demo_admin_password),
                        role=UserRole.ADMIN,
                    )
                )
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await StorageClient.startup()
    seed_runtime_metadata()
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(heartbeat_loop(stop)),
        asyncio.create_task(repair_loop(stop)),
        asyncio.create_task(integrity_loop(stop)),
    ]
    try:
        yield
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await StorageClient.shutdown()


app = FastAPI(title='QuorumVault Control Plane', version='1.1.0', lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.middleware('http')
async def correlation_id(request: Request, call_next):
    cid = request.headers.get('x-correlation-id') or str(uuid.uuid4())
    request.state.correlation_id = cid
    token = correlation_id_var.set(cid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers['x-correlation-id'] = cid
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info(
            'request_complete',
            extra={
                'method': request.method,
                'path': request.url.path,
                'status_code': response.status_code,
                'duration_ms': duration_ms,
            },
        )
        return response
    finally:
        correlation_id_var.reset(token)


app.include_router(router)


@app.get('/')
def root():
    return {'name': 'QuorumVault', 'docs': '/docs', 'health': '/api/health'}
