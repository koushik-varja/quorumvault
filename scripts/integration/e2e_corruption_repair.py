#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import time

from qv_client import QVClient, chunk_by_index, deterministic_payload, healthy_replicas, require_docker_stack, wait_until


def main() -> None:
    client = QVClient()
    client.login()
    require_docker_stack(client)

    stamp = int(time.time())
    name = f'e2e-corruption-{stamp}.bin'
    original = deterministic_payload(5 * 1024 * 1024 + 77, f'corruption-{stamp}'.encode())
    original_sha = hashlib.sha256(original).hexdigest()
    uploaded = client.upload_bytes(name, original)
    file_id = uploaded['file_id']
    version = uploaded['version_number']
    chunk = chunk_by_index(uploaded['detail'], version)
    replicas = [r['node_id'] for r in chunk['replicas'] if r['state'] == 'HEALTHY']
    assert len(replicas) == 3, f'Expected RF=3 before corruption, got {replicas}'
    corrupt_node = replicas[0]

    client.request('POST', '/demo/corrupt', {'chunk_hash': chunk['hash'], 'node_id': corrupt_node})
    scan = client.request('POST', '/integrity/scan')
    assert scan['corrupted'] >= 1, f'Integrity scan did not report corruption: {scan}'

    detail = client.request('GET', f'/files/{file_id}')
    after = chunk_by_index(detail, version)
    state = next(r['state'] for r in after['replicas'] if r['node_id'] == corrupt_node)
    assert state == 'CORRUPTED', f'Expected corrupted replica state, got {state}'

    # This read must fall back to another real replica because the selected replica is invalid.
    downloaded_before_repair = client.download(file_id, version)
    assert downloaded_before_repair == original, 'Fallback download bytes differ from original'
    assert hashlib.sha256(downloaded_before_repair).hexdigest() == original_sha

    client.request('POST', '/repairs/scan')

    def repaired_detail():
        current = client.request('GET', f'/files/{file_id}')
        return current if len(healthy_replicas(current, version)) == 3 else None

    repaired = wait_until('corrupted replica repair and RF=3 restoration', repaired_detail, timeout=45)
    assert len(healthy_replicas(repaired, version)) == 3

    downloaded = client.download(file_id, version)
    assert downloaded == original, 'Post-repair download bytes differ from original'
    assert hashlib.sha256(downloaded).hexdigest() == original_sha
    print('PASS: real corruption -> checksum detection -> healthy fallback -> repair -> exact SHA-256')


if __name__ == '__main__':
    main()
