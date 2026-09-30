# Benchmarking Methodology

QuorumVault includes a benchmark harness but commits **no invented performance numbers**. Record results only after running them on the target machine.

## Environment record

Before publishing any result, record:

- CPU model and core count
- RAM
- operating system
- Docker Desktop version/resources
- Python/Node versions where relevant
- file size and chunk size
- concurrency level
- whether storage volumes are on SSD/HDD
- exact commit tested

## Harness

From a host with the stack running:

```powershell
python scripts/benchmark/benchmark.py --base-url http://localhost:8000/api --email admin@quorumvault.local --password "QuorumVaultDemo!23" --size-mib 64 --concurrency 4
```

The script generates deterministic bytes locally, runs the upload-session protocol, downloads and verifies SHA-256, measures API latency, then executes both concurrent uploads and concurrent verified downloads at the requested worker count. Output is JSON so results can be archived without hand-editing.

## Metrics

- **Upload throughput:** source bytes / elapsed finalize workflow time.
- **Download throughput:** verified bytes / response elapsed time.
- **API latency:** repeated authenticated dashboard request latency; report median and p95.
- **Concurrent uploads/downloads:** aggregate throughput at the requested worker count.
- **Repair time:** the harness reads the latest successful measured `duration_ms` from repair history when one exists; it reports `null` rather than inventing a value when no repair has been measured.
- **Deduplication savings:** compare logical latest-version bytes with unique referenced chunk bytes from the Dashboard API.
- **Large-file memory behavior:** observe Docker Desktop/container memory while increasing generated file size; the storage path is chunked/streamed, while browser SHA-256 currently buffers one chunk at a time.

## Interpreting results

Do not compare results from different hardware without context. Docker Desktop filesystem performance can differ significantly from native Linux. The project favors correctness and inspectability over claiming maximum throughput.
