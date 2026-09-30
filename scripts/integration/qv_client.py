from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_API = os.getenv('QV_API_URL', 'http://localhost:8000/api').rstrip('/')
DEFAULT_EMAIL = os.getenv('QV_ADMIN_EMAIL', 'admin@quorumvault.local')
DEFAULT_PASSWORD = os.getenv('QV_ADMIN_PASSWORD', 'QuorumVaultDemo!23')
CHUNK_SIZE = 4 * 1024 * 1024


class ApiError(RuntimeError):
    pass


@dataclass
class QVClient:
    base_url: str = DEFAULT_API
    token: str | None = None

    def request(self, method: str, path: str, payload: Any = None, *, raw: bytes | None = None, timeout: int = 30) -> Any:
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        data: bytes | None = None
        if raw is not None:
            data = raw
            headers['Content-Type'] = 'application/octet-stream'
        elif payload is not None:
            data = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(f'{self.base_url}{path}', data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
                content_type = response.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    return json.loads(body.decode('utf-8'))
                return body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            raise ApiError(f'{method} {path} -> HTTP {exc.code}: {body}') from exc
        except urllib.error.URLError as exc:
            raise ApiError(f'{method} {path} failed: {exc}') from exc

    def login(self, email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD) -> None:
        result = self.request('POST', '/auth/login', {'email': email, 'password': password})
        self.token = result['access_token']

    def upload_bytes(self, name: str, data: bytes, content_type: str = 'application/octet-stream') -> dict[str, Any]:
        chunks = [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)] or [b'']
        manifest = [
            {'index': index, 'hash': hashlib.sha256(chunk).hexdigest(), 'size': len(chunk)}
            for index, chunk in enumerate(chunks)
        ]
        session = self.request(
            'POST',
            '/uploads/sessions',
            {
                'file_name': name,
                'expected_size': len(data),
                'content_type': content_type,
                'chunks': manifest,
            },
        )
        missing = set(session['missing_chunks'])
        for index, chunk in enumerate(chunks):
            if index in missing:
                self.request('PUT', f"/uploads/sessions/{session['session_id']}/chunks/{index}", raw=chunk, timeout=60)
        finalized = self.request('POST', f"/uploads/sessions/{session['session_id']}/finalize")
        rows = self.request('GET', '/files')
        matches = [row for row in rows if row['name'] == name]
        if not matches:
            raise AssertionError('Uploaded logical file not visible through /files')
        logical = matches[0]
        detail = self.request('GET', f"/files/{logical['id']}")
        finalized['file_id'] = logical['id']
        finalized['detail'] = detail
        finalized['manifest'] = manifest
        return finalized

    def download(self, file_id: str, version: int) -> bytes:
        result = self.request('GET', f'/files/{file_id}/versions/{version}/download', timeout=60)
        if not isinstance(result, (bytes, bytearray)):
            raise AssertionError('Download did not return raw bytes')
        return bytes(result)


def docker(*args: str) -> None:
    command = ['docker', *args]
    print('$', ' '.join(command), flush=True)
    subprocess.run(command, check=True)


def require_docker_stack(client: QVClient) -> None:
    try:
        docker('version')
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit('Docker is required. Start Docker Desktop and `docker compose up --build` first.') from exc
    health = client.request('GET', '/health')
    if health.get('status') != 'ok':
        raise SystemExit('QuorumVault control plane is not healthy.')
    nodes = client.request('GET', '/cluster')
    if len(nodes) != 4 or any(node['status'] != 'HEALTHY' for node in nodes):
        raise SystemExit(f'Expected four healthy storage nodes before E2E test; got {nodes}')


def wait_until(description: str, predicate, timeout: float = 60.0, interval: float = 2.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:  # keep diagnostic for timeout while services transition
            last = exc
        time.sleep(interval)
    raise AssertionError(f'Timed out waiting for {description}. Last observation: {last!r}')


def healthy_replicas(detail: dict[str, Any], version: int, chunk_index: int = 0) -> list[str]:
    selected = next(v for v in detail['versions'] if v['version_number'] == version)
    chunk = next(c for c in selected['chunks'] if c['index'] == chunk_index)
    return [r['node_id'] for r in chunk['replicas'] if r['state'] == 'HEALTHY']


def chunk_by_index(detail: dict[str, Any], version: int, chunk_index: int = 0) -> dict[str, Any]:
    selected = next(v for v in detail['versions'] if v['version_number'] == version)
    return next(c for c in selected['chunks'] if c['index'] == chunk_index)


def deterministic_payload(size: int, seed: bytes) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < size:
        out.extend(hashlib.sha256(seed + counter.to_bytes(8, 'big')).digest())
        counter += 1
    return bytes(out[:size])
