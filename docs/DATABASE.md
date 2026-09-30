# Database Design

PostgreSQL is the source of truth for logical metadata. Physical chunk bytes live only on storage-node volumes.

```mermaid
erDiagram
  USERS ||--o{ LOGICAL_FILES : owns
  USERS ||--o{ UPLOAD_SESSIONS : starts
  USERS ||--o{ SNAPSHOTS : creates
  LOGICAL_FILES ||--o{ FILE_VERSIONS : has
  FILE_VERSIONS ||--o{ FILE_VERSION_CHUNKS : contains
  CHUNKS ||--o{ FILE_VERSION_CHUNKS : referenced_by
  CHUNKS ||--o{ CHUNK_REPLICAS : copied_as
  STORAGE_NODES ||--o{ CHUNK_REPLICAS : stores
  UPLOAD_SESSIONS ||--o{ UPLOAD_SESSION_CHUNKS : declares
  SNAPSHOTS ||--o{ SNAPSHOT_ENTRIES : contains
  LOGICAL_FILES ||--o{ SNAPSHOT_ENTRIES : captures
  FILE_VERSIONS ||--o{ SNAPSHOT_ENTRIES : pins
  CHUNKS ||--o{ REPAIR_JOBS : repaired_by

  USERS { string id PK string email UK string password_hash enum role timestamp created_at }
  LOGICAL_FILES { string id PK string owner_id FK string name string content_type }
  FILE_VERSIONS { string id PK string logical_file_id FK int version_number bigint size_bytes string file_sha256 }
  CHUNKS { string hash PK bigint size_bytes timestamp created_at }
  FILE_VERSION_CHUNKS { string id PK string file_version_id FK string chunk_hash FK int chunk_index bigint size_bytes }
  STORAGE_NODES { string id PK string base_url UK enum status timestamp last_heartbeat bigint storage_used_bytes bigint chunk_count }
  CHUNK_REPLICAS { string id PK string chunk_hash FK string node_id FK enum state timestamp checksum_verified_at }
  UPLOAD_SESSIONS { string id PK string owner_id FK string file_name bigint expected_size int chunk_size enum status }
  UPLOAD_SESSION_CHUNKS { string id PK string session_id FK int chunk_index string chunk_hash bigint size_bytes boolean received }
  SNAPSHOTS { string id PK string owner_id FK string name timestamp created_at }
  SNAPSHOT_ENTRIES { string id PK string snapshot_id FK string logical_file_id FK string file_version_id FK }
  REPAIR_JOBS { string id PK string chunk_hash FK string source_node_id string target_node_id enum state int duration_ms }
```

## Important constraints

- `users.email` is unique.
- `(owner_id, logical_files.name)` is unique, so another upload of the same logical name becomes another version.
- `(logical_file_id, version_number)` is unique.
- `(file_version_id, chunk_index)` and `(upload_session_id, chunk_index)` are unique.
- `(chunk_hash, node_id)` is unique, preventing duplicate replica metadata for the same physical node.
- Chunk hashes are indexed anywhere they are used for lookup-heavy joins.
- Replica and repair states are indexed for health/repair queries.

## Transaction boundaries

Creating an upload session and its manifest is one metadata transaction. Each accepted chunk commits chunk/replica metadata only after required writes are checksum-verified. Finalization verifies all session chunks, calculates the complete file hash from verified replicas, creates the new immutable version and marks the session finalized in one metadata transaction.

Snapshot creation records a consistent set of exact version IDs within one SQLAlchemy session transaction. Restore appends new versions and does not delete source versions.

## Migration

Alembic owns schema revision `0001`. The initial migration calls SQLAlchemy metadata creation against Alembic's bound connection; later revisions should use explicit incremental `op.*` operations to evolve existing deployments safely.
