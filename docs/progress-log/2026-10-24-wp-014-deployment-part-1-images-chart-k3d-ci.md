### 2026-10-24 — WP-014 deployment part 1 (images, chart, k3d, CI)
- Decisions: D-037 (deployment components), D-038 (plan decisions D1-D13; D-004 pgBackRest
  superseded by CloudNativePG backups), ADR-025 (deployment), ADR-012 now Accepted (SeaweedFS
  on-prem, permissive on-prem monitoring).
- Images (`deploy/images`): `supportx-backend` (one image; api / relay / consumers / fanout /
  migrate by command; python 3.12.15-slim-trixie; non-root 10001; read-only root works) and
  `supportx-web` (nginx-unprivileged 1.30.6, console `/`, portal `/portal/`, CSP). Both labelled
  INTERNAL/DEV (D-038). Sizes on arm64: backend 340 MB, web 99 MB. Trivy: no fixable HIGH/CRITICAL
  (web base patched with `apk upgrade` for brotli CVE-2026-111497).
- Chart `deploy/helm/supportx` (ADR-025): API, workers, web, Centrifugo, Keycloak (realm import:
  dev or base), CloudNativePG Cluster + Pooler, NATS and Valkey subcharts (auth on, hardened),
  migrate Job per revision + wait-for-job init containers (RBAC: get jobs), Gateway API routes or
  Ingress, NetworkPolicies (deny by default; verified blocking on k3s), PodMonitor or annotations,
  `helm test` smoke pod, NOTES. Profiles `values-dev.yaml`, `values-single-node.yaml`.
- Backend: `/metrics` + worker `/healthz` `/readyz` on 9464 (`app/core/ops_server.py`, Prometheus
  exporter of D-023 now installed); API HTTP metrics; `SUPPORTX_OIDC_INTERNAL_URL` (back channel
  inside the cluster; token, keys and logout always internal); BFF callback and Origin check from
  the UI origin (portal under `/portal`); readiness probes Keycloak internally;
  `tooling/deploy_migrate.py` (bootstrap from tooling/sql, CNPG pooler lookup, Alembic under an
  advisory lock, newer-schema skip); `tooling/wait_for_job.py`; `tooling/keycloak_realm.py`
  (base realm without demo users/orgs, checked in `make lint`). The dev realm moved into the chart
  (`files/keycloak/dev`), shared with Compose, URLs as placeholders. Portal builds with base
  `/portal/`.
- Local: `make cluster-up`, `deploy-dev`, `cluster-test`, `cluster-e2e`, `chart-lint`,
  `cluster-down` (asks); k3d `supportx` with k3s v1.36.5-k3s1, Traefik 3.7.13 with the Gateway
  provider, CloudNativePG 1.30.1. e2e helpers take cluster URLs and secrets from env.
- CI: `ci.yml` › `chart` (every PR); `cluster.yml` (images + Trivy + SBOM, k3d smoke on deployment
  changes; Playwright on k3d nightly); Trivy fs scan uses `.trivyignore.yaml` (one documented false
  positive). No images are pushed (D-038 item 6); cosign signing starts with WP-014c.
- Found on the way: Keycloak keeps the logout endpoint public even with a dynamic back channel
  (logout failed until every back-channel call was moved internal); `kubectl port-forward` exits on
  the first reset connection (dev NodePort instead); a pre-install Helm hook cannot migrate an
  in-cluster database (Job per revision instead); MinIO and Mailpit are not deployed (no code
  uses object storage or mail yet). The layouts journey was flaky on the cluster: a click on
  "Appearance" landing during the re-render after a layout or language change is lost (the popover
  stays open), and the test's clean-up used an Arabic label, so one failure left the suite user on
  the side bar for later runs. The test now retries closing and resets by position.
- Tests: backend unit + DB (ops server, deploy migrate on a throwaway database, wait-for-job,
  realm, OIDC internal URL and back channel, BFF URLs with a path, readiness); chart lint for 5
  profile variants (kubeconform: all valid); `helm test` passes; Playwright 24/24 on k3d.
- Follow-ups: the Appearance popover should close on the first click after a layout/language
  change (UI); the upstream Valkey chart's own `helm test` pod is refused by our NetworkPolicy and
  reports "auth enforced" for the wrong reason (WP-014b); kubeconform was installed on the dev Mac
  with Homebrew (CI downloads a pinned, checksum-verified binary).
- Dev data: Compose stack untouched except the Keycloak realm file's new location (the existing
  realm in the dev database is not re-imported). Three throwaway `supportx_test_*` databases left
  by a failing test run of this session were dropped. The k3d cluster is new and holds only
  seeded demo data.
