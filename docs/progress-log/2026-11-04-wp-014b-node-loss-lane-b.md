### 2026-11-04 — WP-014b: the node-loss test (lane B, #193)

- **Test:** `deploy/k3d/node-loss.sh` (`make cluster-ha-node-loss`), a step in Cluster › "k3d HA smoke":
  1. sign in through the BFF and save a preference;
  2. stop the k3d agent holding PostgreSQL's primary;
  3. wait for a standby to be promoted;
  4. the same session writes again;
  5. the node starts again, and three database instances are ready.

  Plan decision 1b: standard runners. Green on run 41775062603: promoted after 68 s, writing again 28 s later, three ready instances 16 s after the node returned.
- **Found and fixed on the way:**
  - **CloudNativePG operator:** a single copy can sit on the lost node, and then no failover happens for five minutes. The HA k3d cluster now runs two copies spread across nodes, and docs/deployment.md tells HA installs to do the same.
  - **PgBouncer:** the HA profile ran a single Pooler copy. It now runs two copies on different nodes, with a PDB and `tcp_user_timeout` 10 s. chart-lint's HA check covers Poolers and fails on one copy.
  - **k3d server:** tainted `CriticalAddonsOnly`, so any agent can be stopped without losing the control plane.
  - **Valkey smoke:** waits for five good answers in a row after the promotion. In one run a single request after the failover still failed.
  - **Dev k3d job:** gets the free-disk step, after Valkey was evicted for low ephemeral storage.
- **Follow-up, not done:**
  - **API database waits:** the API's pooled database connections have no client-side limit, which matters once they point at a pod that vanished: `pool_pre_ping` waits on the kernel. It recovered in this test, but bounding it touches `app/core/database.py` (every lane), so it needs the coordinator's agreement first.
  - **Valkey reconvergence:** after the Valkey failover the session took about 68 s to answer steadily. Find out why.
- **Resume:**
  1. Egress NetworkPolicies, as an opt-in allow-list with a cluster test.
  2. WP-014b session 2: CloudNativePG backups and PITR, SeaweedFS with rclone, the restore runbook, the pre-upgrade Job, the upgrade test.
