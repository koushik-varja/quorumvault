# API Guide

Interactive OpenAPI is available at `http://localhost:8000/docs`. All application endpoints use `/api`; authenticated routes accept `Authorization: Bearer <JWT>`.

## Authentication and roles

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/api/auth/register` | Public | Create USER account |
| POST | `/api/auth/login` | Public | Obtain JWT |
| GET | `/api/me` | Authenticated | Current identity and role |

USER accounts can access only their files, upload sessions and snapshots. Dashboard recent activity is filtered to the current actor. System-wide audit data and cluster-wide maintenance actions require ADMIN.

## Upload session protocol

`POST /api/uploads/sessions` accepts filename, expected size, content type and an ordered chunk manifest such as:

```json
{"index": 0, "hash": "<64 hex chars>", "size": 4194304}
```

The response contains `missing_chunks`. Send only those indexes with `PUT /api/uploads/sessions/{session_id}/chunks/{index}` using `application/octet-stream`. `GET /api/uploads/sessions/{session_id}` returns status plus received/missing indexes so an interrupted browser upload can resume. `DELETE /api/uploads/sessions/{session_id}` aborts an active session for Restart Upload. Finish with `POST /api/uploads/sessions/{session_id}/finalize`.

The browser persists only session/fingerprint metadata in local storage; file bytes are never stored there. Reselecting the same file lets the UI verify the backend session and offer **Resume previous upload**.

## Files and versions

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/files` | Current user's logical files/latest version |
| GET | `/api/files/{id}` | Versions, ordered chunks and replica states |
| GET | `/api/files/{id}/versions/{n}/download` | Checksum-verified reconstruction |
| POST | `/api/files/{id}/versions/{n}/restore` | Clone historical version as a new latest version |

Historical restore never rewrites or deletes old versions. If current is v5 and v2 is restored, a new v6 is created with v2's ordered chunk references and an audit event is recorded.

## Snapshots

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/snapshots` | List current user's snapshots |
| POST | `/api/snapshots` | Capture exact latest version IDs |
| POST | `/api/snapshots/{id}/restore` | Append restored versions |

## Cluster, integrity and repair

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/cluster` | Authenticated | Read-only node health and physical usage |
| GET | `/api/placement/{chunk_hash}` | Authenticated | Intended ring placement vs actual replicas |
| GET | `/api/integrity` | ADMIN | Replica-state counts and repair history |
| POST | `/api/integrity/scan` | ADMIN | Run checksum scrub |
| POST | `/api/repairs/scan` | ADMIN | Run under-replication repair scan |
| POST | `/api/gc/scan` | ADMIN | Run reference-safe physical GC |
| GET | `/api/audit` | ADMIN | System-wide audit events |

## Demo-mode admin routes

These require ADMIN and exist only when `DEMO_MODE=true`:

- `POST /api/demo/node/unavailable`
- `POST /api/demo/node/restore`
- `POST /api/demo/corrupt`
- `POST /api/demo/generate-duplicate`

The application never mounts the Docker socket.

## Storage-node internal API

Storage-node chunk operations are not public application APIs. The control plane sends `X-QuorumVault-Internal-Token`, configured by `QUORUMVAULT_INTERNAL_TOKEN`. Missing/incorrect tokens receive HTTP 401. Protected operations include chunk PUT/GET/DELETE, checksum check, and demo corruption. `/internal/health` remains unauthenticated so Compose/control-plane health checks can function.
