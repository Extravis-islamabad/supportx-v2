### 2026-11-12 — HA fix: cluster DNS never single; Valkey survives a DNS blip (lane B)

Deployment only (deploy/, Makefile, the Cluster workflow, docs); no app code, no new dependency.

- **Cause (Cluster run 43082299609, job "k3d HA smoke (Valkey failover)"):** `make
  cluster-ha-node-loss` stopped k3d-supportx-agent-0, which held k3s's only CoreDNS pod; it came
  back only after the 300 s unreachable eviction. Sentinel resolves its peers by hostname, so the
  sentinels kept entering TILT, no quorum formed, and once SDOWN came the replicas'
  master-link-down time (about 386 s) ruled every replica out (`-failover-abort-no-good-slave`).
  The readiness gate (#393) and the never-start-empty guard (#284) were not the cause and are
  unchanged.
- **Cluster DNS:** `deploy/k3s/cluster-dns-ha.sh` scales kube-system/coredns to 2, adds required
  pod anti-affinity on `kubernetes.io/hostname` and fails unless two ready copies sit on two
  nodes. `make cluster-up-ha` runs it before the chart, then `deploy/k3s/ha-preflight.sh`
  strictly. The preflight (read-only) warns about fewer than three nodes, DNS on fewer than two
  nodes and the CloudNativePG operator on fewer than two; `helm install` notes warn too.
  Documented in `values-ha.yaml` and `docs/deployment.md` (k3s and customer-managed clusters).
- **Valkey:** `dnsConfig` ndots 1, timeout 1, attempts 2; every peer named in full
  (`<pod>.supportx-valkey-headless.<namespace>.svc.<cluster domain>`, the domain read from the
  pod's search list), one query per name. Hostnames are still announced. chart-lint guards both.
- **Tests:** helpers in `deploy/k3d/ha-lib.sh`; node-loss.sh waits for Sentinel to settle and
  checks DNS outlives the node; new `deploy/k3d/valkey-node-loss.sh` (`make
  cluster-ha-valkey-node-loss`) runs after ha-smoke in the HA job; failure diagnostics print each
  sentinel's view, the CoreDNS pods and 15 minutes of Valkey and Sentinel logs.
- **k3s restarts (coordinator's follow-up):** kept the scale-and-patch route. In the pinned
  k3s (v1.36.5+k3s1) every start rewrites `coredns.yaml` and force-applies it, but as wrangler's
  three-way merge, which leaves replicas and affinity alone because the manifest sets neither.
  The `.skip` or `--disable` routes would freeze CoreDNS against k3s upgrades. New
  `deploy/k3d/dns-after-restart.sh` (`make cluster-ha-dns-restart`), run after the node-loss
  tests: it restarts the server and fails if k3s reset either.
- **Not run here:** k3d. The next Cluster dispatch proves it.
