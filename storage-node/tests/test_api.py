import hashlib
from fastapi.testclient import TestClient

from app.main import app, settings, store


def _headers() -> dict[str, str]:
    return {'X-QuorumVault-Internal-Token': settings.internal_token}


def test_health_is_public():
    with TestClient(app) as client:
        assert client.get('/internal/health').status_code == 200


def test_chunk_operations_reject_missing_or_invalid_internal_token(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'root', tmp_path)
    data = b'secret chunk'
    chunk_hash = hashlib.sha256(data).hexdigest()
    with TestClient(app) as client:
        assert client.put(f'/internal/chunks/{chunk_hash}', content=data).status_code == 401
        assert client.put(
            f'/internal/chunks/{chunk_hash}',
            content=data,
            headers={'X-QuorumVault-Internal-Token': 'wrong'},
        ).status_code == 401


def test_valid_internal_token_allows_verified_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'root', tmp_path)
    data = b'authenticated chunk'
    chunk_hash = hashlib.sha256(data).hexdigest()
    with TestClient(app) as client:
        put = client.put(f'/internal/chunks/{chunk_hash}', content=data, headers=_headers())
        assert put.status_code == 200
        check = client.get(f'/internal/chunks/{chunk_hash}/check', headers=_headers())
        assert check.status_code == 200 and check.json()['valid'] is True
        read = client.get(f'/internal/chunks/{chunk_hash}', headers=_headers())
        assert read.status_code == 200 and read.content == data
