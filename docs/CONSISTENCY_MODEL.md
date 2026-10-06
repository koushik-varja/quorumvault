# Consistency Model

QuorumVault does not claim a textbook distributed-consensus consistency model.

## Metadata
PostgreSQL is the single metadata authority. Per-file version allocation is serialized with transaction-scoped advisory locking in PostgreSQL and a row lock on the logical file. Database uniqueness constraints remain the final guard.

## Chunks
Chunk identity is immutable SHA-256 content addressing. Chunk metadata creation and replica metadata use idempotent/upsert behavior.

## Writes
A storage-node chunk write is accepted only when the bytes hash to the requested content key. The control plane verifies the target after writing before marking a replica healthy.

## Reads
A read is successful only when each requested chunk is obtained from a healthy/degraded candidate whose returned bytes hash to the expected chunk key. The reconstructed file is then checked against the stored whole-file SHA-256.

## Repair
Repair is safe to retry. Scheduling is serialized per chunk; a target replica is marked `REPAIRING` before network I/O. Successful copies become `HEALTHY` only after checksum verification.

## Cross-system boundary
PostgreSQL commits and remote filesystem writes are not one distributed transaction. Content addressing, idempotent writes, verification, integrity scans, and repair reduce the consequences of partial failure, but they are not equivalent to distributed transaction/consensus semantics.
