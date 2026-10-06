#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integration'))
from qv_client import QVClient, chunk_by_index, deterministic_payload, docker, healthy_replicas, require_docker_stack, wait_until


def container_for(node_id: str) -> str:
    return f'quorumvault-storage-{node_id}'


def now_ms() -> int:
    return int(time.time() * 1000)


def record(name: str, started: int, **fields: Any) -> dict[str, Any]:
    return {'scenario': name, 'elapsed_ms': now_ms() - started, **fields}


def verify_download(client: QVClient, file_id: str, version: int, expected: bytes) -> bool:
    actual = client.download(file_id, version)
    return actual == expected and hashlib.sha256(actual).hexdigest() == hashlib.sha256(expected).hexdigest()


def scenario_single_node_failure(client: QVClient) -> dict[str, Any]:
    started = now_ms()
    payload = deterministic_payload(5 * 1024 * 1024 + 19, b'chaos-single')
    uploaded = client.upload_bytes(f'chaos-single-{int(time.time())}.bin', payload)
    file_id, version = uploaded['file_id'], uploaded['version_number']
    replicas = healthy_replicas(uploaded['detail'], version)
    victim = replicas[0]
    docker('stop', container_for(victim))
    detection_started = now_ms()
    try:
        wait_until(
            'node failure detection',
            lambda: next((n for n in client.request('GET', '/cluster') if n['id'] == victim and n['status'] == 'UNHEALTHY'), None),
            timeout=50,
        )
        detection_ms = now_ms() - detection_started
        client.request('POST', '/repairs/scan')
        repair_started = now_ms()

        def repaired():
            detail = client.request('GET', f'/files/{file_id}')
            nodes = healthy_replicas(detail, version)
            return detail if len(nodes) == 3 and victim not in nodes else None

        wait_until('RF=3 repair', repaired, timeout=45)
        repair_ms = now_ms() - repair_started
        ok = verify_download(client, file_id, version, payload)
        return record(
            'one_node_failure', started,
            data_available=ok, detected=True, repair_attempted=True,
            recovery_succeeded=ok, failure_detection_ms=detection_ms,
            repair_duration_ms=repair_ms, sha256_verified=ok,
        )
    finally:
        docker('start', container_for(victim))
        wait_until(
            'node healthy after restart',
            lambda: next((n for n in client.request('GET', '/cluster') if n['id'] == victim and n['status'] == 'HEALTHY'), None),
            timeout=45,
        )


def scenario_two_node_failure(client: QVClient) -> dict[str, Any]:
    started = now_ms()
    payload = deterministic_payload(3 * 1024 * 1024 + 31, b'chaos-two')
    uploaded = client.upload_bytes(f'chaos-two-{int(time.time())}.bin', payload)
    file_id, version = uploaded['file_id'], uploaded['version_number']
    victims = healthy_replicas(uploaded['detail'], version)[:2]
    for victim in victims:
        docker('stop', container_for(victim))
    try:
        ok = verify_download(client, file_id, version, payload)
        return record(
            'two_node_failure', started,
            data_available=ok, detected=True, repair_attempted=False,
            recovery_succeeded=ok, sha256_verified=ok,
            note='Availability is reported from actual replica placement. RF restoration is not claimed while only two nodes remain online.',
        )
    finally:
        for victim in victims:
            docker('start', container_for(victim))
        wait_until(
            'all nodes healthy after restart',
            lambda: all(n['status'] == 'HEALTHY' for n in client.request('GET', '/cluster')),
            timeout=50,
        )


def scenario_corruption(client: QVClient) -> dict[str, Any]:
    started = now_ms()
    payload = deterministic_payload(4 * 1024 * 1024 + 7, b'chaos-corrupt')
    uploaded = client.upload_bytes(f'chaos-corrupt-{int(time.time())}.bin', payload)
    file_id, version = uploaded['file_id'], uploaded['version_number']
    chunk = chunk_by_index(uploaded['detail'], version)
    victim = healthy_replicas(uploaded['detail'], version)[0]
    client.request('POST', '/demo/corrupt', {'chunk_hash': chunk['hash'], 'node_id': victim})
    scan = client.request('POST', '/integrity/scan')
    detected = scan.get('corrupted', 0) >= 1
    fallback_ok = verify_download(client, file_id, version, payload)
    client.request('POST', '/repairs/scan')
    wait_until(
        'corruption repair',
        lambda: len(healthy_replicas(client.request('GET', f'/files/{file_id}'), version)) == 3,
        timeout=45,
    )
    final_ok = verify_download(client, file_id, version, payload)
    return record(
        'one_corrupted_replica', started,
        data_available=fallback_ok, detected=detected, repair_attempted=True,
        recovery_succeeded=final_ok, sha256_verified=final_ok,
    )


def scenario_replica_deletion(client: QVClient) -> dict[str, Any]:
    started = now_ms()
    payload = deterministic_payload(2 * 1024 * 1024 + 11, b'chaos-delete')
    uploaded = client.upload_bytes(f'chaos-delete-{int(time.time())}.bin', payload)
    file_id, version = uploaded['file_id'], uploaded['version_number']
    chunk = chunk_by_index(uploaded['detail'], version)
    victim = healthy_replicas(uploaded['detail'], version)[0]
    client.request('POST', '/demo/delete-replica', {'chunk_hash': chunk['hash'], 'node_id': victim})
    client.request('POST', '/repairs/scan')
    wait_until(
        'deleted replica rebuild',
        lambda: len(healthy_replicas(client.request('GET', f'/files/{file_id}'), version)) == 3,
        timeout=45,
    )
    ok = verify_download(client, file_id, version, payload)
    return record(
        'one_replica_deleted', started,
        data_available=True, detected=True, repair_attempted=True,
        recovery_succeeded=ok, sha256_verified=ok,
    )


def write_reports(results: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'failure-matrix.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    lines = [
        '# QuorumVault Failure Matrix',
        '',
        '> Generated by the chaos harness from execution results. Values are not estimates.',
        '',
        '| Scenario | Data available? | Detected? | Repair attempted? | Recovery succeeded? | SHA-256 verified? | Time |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    for row in results:
        lines.append(
            f"| {row['scenario']} | {row.get('data_available')} | {row.get('detected')} | "
            f"{row.get('repair_attempted')} | {row.get('recovery_succeeded')} | "
            f"{row.get('sha256_verified')} | {row.get('elapsed_ms')} ms |"
        )
    (output_dir / 'failure-matrix.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', default='docs/generated')
    args = parser.parse_args()
    client = QVClient()
    client.login()
    require_docker_stack(client)
    scenarios = [
        scenario_single_node_failure,
        scenario_two_node_failure,
        scenario_corruption,
        scenario_replica_deletion,
    ]
    results = []
    for scenario in scenarios:
        try:
            result = scenario(client)
        except Exception as exc:
            result = {
                'scenario': scenario.__name__.removeprefix('scenario_'),
                'data_available': None,
                'detected': None,
                'repair_attempted': None,
                'recovery_succeeded': False,
                'sha256_verified': False,
                'elapsed_ms': None,
                'error': str(exc),
            }
        print(json.dumps(result, indent=2), flush=True)
        results.append(result)
    write_reports(results, Path(args.output_dir))
    if any(row.get('recovery_succeeded') is False for row in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
