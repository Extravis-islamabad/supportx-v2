### 2026-11-13 — NodeLocal DNSCache for HA on k3s (D-163, lane B)

On branch feat/ha-nodelocal-dns (worktree supportx-v2-nodelocal), on main after #425. No
migration.

- **The add-on:** `deploy/k3s/node-local-dns.yaml`, rendered and applied by
  `deploy/k3s/node-local-dns.sh` (a DaemonSet in transparent mode, `kube-dns-upstream` for misses,
  `serve_stale`, `force_tcp`). The image is pinned by digest in `values.yaml`. The script refuses
  kube-proxy in ipvs mode and fails unless a cache is ready on every node and a pod resolves
  through it. `deploy/k3d/up.sh` runs it on the HA cluster before the strict preflight.
- **Preflight:** it checks for a cache on every schedulable node and warns on ipvs mode (from k3s's
  `k3s.io/node-args`). With the egress allow-list on, it checks that the policy lists the
  cache's addresses.
- **Egress:** `networkPolicies.egress.dnsAddresses` (new, default empty) adds ipBlock rules to
  the DNS rule. `values-ha.yaml` sets 169.254.20.10/32 and 10.43.0.10/32.
- **Tests:** Valkey failover and the session's write within 60 s again (90 s in #425), and the
  Valkey node-loss test fails if any live sentinel logged `+tilt` after the stop.
- **Docs:** deployment.md (the HA table, a NodeLocal DNSCache section, Preflight, Egress),
  deploy/README.md, D-163.md.

Proved by one Cluster run on the PR (number in the PR).
