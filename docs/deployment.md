# Deployment on Kubernetes (WP-014)

How SupportX runs on Kubernetes: the Helm chart, the local k3d cluster, the images and CI.
Decisions: ADR-025, D-037, D-038. Still to come: HA and backups (WP-014b), signed release bundles
and the air-gapped installer (WP-014c), SaaS cells (WP-014d).

> **Images are INTERNAL/DEV builds.** Plain CPython with source included, labelled
> `com.extravis.supportx.distribution=internal-dev-only`. They must never be given to a customer
> and are pushed only to private registries (D-038). Customer bundles need the Nuitka build
> (ADR-009, WP-013).

## Run it locally (k3d)

Prerequisites on the Mac: Docker Desktop with at least 12 GB memory (check: `docker info`),
k3d 5.9, kubectl 1.37, Helm 4.3 (all via Homebrew). The Compose dev stack may keep running; the
cluster uses its own ports.

```bash
make cluster-up      # k3d cluster "supportx" (k3s v1.36.5) + CloudNativePG operator  (~2 min)
make deploy-dev      # build both images, import them, create secrets, install, helm test (~6 min first time)
open http://supportx.localhost:8080            # console (sign in: admin@demo.test / Admin-Demo-2026!)
open http://supportx.localhost:8080/portal/    # portal  (user@demo.test / User-Demo-2026!)
make cluster-test    # helm test again: every internal route answers, Valkey enforces auth
make cluster-e2e     # all Playwright journeys against the cluster (ARGS="tests/login.spec.ts" for one)
make chart-lint      # lint + render + kubeconform for every profile, golden-file check
make cluster-down    # deletes the cluster and its data (asks for "yes")
```

`make deploy-dev` is also the upgrade: run it again after any change; it rebuilds the images and
rolls the pods. The demo users are the ones of the dev realm (docs/dev-setup.md). Keycloak's admin
console is at <http://supportx.localhost:8080/auth/admin> in the dev profile only; its password is
in the `supportx-app` Secret (`keycloak-admin-password`).

## What runs where

| Pod | Image | Copies (dev / single-node) | Ports | Probes |
|---|---|---|---|---|
| `supportx-api` (API + BFF) | supportx-backend | 1 / 1 (scales out) | 8000 http, 9464 metrics | `/api/v1/health`, `/api/v1/ready` |
| `supportx-relay` (outbox → NATS) | supportx-backend | 1 / 1 (several allowed) | 9464 | `/healthz`, `/readyz` |
| `supportx-consumers` | supportx-backend | 1 / 1 (several allowed) | 9464 | `/healthz`, `/readyz` |
| `supportx-fanout` (events → Centrifugo) | supportx-backend | **always 1** (ADR-023) | 9464 | `/healthz`, `/readyz` |
| `supportx-migrate-<revision>` (Job) | supportx-backend | once per revision | — | — |
| `supportx-web` (console `/`, portal `/portal/`) | supportx-web | 1 / 1 | 8080 | `/healthz` |
| `supportx-centrifugo` | centrifugo v6.10.1 | 1 / 1 | 8000 | `/health` |
| `supportx-keycloak` | keycloak 26.8.1 | 1 / 1 | 8080, 9000 management | `/health/*` |
| `supportx-pg-1` (PostgreSQL 16 + pgvector) | CloudNativePG | 1 / 1 | 5432 | operator |
| `supportx-pg-pooler` (PgBouncer, transaction mode) | CloudNativePG | 1 / 1 | 5432 | operator |
| `supportx-nats-0` (JetStream) | NATS chart 2.15.1 | 1 / 1 | 4222, 7777 metrics | chart |
| `supportx-valkey` (sessions, caches, rate limits; no persistence) | Valkey chart 0.12.0 | 1 / 1 | 6379, 9121 metrics | chart |

Public routes (one host, D-038): `/api` → API, `/connection` + `/emulation` → Centrifugo,
`/auth` → Keycloak (`/auth/admin` only in dev), `/portal/` and `/` → web. Gateway API (Traefik on
k3s) by default; `routing.mode=ingress` for a plain Ingress.

**Start order.** The migrate Job of each Helm revision creates the roles and database
(`tooling/sql`), lets the pooler authenticate them, then runs Alembic. The API and workers of that
revision wait for it in an init container. Rolling back an upgrade (`helm rollback`) moves only the
images; the schema is never downgraded.

**Reporting role (WP-035, ADR-033).** `tooling/sql/roles.sql` also creates `supportx_report`
(NOLOGIN, NOBYPASSRLS) and grants it to `supportx_app`; reports switch to it with `SET LOCAL ROLE`
so they can only read. A DBA-managed database without the admin URL must run that part of
`roles.sql` by hand before migration 0027. On HA profiles, point `SUPPORTX_REPORTING_DATABASE_URL`
at the read replica (CloudNativePG's `-ro` service) so reports never load the primary; unset,
reports use the main database through their own small pool (single node).

## Secrets

The chart only references Secrets. `deploy/scripts/secrets.sh <namespace>` creates them with random
hex values and never overwrites an existing one (its passwords are already inside the databases).

| Secret | Keys |
|---|---|
| `supportx-app` | `app-db-password`, `migrator-db-password`, `relay-db-password`, `session-secret`, any `session-key-*` listed in `secrets.sessionKeys` (the sign-in key ring, D-162; [rotating it](guides/rotating-the-sign-in-key.md)), `centrifugo-token-secret`, `centrifugo-api-key`, `oidc-console-secret`, `oidc-portal-secret`, `keycloak-admin-password`, `nats-password`, `valkey-password`, `s3-access-key`, `s3-secret-key`, `seaweedfs-s3-config` (SeaweedFS's s3.json for that key pair), `audit-signing-key` (`<key id>:<base64 Ed25519 seed>`, consumers worker only; ADR-027), `temporal-db-password` (the bundled Temporal's `temporal` role, with `temporal.bundled.enabled`) |
| `supportx-db-keycloak` (basic-auth) | `username` = `keycloak`, `password` |
| `supportx-pg-superuser` | created by CloudNativePG; used only by the migrate Job |

## Profiles

- `values-dev.yaml`: k3d, plain http on `supportx.localhost:8080`, the dev realm with demo users,
  demo tenants seeded, Keycloak admin API public, a NodePort to PostgreSQL on the host's loopback
  (127.0.0.1:25433) for the e2e suite's tools. **Never** use it anywhere else.
- `values-single-node.yaml`: one k3s VM (8 vCPU / 32 GB / 500 GB), production profile, HTTPS on
  Traefik's websecure listener with your certificate Secret, the base realm (no users). **Internal
  evaluation only** until backups (WP-014b) and Nuitka images exist.
- `values-ha.yaml` (WP-014b, ADR-038): three or more nodes. Two or three copies of every stateless
  component, PostgreSQL with one primary and two standbys, two PgBouncer copies, a three-server
  NATS cluster and Valkey with Sentinel. Copies sit on different nodes, each with a
  PodDisruptionBudget. **Install the CloudNativePG operator with two copies on different nodes**
  (`replicaCount=2`, a hostname spread; `deploy/k3d/prereqs.sh` shows how). With one copy,
  losing its node stops the database failover until Kubernetes moves the operator pod, about
  five minutes later.

  **Cluster DNS: at least two copies on different nodes (k3s ships one).** With one copy, losing
  its node stops every name lookup in the cluster until Kubernetes re-creates the pod, about
  five minutes later (the 300 s unreachable eviction). Valkey's sentinels find each other and
  their master by hostname, so meanwhile they keep entering TILT, no quorum forms, and once the
  replicas' links have been down that long no replica is good enough to promote: Valkey stays
  down until the node returns (Cluster run 43082299609). On k3s, run
  `deploy/k3s/cluster-dns-ha.sh` before installing and after every k3s upgrade. It runs

  ```
  kubectl -n kube-system scale deploy/coredns --replicas=2
  kubectl -n kube-system patch deploy/coredns --type=strategic -p '{"spec":{"template":{"spec":{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"k8s-app":"kube-dns"}},"topologyKey":"kubernetes.io/hostname"}]}}}}}}'
  kubectl -n kube-system rollout status deploy/coredns --timeout=300s
  ```

  and fails unless two ready copies sit on two nodes. k3s's CoreDNS is a plain manifest, not a
  Helm chart, so a `HelmChartConfig` does not reach it. At every start k3s rewrites
  `server/manifests/coredns.yaml` and applies it again, but as a three-way merge against the last
  applied copy: fields the manifest never set (it sets neither replicas nor affinity) are left
  as they are, so a restart keeps both. The HA job proves it on every run (`make
  cluster-ha-dns-restart` restarts the server and checks). A k3s upgrade whose manifest starts
  setting either would reset it, hence the re-run after upgrades. We did not take the
  `coredns.yaml.skip` or `--disable coredns` route: either freezes CoreDNS at our own copy, so k3s
  upgrades (security fixes included) no longer reach it. On a customer-managed cluster (any
  other distribution), do the same to its DNS deployment: two or more copies with required pod
  anti-affinity (or a `DoNotSchedule` topology spread) on `kubernetes.io/hostname`. kubeadm,
  RKE2 and managed clusters usually run two copies already; check where they run.

  **Preflight.** `deploy/k3s/ha-preflight.sh` checks a cluster for the HA profile, read-only:
  three or more schedulable nodes, cluster DNS ready on two or more nodes, the CloudNativePG
  operator ready on two or more nodes. Each unmet requirement prints a WARNING and how to fix
  it (exit 0; `HA_PREFLIGHT_STRICT=1` fails on any warning, as `make cluster-up-ha` does). Run it
  before the install and after any cluster upgrade. `helm install` with `values-ha.yaml` also
  warns in its notes when `kube-system/coredns` runs one copy.

  **Node-monitor grace period: 20 s recommended (not required).** Until Kubernetes marks a lost
  node NotReady (the controller manager's `node-monitor-grace-period`, about 40-50 s by default),
  Services keep routing to its pods: a dead CoreDNS copy swallows part of the cluster's DNS
  queries, and the PgBouncer pooler and API copies on it keep getting requests. With 20 s these
  endpoints drop in about 20 s. Pods are still evicted only after the default 300 s
  not-ready/unreachable toleration, so a short network blip marks a node NotReady for a moment
  without moving any workload. On k3s use `deploy/k3s/config-ha.yaml`
  (`kube-controller-manager-arg: [node-monitor-grace-period=20s]` in each server's
  `/etc/rancher/k3s/config.yaml`); the k3d HA cluster in CI runs it. On a customer-managed
  cluster, set the same flag on kube-controller-manager if your platform allows it (managed
  services often don't). 20 s is twice the kubelet's 10 s status renewal; don't go lower.
  `ha-preflight.sh` can't read this setting (the controller manager runs inside k3s, not as a
  pod), so it doesn't check it.

  **The operator's rule: the DNS failover window must fit inside 10 × Sentinel's down-after.**
  Valkey Sentinel resolves hostnames synchronously, about 4 s blocked per pass while a CoreDNS
  endpoint is dead, so it enters TILT and notices a lost master late. It then promotes only a
  replica whose link has been down for less than 10 × `valkeyHa.downAfterMilliseconds` plus the
  master's SDOWN age: 100 s with our 10 s. The cluster's DNS failover window (roughly the
  node-monitor grace period, until a lost node's CoreDNS endpoint drops) has to fit inside it. In
  Cluster run 43148329223 SDOWN came 77 s after the node stop, past the 50 s that down-after 5 s
  allowed, and every failover aborted (`-failover-abort-no-good-slave`). **Anyone raising the
  grace period or lowering down-after must keep this true**, or a failover after a node loss can
  abort for good. An aborted failover is retried after 2 × `failoverTimeoutMilliseconds` (30 s,
  so 60 s later).

  **What to expect today: about 1 minute of failover after a node loss** (Valkey's new master
  and the sessions writing again; PostgreSQL promotes in under a minute too). While a lost
  node's CoreDNS endpoint is still listed (about 20 s), lookups that reach it time out; Sentinel
  resolves hostnames synchronously, so the stall puts it in TILT, a fixed 30 s pause, before it
  fails over. A node-local DNS cache (NodeLocal DNSCache, next in the HA work) removes that stall
  and brings failover down to about 15 s. The HA tests allow 90 s until then.

  Valkey's pods look names up with `ndots 1`, a 1 s timeout and 2 attempts (`dnsConfig` in
  `templates/valkey-ha.yaml`), and name every peer in full
  (`<pod>.supportx-valkey-headless.<namespace>.svc.<cluster domain>`, the domain read from the
  pod's own search list): one query per name that fails fast, so a short DNS blip never stalls a
  sentinel into TILT.

  Measured on the k3d HA cluster (node-loss test, 2026-11-04): the agent with the primary is
  stopped; a standby is promoted after about 70 s, and the same signed-in session writes again
  about 30 s after that.

  **Valkey failover and readiness.** Sentinel learns a master's replicas only from the master's
  INFO, which it reads every 10 s (fixed in Valkey). A master stopped before its sentinels saw
  its replicas cannot fail over: every attempt aborts with `-failover-abort-no-good-slave` until
  it is back. So a Valkey pod becomes Ready only once its own sentinel knows it in its role
  (`ready.sh` in `templates/valkey-ha.yaml`): a replica when it is synced and its sentinel lists
  it, a master when its sentinel lists every replica connected to it. After that first readiness
  only the server counts, so a sentinel that restarts never makes Valkey unready; a promotion,
  a demotion or a container restart gates again. `kubectl describe pod` shows what a pod waits
  for. Planned restarts, rolling updates and drains (which wait for Ready) are therefore covered.
  **The remaining gap:** an unplanned crash of a master within about 10 s of a fresh start, before
  the sentinels' next INFO, can still miss the failover until that pod is back. No data is lost
  (a pod never starts as an empty master while a peer may hold data), but Valkey is unavailable
  meanwhile; Kubernetes restarts the pod, and it rejoins.

## Client addresses behind the gateway

The API believes `X-Forwarded-For` only from `api.trustedProxies` (addresses or CIDRs; default
`10.42.0.0/16`, k3s's pod network, where Traefik runs). The client address it uses for rate limits
and the audit log is the last one in the header that isn't a trusted proxy, so a client can't
choose its own. Set it to your cluster's pod CIDR, or to your load balancer's addresses if one
sits in front of the gateway. If it doesn't match, every request seems to come from the gateway,
so per-address rate limits are shared by everyone.

## Egress allow-list (opt-in)

Ingress is always denied by default. Egress is open unless `networkPolicies.egress.enabled` is
true (WP-014b). With it on, pods may reach:
- **DNS and the namespace:** every pod may reach DNS (kube-dns) and the other pods of the
  namespace.
- **The Kubernetes API:** CloudNativePG's pods and the API and worker pods (their
  wait-for-migrate step) may reach it, at its real addresses. The chart reads them from the
  `default/kubernetes` EndpointSlice at install time. Where it can't read the cluster (`helm
  template`, GitOps), set `networkPolicies.egress.kubeApiCidrs` (and `kubeApiPorts`, usually
  6443); otherwise the chart refuses to install. It never falls back to `0.0.0.0/0`. Find the
  addresses with `kubectl get endpointslice -n default kubernetes`.
- **Everything else must be listed**, as NetworkPolicy egress rules (`to` with `ipBlock` CIDRs,
  and `ports`):
  - `networkPolicies.egress.extra`: rules for every pod;
  - `networkPolicies.egress.components.<component>`: rules for one component's pods.

**Addresses only.** NetworkPolicies match IP ranges, never host names. A service known only by
name (Microsoft Graph, an AI provider, a CDN) has no fixed addresses. Without a CNI with
host-name policies (such as Cilium), route those through a **forward proxy**, list only the
proxy, and set the proxy for the pods (`HTTPS_PROXY`).

Example for a typical on-prem install. The mail relay, the domain controllers and the proxy are
inside the network; Graph and the AI provider go through the proxy:

```yaml
networkPolicies:
  egress:
    enabled: true
    extra:                               # every pod: the forward proxy
      - to: [{ipBlock: {cidr: 10.20.0.15/32}}]
        ports: [{protocol: TCP, port: 3128}]
    components:
      consumers:                         # outgoing mail
        - to: [{ipBlock: {cidr: 10.20.1.25/32}}]
          ports: [{protocol: TCP, port: 587}]
      keycloak:                          # AD/LDAP (LDAPS)
        - to: [{ipBlock: {cidr: 10.20.2.0/28}}]
          ports: [{protocol: TCP, port: 636}]
      clamav:                            # a private signature mirror
        - to: [{ipBlock: {cidr: 10.20.3.40/32}}]
          ports: [{protocol: TCP, port: 443}]
clamav:
  privateMirror: https://clamav-mirror.example.internal
```

**ClamAV** needs its signature source. The public mirrors are a CDN with no fixed addresses, so
set `clamav.privateMirror`, list your proxy, or load the offline bundle
(`deploy/scripts/clamav-signatures.sh`). The chart prints a warning when egress is on and ClamAV
has none of these. `/api/v1/ready` reports `malware_signatures` as a warning once the signatures
are over 48 hours old (`SUPPORTX_FILES_SIGNATURE_READY_WARN_HOURS`), and
`supportx_files_signature_age_seconds` carries their age for the alert. Anything not listed is
dropped, so check every integration after turning egress on.

CI runs the HA cluster with egress on (`values-ha-ci.yaml`), and `make cluster-ha-egress` checks
that the namespace answers and the outside doesn't. chart-lint checks that the chart refuses to
render without the control plane's addresses, and that no egress rule opens `0.0.0.0/0`.

## Backups

`postgresql.cnpg.backup.enabled` turns on CloudNativePG's Barman Cloud plugin (a cluster
prerequisite, installed like the operator: `deploy/k3d/prereqs.sh` with `BACKUP_PLUGIN=1` shows
how). **On HA installs, run the plugin with two copies on different nodes too, like the
operator:** the operator won't reconcile a cluster, failover included, while its plugin is
unreachable. The database's WAL is archived continuously and a base backup is taken daily, so it can be
restored to any moment within `retentionPolicy` (30 days by default).

**Production: back up to storage outside the cluster.** By default the backups go to this
release's own SeaweedFS, which is fine for dev and CI but shares the database's failure domain:
losing the cluster or its disks loses the backups too, and the chart warns about it. For
production set `destinationPath`, `endpointURL` and `credentialsSecret` (keys `ACCESS_KEY_ID`,
`ACCESS_SECRET_KEY`) to a bucket elsewhere, with credentials of its own, so the application's
keys can't touch the backups.

**Encrypted at rest.** The target encrypts (S3 server-side): set `encryption` to `AES256` or
`aws:kms`, or use a bucket whose policy encrypts every object. Barman Cloud has no client-side
encryption; the offsite copy of the object storage (rclone, WP-014b) adds it with its own key.

The restore runbook, and the CI drill that runs it, come with WP-014b session 2.

## Observability

Every SupportX pod serves Prometheus metrics on 9464 (`http_server_*` for the API; outbox age,
relay counts, consumer lag, DLQ and fan-out counters for the workers). CloudNativePG, NATS
(7777), Valkey (9121), Centrifugo and Keycloak (9000) export their own. With the Prometheus
Operator installed the chart creates a PodMonitor; otherwise pods carry `prometheus.io/*`
annotations. Dashboards, alerts and the on-prem monitoring bundle (VictoriaMetrics, VictoriaLogs,
Jaeger, Perses) come with WP-014b.

## CI

| Workflow | When | What |
|---|---|---|
| CI › `chart` | every PR | `make chart-lint`: helm lint, render for 5 profile variants, kubeconform (Kubernetes 1.36 + CRD schemas), golden single-node render |
| Security › `trivy` | every PR, push, nightly | filesystem scan incl. the Dockerfiles and the rendered single-node manifests (misconfigurations) |
| Cluster › `images` | PRs touching `deploy/` or the Makefile, nightly | build both images (not pushed), Trivy gate (fixable HIGH/CRITICAL fail), CycloneDX SBOMs as artifacts |
| Cluster › `smoke` | same | k3d with the pinned k3s, `make deploy-dev` (incl. `helm test`), public routes through the gateway |
| Cluster › `e2e` | nightly, on demand | everything above, then every Playwright journey against the cluster |
| Cluster › `ha-smoke` | nightly, on demand, PRs labelled `full-ci` | a four-node k3d cluster with `values-ha.yaml`. The bring-up gives CoreDNS two copies on different nodes and runs the HA preflight (strict). First the Valkey master is killed (the session survives, no split brain). Then the node with the promoted Valkey master is stopped (`make cluster-ha-valkey-node-loss`): Sentinel promotes again within 60 s, the session writes again, the old master returns as a replica. The same again in the worst case, forced by the test (`make cluster-ha-valkey-node-loss-dns`): the stopped node holds the Valkey master and a CoreDNS copy. Then the agent with PostgreSQL's primary is stopped (`make cluster-ha-node-loss`): a standby is promoted, the session writes again, and the node rejoins as a standby. Then the k3s server restarts (`make cluster-ha-dns-restart`): CoreDNS keeps two copies on two nodes and its anti-affinity |

## Troubleshooting

- Pods stuck in `Init`: `kubectl -n supportx logs job/supportx-migrate-<revision>`.
- `helm upgrade` fails on `--wait`: `kubectl -n supportx get pods` and `kubectl -n supportx
  describe pod <pod>`; Keycloak needs about a minute to build itself at start.
- After changing the dev realm file: Keycloak imports it only when the realm does not exist yet;
  recreate the cluster (`make cluster-down cluster-up deploy-dev`).
