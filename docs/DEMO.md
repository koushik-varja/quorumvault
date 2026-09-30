# QuorumVault Demo Guide

This walkthrough demonstrates real storage behavior. Use the demo ADMIN account for maintenance and fault injection.

## Start

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open `http://localhost:8080`. Compose healthchecks gate control-plane/frontend startup on PostgreSQL, Redis and the four storage nodes.

## Recommended sequence

1. Open **Cluster** and confirm four healthy nodes.
2. Upload a file from **Files**.
3. Open File Detail and inspect ordered chunk SHA-256 keys plus three replica nodes per chunk.
4. Demonstrate resumability with a sufficiently large file: begin uploading, refresh/interupt before completion, reselect the exact same file, choose **Resume previous upload**, and verify the UI reports already-uploaded vs remaining chunks. Use **Restart Upload** to discard an active session and create a fresh one.
5. Upload the same file again. When all three replicas are already healthy, the manifest should require no chunk retransfers.
6. Modify a small part of the file and upload under the same filename. Unchanged chunk hashes should be reused while changed chunks get new identities.
7. Open an older version and choose **Restore this version**. Confirm it appends a new version rather than overwriting history.
8. Create a snapshot named `Before Final Submission`.
9. Simulate a node unavailable in Demo Lab, or stop an actual container:

```powershell
docker stop quorumvault-storage-node-2
```

10. After the heartbeat timeout, observe node/replica state and run a repair scan. Under-replicated chunks should be copied from a verified source to the spare healthy node.
11. Download the file while the original node is unavailable; verified fallback replicas should reconstruct it.
12. Restore the node:

```powershell
docker start quorumvault-storage-node-2
```

13. From File Detail, take a chunk hash and one replica node ID. In Demo Lab corrupt only that replica.
14. Run **Scan integrity** and observe `CORRUPTED`. Download should still succeed using another verified replica.
15. Run **Repair scan** and inspect source, target, result and measured duration.
16. Restore the earlier snapshot; restored content appears as newly appended versions.

## Automated real-service verification

With the full Compose stack healthy, the repository includes two host-side tests that do not mock storage-node reads/writes/checks/repair copies:

```powershell
python scripts/integration/e2e_node_failure_repair.py
python scripts/integration/e2e_corruption_repair.py
```

The failure scenario stops a real storage-node container, waits for timeout detection, verifies RF=3 repair using a healthy destination, downloads, and checks exact bytes/SHA-256. The corruption scenario damages one real replica, runs checksum scrub, proves download fallback, repairs redundancy and verifies exact final bytes/SHA-256.

## Local storage-node ports

Ports 9001-9004 remain published for local demo/debug inspection. `/internal/health` is public; chunk GET/PUT/DELETE/check and corruption operations require the shared `X-QuorumVault-Internal-Token`. Do not reuse the demo token outside local development.

## Fast dedup demonstration

**Generate duplicate example** creates deterministic chunks. Run it twice: the later run should reuse existing healthy content and report deduplicated chunks.

## Verify, do not merely show

- downloaded bytes/SHA-256 match the source;
- each chunk has three distinct healthy replicas in the normal state;
- duplicate uploads do not create duplicate content rows;
- a corrupted storage-node read is never accepted;
- USER accounts cannot see system-wide audit/admin controls;
- repair history records source, target, result and measured duration.
