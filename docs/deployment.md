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

## Secrets

The chart only references Secrets. `deploy/scripts/secrets.sh <namespace>` creates them with random
hex values and never overwrites an existing one (its passwords are already inside the databases).

| Secret | Keys |
|---|---|
| `supportx-app` | `app-db-password`, `migrator-db-password`, `relay-db-password`, `session-secret`, `centrifugo-token-secret`, `centrifugo-api-key`, `oidc-console-secret`, `oidc-portal-secret`, `keycloak-admin-password`, `nats-password`, `valkey-password` |
| `supportx-db-keycloak` (basic-auth) | `username` = `keycloak`, `password` |
| `supportx-pg-superuser` | created by CloudNativePG; used only by the migrate Job |

## Profiles

- `values-dev.yaml`: k3d, plain http on `supportx.localhost:8080`, the dev realm with demo users,
  demo tenants seeded, Keycloak admin API public, a NodePort to PostgreSQL on the host's loopback
  (127.0.0.1:25433) for the e2e suite's tools. **Never** use it anywhere else.
- `values-single-node.yaml`: one k3s VM (8 vCPU / 32 GB / 500 GB), production profile, HTTPS on
  Traefik's websecure listener with your certificate Secret, the base realm (no users). **Internal
  evaluation only** until backups (WP-014b) and Nuitka images exist.

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

## Troubleshooting

- Pods stuck in `Init`: `kubectl -n supportx logs job/supportx-migrate-<revision>`.
- `helm upgrade` fails on `--wait`: `kubectl -n supportx get pods` and `kubectl -n supportx
  describe pod <pod>`; Keycloak needs about a minute to build itself at start.
- After changing the dev realm file: Keycloak imports it only when the realm does not exist yet;
  recreate the cluster (`make cluster-down cluster-up deploy-dev`).
