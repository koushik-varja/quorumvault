#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from typing import Any

import httpx

CHUNK = 4 * 1024 * 1024


def make_bytes(size: int, seed: int) -> bytes:
    block = hashlib.sha256(f'quorumvault-{seed}'.encode()).digest() * 4096
    return (block * ((size // len(block)) + 1))[:size]


async def login(client: httpx.AsyncClient, base: str, email: str, password: str) -> str:
    response = await client.post(f'{base}/auth/login', json={'email': email, 'password': password})
    response.raise_for_status()
    return response.json()['access_token']


async def upload(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    name: str,
    data: bytes,
) -> tuple[dict[str, Any], float, int, int]:
    chunks: list[tuple[int, bytes, str]] = []
    for index, offset in enumerate(range(0, len(data), CHUNK)):
        blob = data[offset:offset + CHUNK]
        chunks.append((index, blob, hashlib.sha256(blob).hexdigest()))
    if not chunks:
        chunks = [(0, b'', hashlib.sha256(b'').hexdigest())]
    manifest = [{'index': i, 'hash': h, 'size': len(blob)} for i, blob, h in chunks]

    started = time.perf_counter()
    response = await client.post(
        f'{base}/uploads/sessions',
        headers=headers,
        json={
            'file_name': name,
            'expected_size': len(data),
            'content_type': 'application/octet-stream',
            'chunks': manifest,
        },
    )
    response.raise_for_status()
    session = response.json()
    for index in session['missing_chunks']:
        _, blob, _ = chunks[index]
        sent = await client.put(
            f"{base}/uploads/sessions/{session['session_id']}/chunks/{index}",
            headers={**headers, 'content-type': 'application/octet-stream'},
            content=blob,
        )
        sent.raise_for_status()
    finalized = await client.post(f"{base}/uploads/sessions/{session['session_id']}/finalize", headers=headers)
    finalized.raise_for_status()
    elapsed = time.perf_counter() - started
    return finalized.json(), elapsed, len(session['missing_chunks']), len(chunks)


async def verified_download(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    expected_sha: str,
) -> bytes:
    response = await client.get(url, headers=headers)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != expected_sha:
        raise RuntimeError('download checksum mismatch')
    return response.content


async def main(args: argparse.Namespace) -> None:
    limits = httpx.Limits(max_connections=max(16, args.concurrency * 4), max_keepalive_connections=max(8, args.concurrency * 2))
    async with httpx.AsyncClient(timeout=120, limits=limits) as client:
        token = await login(client, args.base_url, args.email, args.password)
        headers = {'Authorization': f'Bearer {token}'}
        data = make_bytes(args.size_mib * 1024 * 1024, 1)
        expected = hashlib.sha256(data).hexdigest()

        result, upload_seconds, missing, total = await upload(
            client, args.base_url, headers, 'benchmark.bin', data
        )
        files_response = await client.get(f'{args.base_url}/files', headers=headers)
        files_response.raise_for_status()
        file_id = next(item['id'] for item in files_response.json() if item['name'] == 'benchmark.bin')
        version = result['version_number']
        download_url = f'{args.base_url}/files/{file_id}/versions/{version}/download'

        started = time.perf_counter()
        await verified_download(client, download_url, headers, expected)
        download_seconds = time.perf_counter() - started

        latencies_ms: list[float] = []
        for _ in range(20):
            started = time.perf_counter()
            response = await client.get(f'{args.base_url}/dashboard', headers=headers)
            response.raise_for_status()
            latencies_ms.append((time.perf_counter() - started) * 1000)

        async def upload_worker(index: int):
            return await upload(
                client,
                args.base_url,
                headers,
                f'benchmark-concurrent-{index}.bin',
                make_bytes(len(data), index + 10),
            )

        started = time.perf_counter()
        await asyncio.gather(*(upload_worker(i) for i in range(args.concurrency)))
        concurrent_upload_seconds = time.perf_counter() - started

        started = time.perf_counter()
        concurrent_downloads = await asyncio.gather(
            *(verified_download(client, download_url, headers, expected) for _ in range(args.concurrency))
        )
        concurrent_download_seconds = time.perf_counter() - started
        concurrent_download_bytes = sum(len(blob) for blob in concurrent_downloads)

        dashboard_response = await client.get(f'{args.base_url}/dashboard', headers=headers)
        dashboard_response.raise_for_status()
        dashboard = dashboard_response.json()

        # Repair duration is produced by real repair jobs. Benchmarking reads it; it does not invent one.
        integrity_response = await client.get(f'{args.base_url}/integrity', headers=headers)
        integrity_response.raise_for_status()
        repair_durations = [
            job['duration_ms']
            for job in integrity_response.json().get('repairs', [])
            if job.get('state') == 'SUCCEEDED' and job.get('duration_ms') is not None
        ]

        output = {
            'environment_note': 'Record host/Docker resources and exact commit separately',
            'file_size_bytes': len(data),
            'concurrency': args.concurrency,
            'upload_seconds': upload_seconds,
            'upload_mib_s': (len(data) / 1024 / 1024) / upload_seconds if upload_seconds else None,
            'download_seconds': download_seconds,
            'download_mib_s': (len(data) / 1024 / 1024) / download_seconds if download_seconds else None,
            'api_latency_ms_median': statistics.median(latencies_ms),
            'api_latency_ms_p95': sorted(latencies_ms)[int(len(latencies_ms) * 0.95) - 1],
            'initial_missing_chunks': missing,
            'total_chunks': total,
            'concurrent_upload_seconds': concurrent_upload_seconds,
            'aggregate_concurrent_upload_mib_s': (
                (len(data) * args.concurrency / 1024 / 1024) / concurrent_upload_seconds
                if concurrent_upload_seconds else None
            ),
            'concurrent_download_seconds': concurrent_download_seconds,
            'aggregate_concurrent_download_mib_s': (
                (concurrent_download_bytes / 1024 / 1024) / concurrent_download_seconds
                if concurrent_download_seconds else None
            ),
            'latest_measured_repair_duration_ms': repair_durations[0] if repair_durations else None,
            'dashboard_storage': {
                key: dashboard[key]
                for key in ('logical_storage_bytes', 'unique_chunk_bytes', 'dedup_savings_bytes')
            },
        }
        print(json.dumps(output, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:8000/api')
    parser.add_argument('--email', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--size-mib', type=int, default=64)
    parser.add_argument('--concurrency', type=int, default=4)
    asyncio.run(main(parser.parse_args()))
