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

**Upgrading to a release that adds a secret key: re-run `deploy/scripts/secrets.sh <namespace>`
before `helm upgrade`.** It only adds the missing keys. Since the security bundle B1 (#451) the
API needs `api-key-secret` (the API keys' own HMAC key) in production and refuses to start without
it, with a message saying so; keys made before keep working (re-hashed on first use, while
`session-secret` stays set). The coordinator's decision (2026-11-12): hard from the start, as
there are no customer installs yet. Once one exists, a change like this ships with a release-note
announcement and a migration path that removes nothing silently (Haider's rule).

| Secret | Keys |
|---|---|
| `supportx-app` | `app-db-password`, `migrator-db-password`, `relay-db-password`, `session-secret`, `api-key-secret` (the API keys' own HMAC key, required in production; [API keys](api/keys.md)), any `session-key-*` listed in `secrets.sessionKeys` (the sign-in key ring, D-162; [rotating it](guides/rotating-the-sign-in-key.md)), `centrifugo-token-secret`, `centrifugo-api-key`, `oidc-console-secret`, `oidc-portal-secret`, `keycloak-admin-password`, `nats-password`, `valkey-password`, `s3-access-key`, `s3-secret-key`, `seaweedfs-s3-config` (SeaweedFS's s3.json for that key pair), `audit-signing-key` (`<key id>:<base64 Ed25519 seed>`, consumers worker only; ADR-027), `temporal-db-password` (the bundled Temporal's `temporal` role, with `temporal.bundled.enabled`) |
| `supportx-db-keycloak` (basic-auth) | `username` = `keycloak`, `password` |
| `supportx-db-seaweedfs-filer` (basic-auth) | `username` = `seaweedfs_filer`, `password`: the HA SeaweedFS filers' database role (`objectStorage.seaweedfs.ha`, D-166); CloudNativePG sets the role's password from it |
| `supportx-pg-superuser` | created by CloudNativePG; used only by the migrate Job |

## Profiles

- `values-dev.yaml`: k3d, plain http on `supportx.localhost:8080`, the dev realm with demo users,
  demo tenants seeded, Keycloak admin API public, a NodePort to PostgreSQL on the host's loopback
  (127.0.0.1:25433) for the e2e suite's tools. **Never** use it anywhere else.
- `values-single-node.yaml`: one k3s VM (8 vCPU / 32 GB / 500 GB), production profile, HTTPS on
  Traefik's websecure listener with your certificate Secret (plain HTTP redirected to it), the
  base realm (no users). **Internal evaluation only** until backups (WP-014b) and Nuitka images
  exist.
- `values-staging.yaml` (D-169): on top of `values-single-node.yaml`, the staging laptop: its
  LAN name, its own CA's certificate, locally built images, demo data, laptop sizes. Only with
  [the staging laptop runbook](runbooks/staging-laptop.md).
- `values-ha.yaml` (WP-014b, ADR-038): three or more nodes. Two or three copies of every stateless
  component, PostgreSQL with one primary and two standbys, two PgBouncer copies, a three-server
  NATS cluster and Valkey with Sentinel. Copies sit on different nodes, each with a
  PodDisruptionBudget. **Install the CloudNativePG operator with two copies on different nodes**
  (`replicaCount=2`, a hostname spread; `deploy/k3d/prereqs.sh` shows how). With one copy,
  losing its node stops the database failover until Kubernetes moves the operator pod, about
  five minutes later.

  **What runs how many copies in the HA profile.** "Spread" means required pod anti-affinity on
  `kubernetes.io/hostname` (`ha.antiAffinity: hard`): two copies never share a node, so a lost
  node takes at most one. `deploy/k3s/ha-preflight.sh` checks the rows marked *(preflight)*.

  | Component | Copies | How it survives a lost node |
  |---|---|---|
  | API | 3 to 6 (HPA, minimum 3), spread | the others serve; PodDisruptionBudget |
  | Web | 2, spread | the other serves |
  | Outbox relay | 2, spread | both share the outbox (`FOR UPDATE SKIP LOCKED`) |
  | Event consumers | 2, spread | both share each durable consumer |
  | SLA timers (Temporal worker) | 2, spread | both share the task queue; a repeated task is a no-op |
  | Workflow timers (Temporal worker) | 2, spread | the same |
  | Keycloak | 2, spread | Infinispan shares sessions between the copies |
  | Centrifugo | 3, spread | the Valkey engine (through Sentinel) links the copies |
  | Temporal (bundled) | 2, spread | the server pods share the shards (membership) |
  | Valkey + Sentinel | 3, spread | Sentinel promotes a replica (below) |
  | PostgreSQL (CloudNativePG cluster) | 3 instances, required anti-affinity *(preflight)* | CloudNativePG promotes a standby |
  | PgBouncer pooler | 2, spread | the other copy; dead server links dropped in 10 s |
  | NATS | 3 servers, required anti-affinity *(preflight)* | JetStream keeps quorum (2 of 3); streams keep 3 replicas |
  | ClamAV | 2, spread | the Service balances scans over both; their signature pulls are staggered |
  | CoreDNS (k3s) | 2, spread *(preflight)* | `deploy/k3s/cluster-dns-ha.sh` (below) |
  | Traefik (k3s) | 2, spread *(preflight)* | `deploy/k3s/traefik-ha.yaml` (below) |
  | NodeLocal DNSCache | 1 per node *(preflight)* | `deploy/k3s/node-local-dns.sh` (below); each node's pods use their own node's cache |
  | CloudNativePG operator | 2, hostname spread *(preflight)* | `deploy/k3d/prereqs.sh` shows how |
  | Barman Cloud plugin | 2, hostname spread | the same; the operator blocks a cluster's changes, failover included, while its plugin is unreachable |
  | SeaweedFS masters (bundled object storage) | 3 (one raft group), required anti-affinity *(preflight)* | raft elects a new leader among the other two (2 of 3); PodDisruptionBudget keeps 2 |
  | SeaweedFS volume servers | 3, required anti-affinity *(preflight)* | every file has **2 copies** on two servers on two nodes (replication `001`, *preflight*); the leader re-makes missing copies (`volume.fix.replication`, every 17 minutes) |
  | SeaweedFS filers with the S3 gateway | 2, required anti-affinity | the other filer serves through the same `supportx-seaweedfs` Service; their metadata is in the PostgreSQL cluster above (own database and role) |
  | **Single copy, and why that is acceptable** | | |
  | Realtime fan-out | 1 (ADR-023: merge windows and per-tenant rate limits are in memory) | fast eviction *(preflight)*: evicted 30 s after its node goes NotReady (`ha.fastEvictionSeconds`), so it runs again elsewhere about 50 s after the loss instead of five minutes. Meanwhile live updates pause; screens reconcile by refetch when their realtime connection returns (architecture.md §8.3). The node-loss test checks that it moves and that events reach it again. |
  | Custom field index worker | 1 (D-088: one builder, behind an advisory lock) | background work only; fast eviction as the fan-out *(preflight)* |
  | local-path-provisioner (k3s) | 1 | only creates new volumes; local volumes are bound to their node anyway |
  | metrics-server (k3s) | 1 | only feeds the HPA, which keeps its current count meanwhile |
  | cert-manager | 1 | renewals start days before expiry; its webhook matters only while certificate resources are applied |

  **Object storage: the bundled SeaweedFS, replicated (D-166).** With `values-ha.yaml` the
  bundled SeaweedFS (`objectStorage.mode: seaweedfs`) runs SeaweedFS's own replication
  (`objectStorage.seaweedfs.ha`) instead of the single pod of the single-node profile: three
  masters, three volume servers and two filers running the S3 gateway, each on its own node,
  behind the same `supportx-seaweedfs:8333` Service, so the app's settings do not change. Every
  file is written to two volume servers (replication `001`; `002` keeps three copies and needs
  every volume server up to write), so a lost node loses no file, and uploads and downloads go on
  within a minute (the object-storage node-loss test below). The filers keep the file tree in the
  release's CloudNativePG cluster: its own database (`seaweedfs_filer`) and role
  (`seaweedfs_filer`), which may sign in to that database only (pg_hba) and has no other rights.
  Because it is the same cluster, the file tree is in the same database backups and comes back
  with the same restore (the restore drill checks it). While the database fails over, file
  reads and writes pause with the rest of SupportX.

  **Sizing:** plan the volume servers' disks for twice the stored files with `001` (three times
  with `002`), plus room to re-make the copies of one lost server on the others. Set
  `objectStorage.seaweedfs.ha.volume.storage.size` per server accordingly.

  **Your own S3-compatible store stays supported.** An HA install may instead point the chart
  at its own highly available S3-compatible store (a MinIO cluster, NetApp StorageGRID or ONTAP
  S3, Ceph RGW, or a cloud S3); then no SeaweedFS is installed at all:

  ```yaml
  objectStorage:
    mode: external                  # no bundled SeaweedFS is installed
    bucket: supportx                # created beforehand
    region: us-east-1
    external:
      endpoint: https://s3.internal.example.com
  ```

  with the access keys in the app Secret (keys `s3-access-key`, `s3-secret-key`). With backups
  on, the database backups then go to that store too (`postgresql.cnpg.backup`, a separate bucket
  and credentials recommended), and it must encrypt at rest (`postgresql.cnpg.backup.encryption`
  or `encryptionByBucketPolicy: true`); the chart refuses otherwise (Backups).

  **Replication is not a backup.** Two copies mean a lost server or disk loses nothing. A file
  deleted or overwritten (by a person, a bug or an attacker) is deleted or overwritten in every
  copy at once, though. The file-store backup (the offsite rclone copy, audit gap #1) is still
  needed, as it is with an external store.

  **Upgrade note for existing HA installs.** `values-ha.yaml` now turns the replicated store
  on, so an HA release upgraded with it starts the new store **empty**: follow the steps below in
  a maintenance window. To upgrade the rest first, keep the old store with
  `--set objectStorage.seaweedfs.ha.enabled=false`. The preflight then warns that the
  single-copy store runs under HA, and `HA_PREFLIGHT_STRICT=1` fails, until the move is done.

  **Moving an existing single-copy install to HA.** The chart does not move files from the
  single SeaweedFS pod to the replicated topology: the two are different stores (the filers'
  metadata moves into PostgreSQL), and switching `objectStorage.seaweedfs.ha.enabled` on an
  installed release starts the replicated one empty. Move the files by hand, in a maintenance
  window, with rclone (approved, D-038), not automated:

  1. Before the upgrade, stop uploads (scale the API and the consumers worker to 0) and copy the
     bucket out of the old store, through a port-forward to its S3 port
     (`kubectl -n supportx port-forward svc/supportx-seaweedfs 8333:8333`), to a disk or another
     S3 bucket with room for it: `rclone copy old:supportx /backup/supportx`, with an rclone
     remote `old` of type `s3`, provider `SeaweedFS`, endpoint `http://127.0.0.1:8333` and the
     app Secret's `s3-access-key` / `s3-secret-key`. Keep the old pod's volume until the end.
  2. Upgrade with `values-ha.yaml`; wait until `deploy/k3s/ha-preflight.sh` passes.
  3. Copy the bucket into the new store through the same Service name (now the filers):
     `rclone copy /backup/supportx new:supportx`.
  4. Verify every object, size and checksum: `rclone check /backup/supportx new:supportx`
     (and `rclone check old:supportx new:supportx` while the old store can still be reached). It
     must report 0 differences before the API is scaled back up.
  5. Only then delete the old pod's volume (`data-supportx-seaweedfs-0`), with the product
     owner's confirmation (CLAUDE.md rule h).

  The database backups (`backups/postgres` in the same bucket, in dev and CI) are files like any
  other: copy them too, or start a fresh backup chain after the move.

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

  **Traefik: two copies on different nodes (k3s ships one).** Every request into SupportX
  passes the ingress. With k3s's one Traefik copy, the node-loss test's stopped agent held it:
  the pod stayed "Running" until the 300 s eviction and no client request was answered for 90 s,
  although the API pods were healthy. k3s installs Traefik as a Helm chart, so a
  `HelmChartConfig` reaches it. On a k3s HA install, on every server:

  ```
  sudo cp deploy/k3s/traefik-ha.yaml /var/lib/rancher/k3s/server/manifests/traefik-config.yaml
  bash deploy/k3s/traefik-ha.sh      # waits until two ready copies run on two nodes, else fails
  ```

  If that folder already holds a `HelmChartConfig` named `traefik` (k3s keeps one per chart),
  merge the file's values into it instead. It keeps the Gateway API and streaming settings, and
  adds `deployment.replicas: 2`, required pod anti-affinity on `kubernetes.io/hostname` and a
  PodDisruptionBudget (the Traefik chart's own keys; k3s v1.36.5 bundles chart 40.1.0). k3s
  re-applies the file at every start and its own Traefik manifest sets neither replicas nor
  affinity, so both survive restarts and upgrades. The k3d HA cluster in CI installs this same
  file (`deploy/k3d/cluster-ha.yaml`). On another distribution, run your ingress controller with
  two or more copies on different nodes.

  **NodeLocal DNSCache: a DNS cache on every node (D-163).** Two CoreDNS copies keep names
  resolving, but when a node is lost its copy stays behind the kube-dns Service until the node
  goes NotReady (about 20 s). Lookups that land on it time out meanwhile. Valkey's sentinels
  resolve synchronously, so they stall long enough to enter TILT, a fixed 30 s pause before they
  may fail over: failover took about 50 s (Cluster runs 43153098860, 43157246881). A cache on
  every node answers SupportX's names from memory and sends misses to CoreDNS over TCP, which
  fails fast on a dead copy; failover then takes about 15 s and the node-loss tests allow 60 s
  and fail on any TILT. After `cluster-dns-ha.sh`, and after every k3s upgrade:

  ```
  bash deploy/k3s/node-local-dns.sh   # waits for a ready cache on every node and a lookup through it
  ```

  It runs in transparent mode: the cache takes the kube-dns address on each node, so pods keep
  their DNS settings and no k3s or kubelet flag changes. That needs kube-proxy in iptables mode,
  k3s's default (the script refuses ipvs mode, and the preflight warns). All of k3s's own
  CoreDNS settings still decide every answer: misses go to CoreDNS through a second Service,
  `kube-dns-upstream`. The image (`registry.k8s.io/dns/k8s-dns-node-cache`, Apache-2.0) is
  pinned by digest in `values.yaml` (`images.nodeLocalDns`), so the air-gapped mirror carries
  it; `IMAGE_REGISTRY=<mirror>` points the script at the mirror. On a clean stop the cache
  removes its rules and pods reach CoreDNS directly. A crashed cache leaves its rules until the
  kubelet restarts it, within seconds, and that node's lookups fail meanwhile. On another
  distribution, use its NodeLocal DNSCache add-on (most managed clusters offer one).
  The cache runs on the node's own network: it listens on port 53 (UDP and TCP) of
  169.254.20.10 and the kube-dns address, its health check on 169.254.20.10:8080, and its
  Prometheus metrics on port **9253 of every node address**. A host firewall must let the API
  server (for the script's check) and your Prometheus reach 9253 from inside the cluster
  network only.
  With the egress allow-list on, pods reach the cache from their node's network, not CoreDNS's
  pods: `values-ha.yaml` lists its addresses (`networkPolicies.egress.dnsAddresses`:
  169.254.20.10 and k3s's default kube-dns address 10.43.0.10). If your kube-dns address
  differs, list yours. The script says so, and the preflight checks.

  **Preflight.** `deploy/k3s/ha-preflight.sh` checks a cluster for the HA profile, read-only: three
  or more schedulable nodes, cluster DNS ready on two or more nodes, the CloudNativePG operator
  ready on two or more nodes, Traefik ready on two or more nodes, NodeLocal DNSCache ready on every
  schedulable node and kube-proxy not in ipvs mode. Once SupportX is installed in
  `SUPPORTX_NAMESPACE` (default `supportx`) it also checks the release: NATS servers and PostgreSQL
  instances each on distinct nodes, the fast-eviction tolerations on the fan-out and index workers,
  with the egress allow-list on the cache's addresses in it, and the bundled SeaweedFS when it
  runs: three masters on distinct nodes, volume servers on two distinct nodes or more, and a
  default replication of `001` or `002` (read from the master pods' own arguments); the
  single-copy SeaweedFS under HA is a warning. External object storage is skipped. Each unmet
  requirement prints a WARNING and how to fix it (exit 0; `HA_PREFLIGHT_STRICT=1` fails on any
  warning, as `make cluster-up-ha` does before the install and `make cluster-ha-preflight` after
  it). Run it before the install, after it, and after any cluster upgrade. `helm install` with
  `values-ha.yaml` also warns in its notes when `kube-system/coredns` runs one copy.

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

## Front load balancer (HA installs)

In an HA install on k3s, every node answers on the ingress ports (80/443): k3s's ServiceLB
forwards each node's port to the Traefik Service, and inside the cluster kube-proxy only routes
to Traefik copies that are Ready, on any node. The one place a lost or just-rejoined node can
still drop requests is **in front of the cluster**: a load balancer (or DNS round robin) that
keeps sending to a node that is down, or that has just come back and whose forwarding rules are
still syncing (a few seconds after k3s starts on it).

So the external load balancer in front of the nodes **must health-check every node's ingress
port** and stop sending to a node that fails, for example:

- a TCP check on each node's port 443 (or 80) every 2-5 s, marking a node down after 2 failures
  and up again after 2 successes;
- or, better, an HTTP check through the ingress to `https://<your host>/api/v1/health` with the
  `Host` header set (expects 200), so a node whose Traefik or routing is not ready is skipped.

DNS round robin without health checks is not enough for HA: clients keep a dead node's address
until their cache expires. `deploy/k3s/ha-preflight.sh` prints this as a reminder; it cannot see
your load balancer. In CI, k3d's own front proxy does not health-check, so the HA tests allow a
node that just rejoined up to 30 s before the session must write again, and print how long it
took (`write_after_return`, deploy/k3d/ha-lib.sh).

## Transport security

What is encrypted on each hop, per profile (audit row 5). "Verified" means the client checks the
server's certificate against a known CA and the host name it dialled.

| Hop | dev (k3d) | single-node | HA |
|---|---|---|---|
| Browser to gateway | plain http (local only) | **HTTPS**, HTTP answers 301 to https | **HTTPS**, HTTP answers 301 to https |
| App, Centrifugo to Valkey (servers and sentinels) | plain (bundled single Valkey) | plain (bundled single Valkey) | **TLS only, verified** (internal CA) |
| App to NATS; NATS server to server (routes) | plain | plain (one server) | **TLS, verified** (internal CA); routes mutual TLS |
| App, workers, migrate Job to PostgreSQL (through PgBouncer, or direct) | encrypted, not verified (asyncpg's default) | encrypted, not verified (until the HA run proves verification) | **verify-full** (CloudNativePG's CA) |
| PgBouncer to PostgreSQL | TLS, CA checked (CloudNativePG's own) | same | same |
| Keycloak, Temporal to PostgreSQL | as their defaults (not changed here) | same | same |

### Browser to gateway (routing.tls)

On by default in every profile but `values-dev.yaml`. The Gateway gets two listeners: HTTPS
(`routing.gateway.tlsListenerName`, Traefik's websecure entrypoint 8443) carrying every route, and
plain HTTP (`listenerName`, 8000) whose only route is a `RequestRedirect` to https with status
301. `routing.tls.redirectHttp: false` drops the HTTP listener altogether. The certificate:

- **Your own (on-prem):** create a `kubernetes.io/tls` Secret in the release namespace
  (`kubectl -n supportx create secret tls supportx-tls --cert=fullchain.pem --key=key.pem`) and
  set `routing.tls.secretName=supportx-tls`. The older `routing.gateway.tlsSecret` still works.
  Renewing it is replacing the Secret; Traefik picks the new one up by itself.
- **From cert-manager:** set `routing.tls.issuerRef` (`{name: ..., kind: ClusterIssuer}`); the
  chart asks for a Certificate for `routing.hostnames` (or `publicUrl`'s host) in
  `<release>-tls` (or `routing.tls.secretName`), and cert-manager renews it.

The chart refuses TLS without either, and TLS with an `http://` `publicUrl`. Where a load
balancer in front already terminates TLS, set `routing.tls.enabled: false` and keep `publicUrl`
`https://`. `routing.gateway.protocol` is gone: the chart refuses it and names
`routing.tls.enabled` instead.

**Ingress mode** serves the same Secret, and with TLS on it never serves the app over plain HTTP,
since a first visit could otherwise sign in over http before HSTS applies:

- `className: traefik`: the routes are on the `websecure` entry point only, so plain HTTP has
  no route. For a 301 as well, turn on Traefik's own entry-point redirect
  (`ports.web.redirections.entryPoint: {to: websecure, scheme: https}` in its values).
- `className: nginx`: `ssl-redirect` and `force-ssl-redirect`, so plain HTTP answers 308 to
  https.
- Any other class: the chart refuses to render until you make that controller redirect or
  refuse http yourself and set `routing.ingress.enforcesHttps: true`.

### PostgreSQL (postgresql.tls.verify)

CloudNativePG always serves TLS, with its own CA (Secret `<release>-pg-ca`, keys `ca.crt` and
`ca.key`), and its PgBouncer connects to PostgreSQL with that CA checked. What `postgresql.tls`
adds is the app's side: with `verify: true` the API, the workers and the migrate Job connect
sslmode verify-full (`SUPPORTX_DATABASE_SSL_ROOT_CERT`, the chain checked against that CA and the
host name against the certificate). They reach PostgreSQL through the pooler
(`<release>-pg-pooler`), and CloudNativePG's PgBouncer serves the cluster's server certificate, so
the chart adds the pooler's names to it (`spec.certificates.serverAltDNSNames`); the relay and the
index worker go straight to `<release>-pg-rw`, which the operator's certificate already names.
Pods mount `ca.crt` alone.

On in `values.yaml` and `values-ha.yaml`. `values-single-node.yaml` and `values-dev.yaml` keep
it off for now (encrypted, unchecked, as before): it is proven on the HA cluster first, then
turned on for single-node.

**External database:** set `postgresql.mode: external`, `postgresql.tls.verify: true` and
`postgresql.external.caSecret` to a Secret in the release namespace holding your server's CA as
`ca.crt` (`kubectl -n supportx create secret generic db-ca --from-file=ca.crt=root.pem`); the
host names in `postgresql.external.host` and `poolerHost` must be in the server's (and your
pooler's) certificate. The chart refuses verification without that Secret; a server without TLS
needs `postgresql.tls.verify: false`, knowingly.

### The internal CA (internalTls)

The in-cluster servers that speak TLS get their certificates from cert-manager (a prerequisite of
these profiles, like the CloudNativePG operator; `deploy/k3d/prereqs.sh` installs it with
`BACKUP_PLUGIN=1`). By default the chart makes its own CA (`templates/internal-tls.yaml`): a
self-signed root, valid ten years, kept only in the Secret `<release>-internal-ca`, and an Issuer
`<release>-internal-ca` signing one-year server certificates that cert-manager renews 30 days
before they end. Pods mount that Secret's `ca.crt` alone, never its key.

**Your own PKI (on-prem):** set `internalTls.issuerRef` to a cert-manager Issuer or ClusterIssuer
of yours (a CA issuer on your intermediate, Vault, ...) and `internalTls.caSecret` to a Secret in
the release namespace whose `ca.crt` is the root it chains to. The chart then makes no CA of its
own. Internal TLS needs cert-manager (the chart creates its Certificate objects); a cluster
without it turns the internal TLS switches off and keeps only the NetworkPolicies between pods.

| Secret | Holds | Made by |
|---|---|---|
| `<release>-internal-ca` (or `internalTls.caSecret`) | the internal root (`ca.crt`; `tls.key` only for the chart's own) | cert-manager, or you |
| `<release>-valkey-tls` | every Valkey pod's server and sentinel certificate: `*.<release>-valkey-headless[.<ns>.svc[.cluster.local]]`, `localhost`, `127.0.0.1` | cert-manager |
| `supportx-nats-tls` (`nats.config.nats.tls.secretName`) | the NATS servers' certificate, for clients and routes: `<release>-nats[.<ns>[.svc[.cluster.local]]]`, `*.<release>-nats-headless[...]` | cert-manager |

### Valkey (valkeyHa.tls)

On in `values-ha.yaml`. Every server and sentinel listens on TLS only, on the usual ports
(6379, 26379; `port 0`, no plaintext listener), replication and the sentinels' own connections
included (`tls-replication yes`). Clients prove themselves with the password, so no client
certificate is asked for (`tls-auth-clients no`). Valkey rereads its certificate files every
`valkeyHa.tls.reloadIntervalSeconds` (an hour), so a renewal needs no restart. The API and the
workers connect with `valkeys://` and `SUPPORTX_VALKEY_TLS_CA_FILE` (the CA; the host name is
checked: the sentinels announce each server by its pod name, which the certificate lists), and
Centrifugo's engine with `tls` and `sentinel_tls`. The chart's scripts reach their own servers
through `vcli` (`templates/valkey-ha.yaml`, `common.sh`), which adds `--tls --cacert`; from a
shell in a pod: `. /scripts/common.sh; vcli -p 26379 SENTINEL masters`. The single-node and dev
profiles keep the bundled single Valkey, plaintext inside the namespace's NetworkPolicy.

### NATS (nats.config.nats.tls)

On in `values-ha.yaml`, for the clients and between the servers. The app connects with `tls://`
and `SUPPORTX_NATS_TLS_CA_FILE`; the host name checked is the URL's (`<release>-nats`, which the
certificate lists), also when the client reconnects to another server of the cluster. Routes are
always mutual TLS in NATS: each server presents the same certificate and checks its peers' against
the CA (`cluster.tls.merge.ca_file`, the `ca.crt` cert-manager writes beside the certificate; a
CA or Vault issuer of your own writes it too). The NATS chart reloads the certificate when
cert-manager renews it. The monitoring port 8222 (probes, the Prometheus exporter) stays plain
http inside the pod network. The certificate's Secret name is a plain value of the NATS chart, so
`values-ha.yaml` names it `supportx-nats-tls` for the release name `supportx`; another release
name sets `nats.config.nats.tls.secretName` and `nats.config.cluster.tls.secretName` to
`<release>-nats-tls` (the chart refuses the two differing).

## Client addresses behind the gateway

The API believes `X-Forwarded-For` only from `api.trustedProxies` (addresses or CIDRs; default
`10.42.0.0/16`, k3s's pod network, where Traefik runs). The client address it uses for rate limits
and the audit log is the last one in the header that isn't a trusted proxy, so a client can't
choose its own. Set it to your cluster's pod CIDR, or to your load balancer's addresses if one
sits in front of the gateway. If it doesn't match, every request seems to come from the gateway,
so per-address rate limits are shared by everyone.

## Rate limits without a signed-in person

Routes that nobody signs in for are limited per client address (the address above), each request
counted in Valkey (audit row 14, `ip_rate_limit` in `backend/app/shared/api/ratelimit.py`). An
IPv4 address counts on its own; an IPv6 address counts as its whole /64 network, because one
client holds a /64 and could pick a new address for every request:

| Route | Per address, per minute | Valkey down |
|---|---|---|
| `GET /api/v1/auth/login` | 60 | **refused:** 503 `sign_in_unavailable` |
| `GET /api/v1/auth/callback` | 60 | **refused:** 503 `sign_in_unavailable` |
| `GET /api/v1/public/branding`, `/{tenant}/login.css`, `/{tenant}/{image}` | 300 | allowed |
| `GET /api/v1/public/domain-check/{token}` | 30 | allowed |
| `POST /api/v1/public/action-links/peek`, `/use` | 120 (an outer cap; the links' own budgets stay) | allowed |

The budgets are wide on purpose: an office behind one NAT address signs many people in at once,
and a sign-in is one `/login` and one `/callback` (two of each with an MFA enrolment). They stop
scripted floods. Over a budget the API answers 429 `rate_limited` with `Retry-After`; a browser
is sent back to its app, which shows the message. A refused `/callback` goes back to the app its
sign-in started in (console, portal or the mobile app), read from the pending sign-in without
spending it; with Valkey down that cannot be read, so it goes to the console.

**The sign-in routes fail closed.** Every other route allows requests while Valkey is down (losing
rate limiting for a moment beats losing the API, ADR-020). A sign-in needs Valkey anyway (its
one-time state lives there), so letting it through unlimited buys nothing; it answers 503
`sign_in_unavailable` with `Retry-After: 2`, and the sign-in page says to try again in a minute.

## Egress allow-list (opt-in)

Ingress is always denied by default. Egress is open unless `networkPolicies.egress.enabled` is
true (WP-014b). With it on, pods may reach:
- **DNS and the namespace:** every pod may reach DNS (kube-dns, plus
  `networkPolicies.egress.dnsAddresses`, which `values-ha.yaml` sets for NodeLocal DNSCache) and
  the other pods of the namespace.
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
losing the cluster or its disks loses the backups too, and the chart warns about it. With the
replicated SeaweedFS it matters more: its filers' file tree lives in this same database, so a
lost database also makes the in-cluster backups unreadable until it is back. For
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
| Cluster › `ha-smoke` | nightly, on demand, PRs labelled `full-ci` | a four-node k3d cluster with `values-ha.yaml`. The bring-up gives CoreDNS two copies on different nodes and runs the HA preflight (strict). First the Valkey master is killed (the session survives, no split brain). Then the node with the promoted Valkey master is stopped (`make cluster-ha-valkey-node-loss`): Sentinel promotes again within 60 s, the session writes again, the old master returns as a replica. The same again in the worst case, forced by the test (`make cluster-ha-valkey-node-loss-dns`): the stopped node holds the Valkey master and a CoreDNS copy. Then the agent with PostgreSQL's primary is stopped (`make cluster-ha-node-loss`): a standby is promoted, the session writes again, and the node rejoins as a standby. Then the node with SeaweedFS's raft leader and a volume server is stopped (`make cluster-ha-objects-node-loss`, D-166; the test hands the leadership to an agent without the database primary or the Valkey master): 20 attachments uploaded before still download intact and 5 new ones upload within 60 s, and after the return `volume.fix.replication` brings every volume back to two copies. Then the k3s server restarts (`make cluster-ha-dns-restart`): CoreDNS keeps two copies on two nodes and its anti-affinity |

## Runbooks

| Runbook | What for |
|---|---|
| [restore.md](runbooks/restore.md) | Restore the database to a chosen moment from its backups (WP-014b) |
| [staging-laptop.md](runbooks/staging-laptop.md) | Staging on a spare laptop: OS, k3s, first install, the nightly pull-based upgrade (D-169) |

## Troubleshooting

- Pods stuck in `Init`: `kubectl -n supportx logs job/supportx-migrate-<revision>`.
- `helm upgrade` fails on `--wait`: `kubectl -n supportx get pods` and `kubectl -n supportx
  describe pod <pod>`; Keycloak needs about a minute to build itself at start.
- After changing the dev realm file: Keycloak imports it only when the realm does not exist yet;
  recreate the cluster (`make cluster-down cluster-up deploy-dev`).
