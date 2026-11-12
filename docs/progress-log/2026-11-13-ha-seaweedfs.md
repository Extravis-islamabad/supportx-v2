### 2026-11-13 — HA SeaweedFS with built-in replication (D-166, lane B)

- **Scope:** D-166 (the coordinator for Haider, 2026-11-12): the bundled SeaweedFS highly
  available in the HA profile by SeaweedFS's own replication. Chart and deploy work only, no
  migration, no new image or dependency (`chrislusf/seaweedfs:4.48`, rclone D-038).
- **Built:** `templates/seaweedfs-ha.yaml` (`objectStorage.seaweedfs.ha`, on in `values-ha.yaml`):
  3 masters (hashicorp raft, `-defaultReplication=001`, no telemetry), 3 volume servers, 2 filers
  with the S3 gateway behind the unchanged `supportx-seaweedfs:8333` Service; required
  anti-affinity, PodDisruptionBudgets, master.toml maintenance (deleteEmpty, balance,
  fix.replication every 17 minutes). Filer metadata: postgres2 store in the release's
  CloudNativePG cluster, a `Database` CR and a managed role `seaweedfs_filer` (sign-in only,
  pg_hba: its own database over TLS, refused everywhere else); password from the new
  `supportx-db-seaweedfs-filer` Secret (`secrets.sh`). Network policies for SeaweedFS's own
  flows. Single-node and dev keep the one pod (golden file unchanged).
- **Checks:** the HA preflight checks masters (3, distinct nodes), volume servers (2+ distinct
  nodes) and the replication from the master pods' arguments; the single copy under HA is a
  warning. chart-lint asserts the topology, the confined role and the refusals.
- **Tests:** `deploy/k3d/objects-node-loss.sh` (`make cluster-ha-objects-node-loss`, in the HA
  job after the database node-loss step); the restore drill checks the filers' database. Proven
  live on a throwaway 4-node k3d cluster with the chart's SeaweedFS, PostgreSQL and network
  policy manifests (no SupportX app): leader election, 001 volumes on two nodes, S3 through the
  Service, the role refused outside its database, reads back 23 s and writes 34 s after a node
  stop, fix.replication re-making and trimming copies. The full test with the app runs first in
  the Cluster workflow.
- **Docs:** deployment.md (Profiles, Secrets, Backups, CI; moving a single-copy install with
  rclone and `rclone check`), restore runbook, ADR-038 Addendum A, D-166.
- **Open:** the file-store backup (audit gap #1); the single-node `weed server` still sends
  SeaweedFS's anonymous usage statistics (default on), to fix in its own PR as it changes the
  golden file.
