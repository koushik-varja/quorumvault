#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integration'))
from qv_client import QVClient, deterministic_payload, require_docker_stack


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return ordered[rank]


def ring_points(nodes: list[str], virtual_nodes: int = 64) -> list[tuple[int, str]]:
    points = []
    for node in sorted(set(nodes)):
        for vnode in range(virtual_nodes):
            value = int.from_bytes(hashlib.sha256(f'{node}#{vnode}'.encode()).digest()[:8], 'big')
            points.append((value, node))
    return sorted(points)


def replicas(nodes: list[str], key: str, count: int = 3) -> list[str]:
    points = ring_points(nodes)
    key_value = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big')
    idx = 0
    while idx < len(points) and points[idx][0] < key_value:
        idx += 1
    chosen = []
    for offset in range(len(points)):
        node = points[(idx + offset) % len(points)][1]
        if node not in chosen:
            chosen.append(node)
            if len(chosen) == min(count, len(nodes)):
                break
    return chosen


def remap_percentage(before: list[str], after: list[str], keys: list[str]) -> float:
    changed = sum(replicas(before, key) != replicas(after, key) for key in keys)
    return changed / len(keys) * 100.0


def run_size(client: QVClient, size_mib: int, iterations: int) -> dict:
    upload_ms: list[float] = []
    restore_ms: list[float] = []
    upload_mib_s: list[float] = []
    restore_mib_s: list[float] = []
    verified = 0
    for i in range(iterations):
        data = deterministic_payload(size_mib * 1024 * 1024, f'bench-{size_mib}-{i}'.encode())
        expected = hashlib.sha256(data).hexdigest()
        started = time.perf_counter()
        uploaded = client.upload_bytes(f'benchmark-{size_mib}m-{int(time.time())}-{i}.bin', data)
        upload_elapsed = time.perf_counter() - started
        started = time.perf_counter()
        restored = client.download(uploaded['file_id'], uploaded['version_number'])
        restore_elapsed = time.perf_counter() - started
        if hashlib.sha256(restored).hexdigest() != expected or restored != data:
            raise RuntimeError('restored bytes failed SHA-256 verification')
        verified += 1
        upload_ms.append(upload_elapsed * 1000)
        restore_ms.append(restore_elapsed * 1000)
        upload_mib_s.append(size_mib / upload_elapsed if upload_elapsed else 0)
        restore_mib_s.append(size_mib / restore_elapsed if restore_elapsed else 0)

    def stats(latencies: list[float]) -> dict:
        return {
            'p50_ms': statistics.median(latencies),
            'p95_ms': percentile(latencies, 0.95),
            'p99_ms': percentile(latencies, 0.99) if len(latencies) >= 100 else None,
        }

    return {
        'size_mib': size_mib,
        'iterations': iterations,
        'upload_latency': stats(upload_ms),
        'restore_latency': stats(restore_ms),
        'upload_throughput_mib_s_mean': statistics.mean(upload_mib_s),
        'restore_throughput_mib_s_mean': statistics.mean(restore_mib_s),
        'sha256_verified_restores': verified,
    }


def dedup_case(client: QVClient) -> dict:
    base = deterministic_payload(8 * 1024 * 1024, b'dedup-base')
    changed = base[:4 * 1024 * 1024] + deterministic_payload(4 * 1024 * 1024, b'dedup-changed')
    before = client.request('GET', '/metrics')
    first = client.upload_bytes(f'dedup-a-{int(time.time())}.bin', base)
    second = client.upload_bytes(f'dedup-b-{int(time.time())}.bin', base)
    third = client.upload_bytes(f'dedup-c-{int(time.time())}.bin', changed)
    after = client.request('GET', '/metrics')
    logical_delta = after['storage']['logical_bytes_stored'] - before['storage']['logical_bytes_stored']
    unique_delta = after['storage']['unique_chunk_bytes'] - before['storage']['unique_chunk_bytes']
    saved = max(0, logical_delta - unique_delta)
    return {
        'logical_uploaded_bytes': logical_delta,
        'unique_physical_content_bytes_added': unique_delta,
        'bytes_saved': saved,
        'dedup_percentage': round(saved / logical_delta * 100.0, 3) if logical_delta else 0.0,
        'versions': [first['version_number'], second['version_number'], third['version_number']],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--sizes-mib', default='1,4,8')
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--output', default='docs/generated/benchmark-smoke.json')
    args = parser.parse_args()
    client = QVClient()
    client.login()
    require_docker_stack(client)
    sizes = [int(item) for item in args.sizes_mib.split(',') if item.strip()]
    keys = [hashlib.sha256(f'remap-{i}'.encode()).hexdigest() for i in range(10000)]
    output = {
        'methodology': {
            'sizes_mib': sizes,
            'iterations': args.iterations,
            'p99_policy': 'reported only with at least 100 observations',
            'restore_success_definition': 'downloaded bytes exactly match original and SHA-256 matches',
        },
        'file_sizes': [run_size(client, size, args.iterations) for size in sizes],
        'deduplication': dedup_case(client),
        'consistent_hashing': {
            'join_node_remapped_percent': remap_percentage(
                ['node-1', 'node-2', 'node-3', 'node-4'],
                ['node-1', 'node-2', 'node-3', 'node-4', 'node-5'],
                keys,
            ),
            'remove_node_remapped_percent': remap_percentage(
                ['node-1', 'node-2', 'node-3', 'node-4'],
                ['node-1', 'node-2', 'node-3'],
                keys,
            ),
            'sample_keys': len(keys),
            'note': 'Membership remapping is measured against the repository consistent-hash algorithm; dynamic online membership remains a documented limitation.',
        },
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
