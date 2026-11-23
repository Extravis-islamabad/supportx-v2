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
- **Round 2 (proving run 43148329223, node-loss red):** the stopped node held the PostgreSQL
  primary, the Valkey master and a CoreDNS copy. For about 45 s lookups failed through the dead
  CoreDNS endpoint, the sentinels entered TILT, SDOWN came 77 s after the stop (past the 50 s
  allowance of down-after 5 s), every failover aborted, and the retry was 120 s away. Now:
  - `valkeyHa.downAfterMilliseconds` 10000 (100 s allowance), `failoverTimeoutMilliseconds`
    30000 (an aborted failover retries after 60 s), each commented with the reason;
  - node-monitor grace period 20 s: `deploy/k3s/config-ha.yaml` (shipped k3s server config) and
    `deploy/k3d/cluster-ha.yaml`; recommended, not required, for customer-managed clusters;
    `docs/deployment.md` states the rule that the DNS failover window must fit inside
    10 x down-after. The preflight can't read the setting, so it doesn't check it;
  - `make cluster-ha-valkey-node-loss-dns`: the master and a CoreDNS copy on the stopped node,
    the placement forced (a CoreDNS copy moved if needed; the master handed over with the other
    replica at replica-priority 0);
  - `applied_since` compares times, not strings; the HA job's timeout is 60 minutes;
  - later: NodeLocal DNSCache (PROGRESS).
- **Round 3 (the coordinator's sweep of single copies in the HA profile):** the last proving run
  lost k3s's only Traefik copy with the stopped node; no request was answered for 90 s, the API
  pods healthy. Now:
  - Traefik 2 with required anti-affinity and a PodDisruptionBudget: `deploy/k3s/traefik-ha.yaml`
    (a HelmChartConfig for k3s's server manifests folder; the Traefik chart's own keys, chart
    40.1.0 as bundled by k3s v1.36.5), which the k3d HA cluster installs as is;
    `deploy/k3s/traefik-ha.sh` waits for two ready copies on two nodes (`make cluster-up-ha`);
    single-node k3d keeps one copy;
  - NATS (the subchart's `podTemplate.merge`) and the CloudNativePG cluster
    (`affinity.podAntiAffinityType: required`) with required anti-affinity; workflow timers 2;
    ClamAV 2, spread, its freshclam checks staggered by StatefulSet ordinal;
  - fast eviction for the single-copy fan-out and index workers (`ha.fastEvictionSeconds: 30`,
    NoExecute tolerations for the unreachable and not-ready taints): about 50 s, not 300 s;
  - the preflight checks Traefik, NATS and PostgreSQL spread and the tolerations once the
    release is in (`make cluster-ha-preflight`, a new step in the HA job), and warns, advisory
    only, about the bundled SeaweedFS (decision b: HA installs use their own S3 store; a bundled
    HA SeaweedFS is open in PROGRESS);
  - node-loss.sh: after the write returns, the fan-out is ready on a live node (moved within
    90 s if it was on the stopped one) and acknowledges past a write made after that
    (`realtime__fanout` on `SUPPORTX_EVENTS`, NATS monitoring endpoint);
  - `docs/deployment.md`: what runs how many copies in the HA profile, Traefik and object
    storage for k3s HA installs. Single-node render unchanged (golden file untouched).
