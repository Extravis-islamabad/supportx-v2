# ADR-025: Deployment on Kubernetes: one Helm chart, CloudNativePG, Gateway API, migrate Job per revision

- **Status:** Accepted
- **Date:** 2026-10-24
- **Source:** WP-014; architecture.md §4.1, §5, §11.4, §14, §15; ADR-001, ADR-005, ADR-006,
  ADR-009, ADR-012, ADR-018, ADR-019, ADR-023; D-003, D-009, D-016, D-017, D-037, D-038
- **Owner:** Haider (Product Owner)

## Context

architecture.md §14.3 asks for one Helm chart for every deployment size, the same build in SaaS
and on-prem, migrations that follow expand/contract and checks before upgrades. WP-014 builds the
first part (images, the chart for the dev and single-node profiles, a local k3d cluster, CI); HA,
backups, the air-gapped bundle and SaaS follow in WP-014b/c/d (D-038). Several choices had to be
made that every later deployment work package builds on.

## Decision

1. **One umbrella chart** `deploy/helm/supportx` for every profile; profiles are values files
   (`values-dev.yaml`, `values-single-node.yaml`; HA, SaaS and air-gapped later). Our own
   deployables are templates: API (with the BFF, D-009), relay, consumers, fan-out, web, Centrifugo,
   Keycloak, the migrate Job. NATS and Valkey come from their official charts (subcharts, pinned
   in Chart.lock). PostgreSQL comes from the **CloudNativePG** operator (a cluster-wide
   prerequisite), with its PgBouncer **Pooler** in transaction mode in front (D1/D-038).
2. **Two images of our own**: `supportx-backend` (one image; the command picks the role) and
   `supportx-web` (nginx-unprivileged serving the console at `/` and the portal at `/portal/`).
   Plain CPython, labelled **INTERNAL/DEV** until the Nuitka build exists (ADR-009, D-038).
3. **One host with paths (D3/D-038)**: `/api` → API, `/connection` and `/emulation` → Centrifugo,
   `/auth` → Keycloak (`KC_HTTP_RELATIVE_PATH`; `/auth/admin` not routed publicly except in dev),
   `/portal/` and `/` → web. Same-origin as the Vite dev proxy, so the BFF cookie and CSRF model
   are unchanged. The BFF builds its callback and Origin check from the UI's **origin**; after
   login the browser returns to its own path, or to the UI's base path (`/portal/`).
4. **Gateway API with Traefik** (bundled with k3s) by default; a plain **Ingress** as the supported
   fallback for clusters that bring their own load balancer (D2/D-038). Hostnames are a list, ready
   for per-tenant hosts (WP-017).
5. **Keycloak's back channel stays inside the cluster.** The API discovers the realm at
   `SUPPORTX_OIDC_INTERNAL_URL` (Keycloak with a dynamic back channel) and moves every endpoint it
   calls itself (token, keys, logout) to that base; browsers and the ID-token issuer check keep
   the public URL.
6. **Migrations: one Job per Helm revision, not a Helm hook.** A pre-install hook would run before
   the in-cluster PostgreSQL exists and a post-install hook deadlocks with `--wait`. The Job creates
   roles and the database from `tooling/sql` (single source with the dev stack and CI), lets the
   CloudNativePG pooler look up our roles, then runs Alembic under an advisory lock. The API and
   workers of that revision wait in an init container (`tooling/wait_for_job`, RBAC: `get` jobs).
   A database migrated by a newer release is left alone, so `helm rollback` only moves images back;
   nothing is ever downgraded (expand/contract, CLAUDE.md rule h).
7. **Probes and metrics**: the API keeps `/api/v1/health` and `/api/v1/ready`; every SupportX
   process serves `/metrics` on an internal port (9464) and the workers also `/healthz` and
   `/readyz` there (`app/core/ops_server.py`, Prometheus exporter of D-023). PodMonitors when the
   Prometheus Operator is present, `prometheus.io/*` annotations otherwise.
8. **Scaling**: API, web, consumers and relay can run several copies; the realtime fan-out stays
   at **one** (ADR-023: in-memory merge windows and rate limits) with a surge-first rollout.
9. **Security baseline**: restricted pod security for every container we control (non-root,
   read-only root filesystem, no capabilities, seccomp), ingress NetworkPolicies (deny by default),
   secrets only by reference (`deploy/scripts/secrets.sh` creates random values and never
   overwrites), k3s with secrets encryption.
10. **Local cluster**: k3d with **k3s v1.36.5-k3s1** (D9/D-038; same as the appliance), the public
    URL `http://supportx.localhost:8080`. CI lints and validates the chart on every PR, installs it
    on k3d with a smoke test when deployment files change, and runs every Playwright journey on k3d
    nightly. Images are built but not pushed while the repo is public (D6/D-038).

## Consequences

- **Positive:** the same chart, images and migration path for every profile; a rollback never
  touches the schema; the e2e suite runs unchanged against the cluster; operators of a customer
  cluster can bring their own Gateway, Ingress, database or Prometheus.
- **Negative:** CloudNativePG is a cluster-wide prerequisite; a `user_search` function exists in
  the SupportX database on Kubernetes only (the pooler's documented lookup); Keycloak builds itself
  at every start until an optimized image exists (WP-014b/WP-017).
- **Negative:** dev images share one tag (`dev`); `make deploy-dev` rolls pods with an annotation.

## Notes

Dev-only pieces are explicit in `values-dev.yaml`: the dev realm with demo users, seeded demo
tenants, Keycloak's admin API on the public host, and a NodePort to PostgreSQL bound to the
host's loopback for the e2e suite's fixture tools (a `kubectl port-forward` exits on the first
reset connection, which made the suite flaky).
