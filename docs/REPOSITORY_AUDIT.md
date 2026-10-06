# Repository Audit Before Measured-Failure Upgrade

This audit describes the code that existed on `main` before the measured-failure upgrade. It reports only behavior visible in the repository.

## 1. Current architecture
- React + TypeScript + Vite frontend.
- FastAPI control plane with SQLAlchemy metadata models.
- PostgreSQL metadata authority; Redis for short-lived cache/counters.
- Four FastAPI storage nodes backed by separate filesystem volumes.
- Docker Compose is the default local deployment boundary.
- Storage-node chunk APIs are protected by a shared internal token; health is public.

## 2. Upload flow
1. Browser chunks a file into 4 MiB pieces and calculates SHA-256 per chunk.
2. Client creates an upload session containing ordered `(index, hash, size)` descriptors.
3. Backend marks chunks already backed by the configured number of healthy replicas as received.
4. Missing chunks are uploaded individually.
5. Backend writes each chunk to distinct healthy nodes chosen from the consistent-hash ring, verifies storage-node checksums, and upserts replica metadata.
6. Finalization reconstructs the whole-file SHA-256 from verified replicas and appends an immutable numbered version.

## 3. Restore flow
- Historical version restore clones metadata/chunk references into a new monotonically increasing version.
- Snapshot restore repeats that mechanism for pinned file versions.
- Download/recovery streams ordered chunks, falls back across replicas, verifies each chunk by SHA-256, then verifies the reconstructed file hash.

## 4. Chunk placement
- Placement is content-key based.
- Healthy non-simulated nodes are ring members.
- Replica selection walks clockwise to distinct physical node IDs.
- Uploads can fall through to later ring members if a selected target write fails.

## 5. Consistent hashing
- Implemented in `backend/app/services/placement.py`.
- SHA-256 is reduced to a 64-bit ring coordinate.
- 64 virtual nodes per physical node.
- Sorted unique node IDs make placement deterministic for a fixed membership set.

## 6. Replication
- Default replication factor is 3.
- Replica metadata is unique on `(chunk_hash, node_id)`.
- Writes are verified after storage.
- Repair attempts to restore under-replicated chunks onto a healthy node that does not already hold a good copy.

## 7. Heartbeat / failure detection
- The control plane polls storage-node health.
- Last successful heartbeat is recorded with node storage/chunk counts.
- A failed poll is tolerated until `HEARTBEAT_TIMEOUT_SECONDS` is exceeded.
- Timed-out node replicas are marked unavailable.

## 8. Replica repair
- Repair selects a SHA-256 verified source, writes a target, verifies the target, then updates replica metadata and repair-job state.
- A `RepairJob` table already existed and active jobs were checked before scheduling.

## 9. Integrity checks
- Integrity scan calls storage-node checksum verification.
- Valid replicas become healthy.
- Hash mismatches become corrupted.
- Unreachable copies become unavailable.

## 10. Concurrency model
- PostgreSQL upserts protect chunk/replica identity.
- File-version allocation uses PostgreSQL transaction-scoped advisory locking and row locking.
- SQLite tests use process-level locks.
- Shared bounded `httpx.AsyncClient` pooling is used for control-plane to storage-node traffic.

## 11. Metadata storage
PostgreSQL models include users, logical files, immutable file versions, chunk references, chunks, storage nodes, replicas, upload sessions, snapshots, repair jobs, and audit events.

## 12. Error handling
- API routes return explicit 4xx/5xx responses for invalid sessions, ownership errors, hash mismatches, insufficient storage nodes, and unavailable verified replicas.
- Storage-node reads reject corrupted bytes rather than returning them.
- Cross-system filesystem + metadata writes are not one distributed transaction.

## 13. Existing tests
The repository already covered authentication/authorization, resumable-session status, dedup reuse, version allocation, restore behavior, chunk identity concurrency, heartbeat timeout, storage-node authentication, corruption detection, and basic repair. Docker E2E scripts already exercised real node failure/repair and real corruption/fallback/repair.

## 14. Visible performance bottlenecks
- Finalization reads every chunk to recompute the whole-file hash.
- Integrity and repair scans iterate metadata rows serially.
- Filesystem storage-node stats walk the storage tree.
- Browser hashing is chunk-bounded but not offloaded to Web Workers.
- Repair scheduling is interval-driven.

## 15. Race-condition risks
The concrete repair race was:
`check active repair -> select target -> create RepairJob`.
Those operations were separate database actions with no per-chunk transaction lock, so multiple control-plane workers could observe no active job simultaneously.

## 16. Possible duplicate repair work
Yes. The pre-upgrade active-job check suppressed common duplicates but was not atomic across workers. This upgrade serializes repair scheduling per chunk.

## 17. Data-loss edge cases visible in code
- If every replica of a required chunk is unavailable/corrupted, the file cannot be reconstructed.
- PostgreSQL remains a single metadata authority in the default local architecture.
- Storage-node filesystem writes and metadata commits are not a distributed transaction.
- Dynamic cluster membership/rebalancing is not automated.
- Replication is used instead of erasure coding, so durability depends on replica placement and failure overlap.
