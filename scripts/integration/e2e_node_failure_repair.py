#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import time

from qv_client import QVClient, deterministic_payload, docker, healthy_replicas, require_docker_stack, wait_until


def main() -> None:
    client = QVClient()
    client.login()
    require_docker_stack(client)

    stamp = int(time.time())
    name = f'e2e-node-failure-{stamp}.bin'
    original = deterministic_payload(6 * 1024 * 1024 + 123, f'node-failure-{stamp}'.encode())
    original_sha = hashlib.sha256(original).hexdigest()
    uploaded = client.upload_bytes(name, original)
    file_id = uploaded['file_id']
    version = uploaded['version_number']

    replicas = healthy_replicas(uploaded['detail'], version)
    assert len(replicas) == 3, f'Expected RF=3 before failure, got {replicas}'
    failed_node = replicas[0]
    container = f'quorumvault-storage-{failed_node}'
    print(f'Uploaded {name}; chunk 0 replicas: {replicas}; stopping {container}')

    docker('stop', container)
    try:
        wait_until(
            f'{failed_node} heartbeat timeout',
            lambda: next((n for n in client.request('GET', '/cluster') if n['id'] == failed_node and n['status'] == 'UNHEALTHY'), None),
            timeout=50,
        )

        # The background repair loop may repair before this explicit scan. Either path is valid;
        # the assertion below verifies the resulting real distributed state.
        client.request('POST', '/repairs/scan')

        def repaired_detail():
            detail = client.request('GET', f'/files/{file_id}')
            nodes = healthy_replicas(detail, version)
            return detail if len(nodes) >= 3 and failed_node not in nodes else None

        detail = wait_until('replication factor restored on healthy nodes', repaired_detail, timeout=45)
        repaired_nodes = healthy_replicas(detail, version)
        assert len(repaired_nodes) == 3, f'Expected exactly three healthy replicas after repair, got {repaired_nodes}'

        downloaded = client.download(file_id, version)
        assert downloaded == original, 'Downloaded bytes differ from original after node failure/repair'
        assert hashlib.sha256(downloaded).hexdigest() == original_sha, 'Downloaded SHA-256 differs from original'
        print('PASS: real node failure -> heartbeat detection -> repair -> exact download SHA-256')
    finally:
        docker('start', container)
        wait_until(
            f'{failed_node} to become healthy after restart',
            lambda: next((n for n in client.request('GET', '/cluster') if n['id'] == failed_node and n['status'] == 'HEALTHY'), None),
            timeout=45,
        )


if __name__ == '__main__':
    main()
