#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from app.services.placement import ConsistentHashRing  # noqa: E402


def measure(keys: list[str], before_nodes: list[str], after_nodes: list[str], replicas: int) -> dict:
    before = ConsistentHashRing(before_nodes)
    after = ConsistentHashRing(after_nodes)
    primary_changed = 0
    replica_set_changed = 0
    for key in keys:
        before_replicas = before.replicas(key, replicas)
        after_replicas = after.replicas(key, replicas)
        primary_changed += before_replicas[:1] != after_replicas[:1]
        replica_set_changed += set(before_replicas) != set(after_replicas)
    count = len(keys)
    return {
        'keys': count,
        'before_nodes': before_nodes,
        'after_nodes': after_nodes,
        'replication_factor': replicas,
        'primary_remapped_count': primary_changed,
        'primary_remapped_percentage': round(primary_changed / count * 100.0, 3),
        'replica_set_changed_count': replica_set_changed,
        'replica_set_changed_percentage': round(replica_set_changed / count * 100.0, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--keys', type=int, default=10000)
    parser.add_argument('--replicas', type=int, default=3)
    parser.add_argument('--output')
    args = parser.parse_args()
    keys = [hashlib.sha256(f'quorumvault-key-{index}'.encode()).hexdigest() for index in range(args.keys)]
    baseline = ['node-1', 'node-2', 'node-3', 'node-4']
    result = {
        'methodology': 'deterministic in-process measurement of the repository ConsistentHashRing implementation',
        'live_membership_rebalancing': False,
        'node_join': measure(keys, baseline, baseline + ['node-5'], args.replicas),
        'node_leave': measure(keys, baseline, baseline[:-1], min(args.replicas, 3)),
    }
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
