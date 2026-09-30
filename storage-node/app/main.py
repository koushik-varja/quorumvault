from datetime import datetime, timezone
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response as RawResponse

from .config import settings
from .storage import ChunkStore

app = FastAPI(title=f'QuorumVault Storage Node {settings.node_id}', docs_url=None, redoc_url=None)
store = ChunkStore(settings.data_dir)


def require_internal_token(
    token: str | None = Header(default=None, alias='X-QuorumVault-Internal-Token'),
) -> None:
    expected = settings.internal_token
    if not expected or token is None or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail='Invalid internal service token')


@app.get('/internal/health')
def health():
    return {
        'node_id': settings.node_id,
        'status': 'HEALTHY',
        'timestamp': datetime.now(timezone.utc),
        **store.stats(),
    }


@app.put('/internal/chunks/{chunk_hash}', dependencies=[Depends(require_internal_token)])
async def put_chunk(chunk_hash: str, request: Request):
    data = await request.body()
    try:
        return {'node_id': settings.node_id, 'chunk_hash': chunk_hash, **store.put(chunk_hash, data)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get('/internal/chunks/{chunk_hash}', dependencies=[Depends(require_internal_token)])
def get_chunk(chunk_hash: str):
    try:
        return RawResponse(
            content=store.get(chunk_hash),
            media_type='application/octet-stream',
            headers={'x-chunk-sha256': chunk_hash},
        )
    except FileNotFoundError:
        raise HTTPException(404, 'Chunk not found')
    except ValueError:
        raise HTTPException(409, 'Chunk is corrupted')


@app.get('/internal/chunks/{chunk_hash}/check', dependencies=[Depends(require_internal_token)])
def check_chunk(chunk_hash: str):
    try:
        result = store.check(chunk_hash)
        if not result['exists']:
            raise HTTPException(404, 'Chunk not found')
        return {'node_id': settings.node_id, 'chunk_hash': chunk_hash, **result}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete('/internal/chunks/{chunk_hash}', dependencies=[Depends(require_internal_token)])
def delete_chunk(chunk_hash: str):
    try:
        return {'deleted': store.delete(chunk_hash)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post('/internal/demo/corrupt/{chunk_hash}', dependencies=[Depends(require_internal_token)])
def corrupt(chunk_hash: str):
    if not settings.demo_mode:
        raise HTTPException(404, 'Demo mode disabled')
    try:
        store.corrupt(chunk_hash)
        return {'corrupted': True, 'node_id': settings.node_id, 'chunk_hash': chunk_hash}
    except FileNotFoundError:
        raise HTTPException(404, 'Chunk not found')
