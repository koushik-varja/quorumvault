# Failure Model

QuorumVault is a local, student-scale distributed backup system. The failure model below is intentionally narrow and testable.

## Handled
- Loss of one storage node while sufficient replicas remain.
- Loss of multiple storage nodes when every requested chunk still has at least one reachable valid replica.
- Missing replica files.
- Corrupted replica bytes detected by SHA-256.
- Replica repair from a verified healthy source.
- Upload target failure with fallback to another healthy ring member when enough nodes remain.
- Download/restore replica failure with fallback to another verified copy.
- Retried repair requests through idempotent replica metadata and serialized per-chunk scheduling.

## Explicit degraded states
- `HEALTHY`: configured healthy replica count is satisfied.
- `DEGRADED`: at least one healthy copy exists but redundancy is below target.
- `REPAIRING`: data is recoverable and an active repair is recorded.
- `UNRECOVERABLE`: no healthy verified replica exists for at least one required chunk.

## Not handled as a guarantee
- PostgreSQL metadata database failure/high availability.
- Cross-region replication.
- Byzantine/malicious storage nodes.
- More simultaneous storage failures than actual placement can tolerate.
- Atomic commit across PostgreSQL and storage-node filesystems.
- Automated arbitrary online cluster membership/rebalancing.
- Disaster recovery for loss of both metadata and storage volumes.
