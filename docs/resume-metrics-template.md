# Resume Metrics Template

Use only values copied from generated benchmark/failure reports. Do not invent numbers.

## Source files
- `docs/generated/benchmark-smoke.json`
- `docs/generated/failure-matrix.json`

## Templates

- Tested a **[NODE_COUNT]-node** local QuorumVault storage cluster under **[SCENARIO_COUNT]** automated failure scenarios, measuring **[FAILURE_DETECTION_MS] ms** failure detection and **[REPAIR_DURATION_MS] ms** repair while validating restored bytes with SHA-256.

- Implemented chunk-level SHA-256 deduplication and measured **[DEDUP_PERCENT]%** savings on a controlled duplicate/partial-overlap workload (**[LOGICAL_BYTES] logical bytes**, **[UNIQUE_BYTES] unique content bytes**).

- Measured consistent-hash membership change over **[KEY_COUNT]** deterministic keys: **[JOIN_REMAP_PERCENT]%** replica-placement remapping on node join and **[LEAVE_REMAP_PERCENT]%** on node removal.

- Benchmarked verified restore throughput at **[SIZE_MIB] MiB** with **p50 [P50] ms / p95 [P95] ms** latency and **[THROUGHPUT] MiB/s** mean throughput. Report p99 only when the benchmark output contains a non-null p99 value.
