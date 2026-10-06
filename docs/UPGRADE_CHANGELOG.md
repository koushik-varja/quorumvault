# Measured-Failure Upgrade Changelog

## Preserved
- Application name and overall architecture.
- FastAPI control plane and storage-node services.
- PostgreSQL + Redis.
- React/Vite frontend.
- 4 MiB chunking, SHA-256 addressing, deduplication, RF=3, snapshots, restores, auth, resumable uploads, and existing E2E scripts.

## Changed
- Repair scheduling is now serialized per chunk using the existing transaction-key lock mechanism.
- Repair target reservation uses `REPAIRING` replica state before network I/O.
- Stale active repair jobs expire through a bounded repair lease.
- Added derived object/chunk health states: HEALTHY, DEGRADED, REPAIRING, UNRECOVERABLE.
- Added authenticated project metrics aggregation.
- Added a controlled replica-deletion demo action.
- Added a chaos harness that emits JSON + Markdown failure matrices.
- Added a benchmark suite for upload/restore latency, verified SHA-256 recovery, dedup savings, and consistent-hash remapping.
- Added focused frontend data-health visibility without redesigning the application.
- Added unit tests for health-state transitions, repair idempotency/duplicate suppression, and consistent-hash membership change.

## Important limitation retained
Dynamic online membership is still not automated. Join/remove remapping is measured against the repository's actual consistent-hash algorithm, and documentation labels that result as an algorithm-level membership experiment rather than a live automatic rebalance.
