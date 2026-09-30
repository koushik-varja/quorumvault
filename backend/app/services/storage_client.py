from __future__ import annotations

import asyncio
import httpx

from ..config import settings
from .hashing import sha256_bytes


class StorageClient:
    """Shared async client for all control-plane -> storage-node traffic.

    Instances are lightweight facades over one process-wide AsyncClient so replica
    operations reuse keep-alive connections instead of opening a TCP connection per call.
    """

    _client: httpx.AsyncClient | None = None
    _startup_lock = asyncio.Lock()

    def __init__(self, timeout: float | None = None):
        self.timeout_override = timeout

    @classmethod
    async def startup(cls) -> None:
        async with cls._startup_lock:
            if cls._client is not None and not cls._client.is_closed:
                return
            timeout = httpx.Timeout(
                connect=settings.storage_connect_timeout_seconds,
                read=settings.storage_read_timeout_seconds,
                write=settings.storage_write_timeout_seconds,
                pool=settings.storage_pool_timeout_seconds,
            )
            limits = httpx.Limits(
                max_connections=settings.storage_max_connections,
                max_keepalive_connections=settings.storage_max_keepalive_connections,
                keepalive_expiry=30.0,
            )
            cls._client = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                headers={'X-QuorumVault-Internal-Token': settings.internal_token},
            )

    @classmethod
    async def shutdown(cls) -> None:
        async with cls._startup_lock:
            if cls._client is not None:
                await cls._client.aclose()
                cls._client = None

    async def _http(self) -> httpx.AsyncClient:
        if self.__class__._client is None or self.__class__._client.is_closed:
            await self.__class__.startup()
        assert self.__class__._client is not None
        return self.__class__._client

    def _timeout(self) -> float | None:
        return self.timeout_override

    async def health(self, base_url: str) -> dict:
        client = await self._http()
        r = await client.get(f'{base_url}/internal/health', timeout=self._timeout())
        r.raise_for_status()
        return r.json()

    async def put(self, base_url: str, chunk_hash: str, data: bytes) -> dict:
        client = await self._http()
        r = await client.put(
            f'{base_url}/internal/chunks/{chunk_hash}',
            content=data,
            headers={'content-type': 'application/octet-stream'},
            timeout=self._timeout(),
        )
        r.raise_for_status()
        return r.json()

    async def get(self, base_url: str, chunk_hash: str) -> bytes:
        client = await self._http()
        r = await client.get(f'{base_url}/internal/chunks/{chunk_hash}', timeout=self._timeout())
        r.raise_for_status()
        data = r.content
        if sha256_bytes(data) != chunk_hash:
            raise ValueError('checksum mismatch from storage node')
        return data

    async def check(self, base_url: str, chunk_hash: str) -> dict:
        client = await self._http()
        r = await client.get(f'{base_url}/internal/chunks/{chunk_hash}/check', timeout=self._timeout())
        if r.status_code == 404:
            return {'exists': False, 'valid': False}
        r.raise_for_status()
        return r.json()

    async def delete(self, base_url: str, chunk_hash: str) -> None:
        client = await self._http()
        r = await client.delete(f'{base_url}/internal/chunks/{chunk_hash}', timeout=self._timeout())
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    async def corrupt(self, base_url: str, chunk_hash: str) -> dict:
        client = await self._http()
        r = await client.post(f'{base_url}/internal/demo/corrupt/{chunk_hash}', timeout=self._timeout())
        r.raise_for_status()
        return r.json()
