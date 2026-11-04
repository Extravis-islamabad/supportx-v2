### 2026-11-04 — WP-014b session 1: the HA profile (lane B, draft #189)

- **Decisions:** the plan is ~/Desktop/wp-014b-plan.md. Decisions 1-6 were confirmed by the coordinator for the product owner, listed for his review:
  - a reduced HA profile on standard runners;
  - Valkey Sentinel in app/core;
  - Perses as the one dashboard source;
  - the licence pre-check skipped until WP-013;
  - the restore drill on SeaweedFS;
  - the Keycloak image kept internal.

  ADR-038 (Valkey HA through our own Sentinel) is proposed.
- **App:** `app/core/valkey.py` is the only way to reach Valkey (all 8 call sites), with Sentinel when SUPPORTX_VALKEY_SENTINELS is set.
- **Chart:**
  - `values-ha.yaml`;
  - `ha` values: anti-affinity, zone spread, PDBs for every multi-copy component;
  - an API HPA;
  - stream replicas follow the NATS cluster;
  - a Keycloak cluster NetworkPolicy;
  - HA Valkey: our own StatefulSet, a server plus a sentinel per pod, sentinel-first start-up;
  - Centrifugo ×3 on the Valkey engine;
  - `/auth/admin` blocked in Ingress mode;
  - the helm test checks HA Valkey's and the sentinels' auth.

  Single-node output is unchanged against the golden file.
- **Tests:**
  - chart-lint "ha" and "ha-ci" profiles, plus a PDB/anti-affinity check;
  - tests/ha/test_valkey_failover.py (CI "valkey failover", 3 local runs passing);
  - the k3d HA smoke (cluster.yml "k3d HA smoke (Valkey failover)"): a real BFF sign-in, the master killed, the session kept, the pod back as a replica.
- **Blocked:** the PR secret scan has one false positive (commit ca01882f, a Helm error message, since reworded). For the product owner: (A) one fingerprint entry, or (B) a clean replacement PR and the old branch deleted. The coordinator parked both. The clean replacement PR is opened when #189 is ready, and nothing is deleted.
- **Resume:**
  1. Make the k3d HA smoke pass on a runner.
  2. Egress NetworkPolicies, as an opt-in allow-list with a cluster test.
  3. The node-loss e2e acceptance test.
  4. Session 2: CloudNativePG backups and PITR, SeaweedFS with rclone, the restore runbook, the pre-upgrade Job, the upgrade test.
