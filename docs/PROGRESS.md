# SupportX v2 — Progress

## Current status

- **Stage:** 0 — Foundation (architecture.md §17). In progress: 14 of 16 work packages done
  (WP-014 = part 1 of 4; 014b-d are planned below).
- **Last completed:** WP-014 (deployment part 1: images, Helm chart for dev and single-node, k3d,
  CI), 2026-10-24. Before it: WP-012b.
- **Next work package:** WP-015 (clickable prototype) or WP-013 (licence core; Rust 1.99.1 is now
  installed). WP-014b (HA + backups) is unblocked as well.
- **Working mode:** single agent (parallel mode ended 2026-10-23; a stale WP-010 worktree or
  branch, if any, is left for the product owner).
- **Blockers:** None. Homebrew, k3d 5.9.0, kubectl 1.37.1, Helm 4.3.1 and Rust 1.99.1 are installed
  on the dev Mac; Docker Desktop has 12 GB (D-038).
- **Repository:** https://github.com/devhat-pm/supportx-v2, **temporarily PUBLIC** (D-018) until
  the account billing problem is fixed; then set back to private (D-015).

### Open questions (awaiting product owner)

None.

Resolved 2026-10-24: rich-text editor = Tiptap with server-side sanitising, built with the
first incidents work package (D-036, timing moved by D-040); parity phase 1 questions answered
(D-039 to D-050); k3d installed through Homebrew by the product owner; WP-014 plan
decisions D1-D13 (D-038).

### Open items

1. **GitHub billing (owner action, expected by 2026-10-24):** Actions jobs on the private repo are
   refused ("recent account payments have failed or your spending limit needs to be increased").
   Fix billing, then `gh repo edit devhat-pm/supportx-v2 --visibility private
   --accept-visibility-change-consequences` and re-run CI to confirm it starts (D-018).
2. **Branch protection on a private repo needs GitHub Pro/Team.** `main` protection (required
   checks backend, frontend, pre-commit; strict; no force pushes or deletions) is active while the
   repo is public. GitHub keeps the rule but stops enforcing it once the repo is private on the
   Free plan. Upgrade to Pro (or move to an Extravis org on Team) to keep it, or accept
   unprotected `main`.
3. **Dependabot PR #3 (jsdom 27 → 30, test helper)** awaits review; majors for TypeScript, Ant
   Design and React are ignored per D-014, ADR-002 and CLAUDE.md §3 (PRs #2, #4, #5, #6 closed).

Resolved 2026-10-22 — see `docs/DECISIONS.md`: monitoring scope (D-001), roadmap authority
(D-002), local cluster tool (D-003), stack additions (D-004), v1 migration (D-005), Urdu (D-006),
ADR owners (D-007), prototype design input (D-008), BFF location (D-009), Keycloak tenancy (D-010),
Redis licence (D-011); helper libraries, i18next, TypeScript version (D-012..D-014); GitHub
private repo + Actions (D-015), S3-only object storage (D-016), Temporal without auto-setup (D-017).

## Stage 0: Foundation — work packages

Stage 0 outcomes (§17): ADRs signed off; repo, CI/CD, environments; identity, tenancy and RLS;
outbox and event bus; realtime pipeline; design system; licence core prototype; clickable prototype
of console and portal. Each WP is sized for one Claude Code session. Status: `[ ]` todo,
`[~]` in progress, `[x]` done.

### [x] WP-001 — Monorepo skeleton and dev tooling (done 2026-10-22)
- **Goal:** Empty-but-real monorepo matching CLAUDE.md §4, with all quality tools wired.
- **Scope:** `backend/` uv project (Python 3.12, ruff, mypy strict, pytest, import-linter with a
  module-boundary contract, `GET /api/v1/health`); `frontend/` pnpm workspace with empty `apps/console`,
  `apps/portal` and `packages/*` stubs (tsc strict, ESLint, Prettier, Vitest); `deploy/`,
  `licence-core/` placeholders with READMEs; root task runner (Makefile) with `lint`, `typecheck`,
  `test`, `format` targets.
- **Acceptance:** `make lint typecheck test` passes on a clean clone for both backend and frontend
  (with one trivial test each); Python pinned to 3.12 via uv; pnpm via corepack; no dependency
  outside CLAUDE.md §3.
- **Depends on:** —

### [x] WP-002 — Local dev stack (Docker Compose) (done 2026-10-22)
- **Goal:** One command brings up every backing service for local development.
- **Scope:** `deploy/compose/docker-compose.yml` for PostgreSQL 16 (+ pgvector), PgBouncer, NATS
  JetStream, Temporal (+ UI), Centrifugo, Keycloak, Valkey, OpenSearch, MinIO, Mailpit, ClickHouse,
  ClamAV; profiles core (default) and full; named volumes prefixed `supportx_dev_`; health checks;
  `make dev-init/dev-up/dev-up-full/dev-down/dev-ps/dev-logs/dev-check/dev-reset` (`dev-down` never
  removes volumes; `dev-reset` asks for "yes"); `.env.example`; PostgreSQL roles `supportx_app`
  (no BYPASSRLS) and `supportx_migrator`.
- **Acceptance:** `make dev-up` reaches all-healthy on the dev Mac; `make dev-check` connects to each
  service; ports and credentials documented in `docs/dev-setup.md`.
- **Depends on:** WP-001

### [x] WP-003 — CI pipeline and quality gates (done 2026-10-22)
- **Goal:** Every push runs the §16.2 gates that are meaningful at this stage.
- **Scope:** CI workflow for backend (ruff, mypy, import-linter, pytest) and frontend (tsc, ESLint,
  Prettier check, Vitest); secret scanning; Trivy filesystem scan; caching for uv and pnpm;
  conventional-commit check on PR titles.
- **Acceptance:** Pipeline green on main; a deliberately failing lint/type/test is shown to fail
  the build (on a throwaway branch).
- **Depends on:** WP-001; CI platform: GitHub Actions on a private GitHub repo (D-015)

### [x] WP-004 — Backend application core (done 2026-10-23)
- **Goal:** Production-shaped FastAPI app with cross-cutting concerns, no business modules yet.
- **Scope:** `app/main.py` app factory; `core/config` (env-driven; pydantic-settings pending approval); structured
  JSON logging with trace ID and tenant ID; RFC 9457 error model with machine codes; liveness and
  readiness endpoints; OpenTelemetry instrumentation hooks; `/api/v1` router; OpenAPI 3.1 export
  script.
- **Acceptance:** App starts against the dev stack; health endpoints tested; an unhandled exception
  returns a problem-details body with no stack trace; OpenAPI JSON exported to a file in CI.
- **Depends on:** WP-001

### [x] WP-005 — Data layer, RLS and tenancy bootstrap (done 2026-10-23)
- **Goal:** Non-negotiable rule (a) proven in code and tests.
- **Scope:** Async SQLAlchemy engine/session; Alembic setup; base model mixin (UUIDv7 PK,
  `tenant_id`, timestamps, audit-by columns, `version`, `deleted_at`); RLS policy helper used by
  migrations; separate migration-owner and app roles (app role without BYPASSRLS); tenant context
  (`SET LOCAL app.tenant_id`) per transaction; `organization` module with `tenants` and `sites`;
  per-tenant display-ID sequence table; Testcontainers fixtures.
- **Acceptance:** Tests prove tenant A cannot select/insert/update/delete tenant B rows, and that a
  query without tenant context returns zero rows; migrations upgrade and downgrade cleanly on a
  fresh Testcontainers database.
- **Depends on:** WP-002, WP-004

### [x] WP-006 — Identity and authentication (done 2026-10-23)
- **Goal:** Users log in via Keycloak; API knows who and which tenant.
- **Scope:** Keycloak dev realm import (one shared realm, tenants as Keycloak Organizations —
  D-010; dedicated-realm path stubbed); BFF login flow in `app/modules/identity_access/bff` (D-009;
  OIDC Code + PKCE, HttpOnly session cookie, tokens server-side in Valkey); `identity_access` module (users,
  groups, roles minimal); permission policy layer skeleton (module/action check) used by services;
  API-key auth stub for integrations.
- **Acceptance:** Integration test logs a user in against Keycloak (Testcontainers or dev stack),
  calls a protected endpoint, and is rejected without a session; tokens never appear in browser-
  readable responses; tenant resolved from the session drives RLS.
- **Depends on:** WP-005

### [x] WP-007 — Transactional outbox and event bus (done 2026-10-23)
- **Goal:** Non-negotiable rule (b) proven end to end.
- **Scope:** `shared/events` envelope (event ID, type, tenant, aggregate, version, occurred_at,
  payload); outbox table + writer used inside service transactions; relay worker publishing to NATS
  JetStream with per-tenant subjects; idempotent consumer base class recording processed IDs;
  stream/consumer provisioning.
- **Acceptance:** Tests show an event is published for a committed change, none for a rolled-back
  change, and redelivery is processed once; relay survives restart without loss.
- **Depends on:** WP-005

### [x] WP-008 — API conventions (done 2026-10-23)
- **Goal:** Shared building blocks every module will use.
- **Scope:** Optimistic concurrency (version + ETag/If-Match, 409 with changed fields);
  Idempotency-Key handling on POST (PostgreSQL-backed, ADR-020; planned as Valkey-backed);
  cursor pagination; filter DSL v0 (field, op, value, AND/OR groups) compiled to SQLAlchemy;
  OpenAPI diff check script. Also: sorting, rate limiting (Valkey), deprecation headers.
- **Acceptance:** Unit and integration tests for each block; a stale-version update returns 409; a
  repeated POST with the same key creates one record.
- **Depends on:** WP-004, WP-005

### [x] WP-009 — Entitlement interface (done 2026-10-23)
- **Goal:** Non-negotiable rule (f) has a single, real seam.
- **Scope:** `licensing` module exposing `has_feature`, `check_limit`, `remaining`; provider
  protocol with a SaaS-plan provider stub and a dev provider (config-driven); FastAPI dependency
  for feature gates; problem-details error code for "not entitled"; import-linter contract that
  only `licensing` touches providers.
- **Acceptance:** Tests show gating works identically with both providers; a CI grep/lint fails on
  deployment-mode checks in module code.
- **Depends on:** WP-004

### [x] WP-010 — Frontend foundation and design system (done 2026-10-23)
- **Goal:** Shared frontend packages that enforce rule (d) from day one.
- **Scope:** `packages/ui` (AntD 5 theme tokens, light/dark/high-contrast, RTL switch, app shell);
  `packages/labels` migrated to i18next + react-i18next (D-013; dictionary, `humanize()` with
  missing-label warning, plurals, interpolation, en/ar/ur resources);
  custom ESLint no-raw-enum rule; `packages/api-client` generated from the WP-004 OpenAPI export
  with TanStack Query hooks; console and portal apps boot with login redirect to the BFF.
- **Acceptance:** Both apps build and render in en and ar (RTL); ESLint rule test cases pass;
  regenerating the API client after a backend schema change breaks `tsc` where expected.
- **Depends on:** WP-001, WP-004

### [x] WP-011 — Realtime pipeline end to end (done 2026-10-23)
- **Goal:** Non-negotiable rule (c) proven: commit → screen in under 1 s.
- **Scope:** Connection and subscription token endpoints with permission checks (§8.2); fan-out
  consumer NATS → Centrifugo using §8.1 channel names and minimal payloads; `packages/realtime`
  (Centrifugo client, channel hooks, TanStack Query cache patching, reconnect recovery, fallback
  indicator).
- **Acceptance:** Automated test: a change committed via the API reaches a subscribed browser
  client and patches the cache; an unauthorised subscription is refused; reconnect replays missed
  messages.
- **Depends on:** WP-006, WP-007, WP-010

### [x] WP-012 — Walking skeleton: one demo entity through every rule (done 2026-10-23)
- **Goal:** A reference implementation future modules copy.
- **Scope:** A minimal throwaway-safe entity (e.g. `announcements` in a sandbox module) with the full
  four-layer shape: RLS table, CRUD API with version/ETag and idempotency, outbox events, entitlement
  gate, labels for its statuses, live list and record view in the console, Playwright e2e.
- **Acceptance:** Playwright test with two browser contexts: an edit in one appears live in the
  other without refresh; stale edit shows a 409 conflict message; tenant B never sees tenant A's
  records; no raw codes on screen.
- **Depends on:** WP-006, WP-007, WP-008, WP-009, WP-011, WP-016 (D-025)
- **Built (D-032..D-034, ADR-024):** module `announcements` (not a sandbox: a real, low-risk
  feature), template checklist in `docs/architecture/module-template.md`.

### [ ] WP-013 — Licence core prototype (Rust)
- **Goal:** De-risk ADR-009 early.
- **Scope:** `licence-core/` Rust crate: Ed25519 signature verify of the §13.3 licence JSON,
  fingerprint v1 (Linux sources in §13.4, 3-of-5 match), clock-rollback check; PyO3 bindings; an
  on-prem provider for the WP-009 entitlement interface; dev-only signing tool with a test key.
- **Acceptance:** Rust and Python tests: valid licence accepted, any edited field rejected,
  fingerprint tolerance works (2 changed components pass, 3 fail); no production key in the repo.
- **Depends on:** WP-009 (Rust/PyO3 approved by D-004; Rust toolchain must be installed)

### [x] WP-014 — Deployment part 1: images, Helm chart (dev, single-node), k3d, CI (done 2026-10-24)
- **Goal:** The same build runs on Kubernetes from day one (§14.3). Plan approved 2026-10-24 with
  decisions D1-D13 (D-038); split into 014 / 014b / 014c / 014d.
- **Scope:** Container images for API and workers (the BFF ships inside the API, D-009) and the web
  apps; one Helm chart with `values-dev` and `values-single-node`; local k3d cluster (k3s
  v1.36.5); readiness/liveness wired; in-cluster PostgreSQL (CloudNativePG), NATS, Valkey,
  Centrifugo, Keycloak; migrations on deploy; metrics endpoints; CI chart lint on every PR, k3d
  install + smoke test on deployment changes, Playwright on k3d nightly.
- **Acceptance:** `make cluster-up && make deploy-dev` installs the chart and the walking-skeleton
  e2e test passes against the cluster. **Met**: all 24 Playwright journeys pass on k3d.
- **Depends on:** WP-002, WP-004, WP-012
- **Note (D-017):** Temporal is deployed without `auto-setup`; the `admin-tools` schema Job comes
  with the first workflow module (D-038 item 11).

### [ ] WP-014b — Deployment part 2: HA, backups, monitoring (planned, D-038)
- **Goal:** Standard HA profile and recoverable data.
- **Scope:** `values-ha.yaml` (3 nodes; CNPG 3 instances; NATS cluster with stream replicas 3;
  Valkey with Sentinel and app support; Centrifugo on the Valkey engine; Keycloak 2 with Infinispan;
  PDBs, HPA, anti-affinity); CloudNativePG built-in backups (Barman Cloud to S3-compatible
  storage, PITR) and a restore runbook incl. the NATS stream reset; SeaweedFS for on-prem object
  storage with rclone backups; pre-upgrade check Job (licence maintenance date, disk, fresh
  backup); upgrade test in CI; the permissive monitoring bundle (VictoriaMetrics, VictoriaLogs,
  Jaeger, Perses) with dashboards and alert rules; an optimized Keycloak image; egress
  NetworkPolicies; a way to block `/auth/admin` in Ingress mode.
- **Acceptance:** HA install survives the loss of any one node with the e2e suite passing; a
  restore drill (backup → new cluster → smoke test) passes in CI; alerts fire in a fault test.
- **Depends on:** WP-014

### [ ] WP-014c — Deployment part 3: release pipeline and air-gapped install (planned, D-038)
- **Goal:** Signed, verifiable releases a customer can install with no internet.
- **Scope:** multi-arch builds on native runners (amd64, arm64); push to GHCR as **private**
  packages only; cosign signing (password-protected key in GitHub secrets, moved to a KMS before
  the first customer release) and SBOM attestations; digest pinning and mirroring of third-party
  images; offline bundle (images, charts, k3s, checksums, signature) and `supportx-install`
  (verify / init / up / upgrade / check / backup-secrets / support-bundle); install test with
  egress blocked. **Requires the Nuitka build (WP-013 / ADR-009) before any customer bundle.**
- **Acceptance:** a bundle built in CI installs on a VM with no network and passes the smoke test;
  a tampered image or bundle is refused.
- **Depends on:** WP-014b, WP-013; repo private (D-015) before any image is pushed

### [ ] WP-014d — Deployment part 4: SaaS cell (planned, D-038; with WP-017)
- **Goal:** One region cell (§14.1) from the same chart.
- **Scope:** `values-saas.yaml`; External Secrets Operator; cert-manager with DNS-01 wildcard
  certificates; managed PostgreSQL option; admission-time signature verification; per-tenant
  hostnames (WP-017).
- **Acceptance:** a cell installs from values only; two tenants on two hosts pass the e2e suite.
- **Depends on:** WP-014c, WP-017

### [ ] WP-015 — Clickable prototype of console and portal
- **Goal:** Stage 0 product outcome: navigable prototype to validate journeys with stakeholders.
- **Scope:** Console shell (navigation, command palette, split list/record view, dashboard
  placeholder) and portal shell (AI-assistant landing, catalog, my requests) using mock data
  through the real `ui` and `labels` packages; en/ar.
- **Acceptance:** Product owner reviews screenshots of the journeys in both apps (D-008); all text
  via labels; no ManageEngine screens or wording reused.
- **Depends on:** WP-010. Built from the spec with Ant Design defaults (D-008); no designer input
  needed.

### [x] WP-016 — Authorization policy layer (added by D-025; done 2026-10-23)
- **Goal:** One authorisation policy layer (architecture.md §11.2) that every caller uses, so
  WP-012 and all later modules copy a real permission model instead of `user_type` checks.
- **Scope:** Roles and permissions model (module + action, e.g. `change.approve`); scopes
  (all / site / group / own); attribute rules (e.g. HR cases only for the HR group, assets by site
  and state); field-level visibility (hidden or masked fields per role); segregation-of-duties
  checks (requester of a change cannot approve it; conflicts flagged at role design time). One
  policy evaluation service used by the API, search, realtime fan-out (§8.2) and AI agents.
  Compiled permissions per user cached in Valkey and invalidated by events (role, group and
  membership changes via the outbox). Seed roles: tenant admin, technician, requester (mapped
  from the Keycloak realm roles). Replace the `user_type` checks in `identity_access` (WP-008
  users API) with policy calls. RLS stays the final tenant boundary beneath it.
- **Acceptance:** Tests for each level (module/action, scope, attribute, field masking, SoD) on a
  sample resource; the same decision from API, search filter, realtime subscription check and an
  AI-agent tool call; cache invalidated by a role-change event; tenant A roles never apply in
  tenant B; labels (en/ar) for every role, permission and scope code.
- **Depends on:** WP-006, WP-007, WP-008

## Stage 1: planned work packages

Planned ahead of Stage 1 (architecture.md §17); scoped and numbered when Stage 1 starts.

### [ ] WP-017 — Tenant branding and domains (D-027; planning only)
- **Goal:** Each tenant gets its own address and look without a redesign: the WP-010 theme
  already takes per-tenant seeds (`Branding` in `packages/ui/src/theme.ts`).
- **Scope:** Per-tenant subdomain in SaaS (`<slug>.supportx...`); optional custom domain with
  automatic TLS (ACME, certificate lifecycle per cell); tenant resolution from the request host as
  a login hint (pre-selects the Keycloak organization, never an authorisation decision); logo,
  favicon and brand colours on console, portal, the Keycloak login theme and outgoing e-mails;
  a branding admin screen (preview, contrast check against WCAG AA before saving); assets stored
  through the S3 API (D-016) and served with cache headers; works on-prem (one installation
  domain) through the same entitlement and settings interfaces.
- **Acceptance:** Two tenants on two hosts see their own logo and colours on every surface
  including the login page and e-mails; an unknown host falls back to the default brand; a colour
  failing contrast is refused with a translated message; e2e covers both hosts.
- **Depends on:** WP-010, WP-014 (ingress/TLS), WP-016 (admin permission for branding)

### [ ] WP-018 — Tamper-evident audit log (D-034; planning only)
- **Goal:** The §7.4 audit log: who did what, when, from where, provably unchanged.
- **Scope:** Append-only audit records for privileged actions and record changes (built on the
  WP-012 field history), each hashed with the previous record's hash per tenant (hash chain),
  periodic anchors, a verification tool and an export for auditors; retention and archiving
  (partitioning of `field_changes` and the audit table); GDPR erasure that keeps the chain
  verifiable.
- **Acceptance:** Editing or deleting any stored audit row is detected by the verifier; export
  of a tenant's log for a date range; retention job tested on 10M rows.
- **Depends on:** WP-012, WP-014

## Session log (newest first)

### 2026-10-24 — Parity spec phase 2, batch 1 (docs only)

- Recorded the product owner's answers to the phase 1 questions as D-039 to D-050 and applied
  them to `01-work-items-incidents.md` (now 175 requirements: new REQ-WI-025 locked features,
  REQ-INC-150 undo merge) and to the parity README (module files regrouped into twelve, MVP =
  Stage 1 internal go-live plus one design partner). D-036 timing amended by D-040 (Tiptap
  with the first incidents work package); CLAUDE.md §3 updated.
- Added `02-service-requests-catalog-portal.md` (127: 60 MVP / 51 V1 / 16 LATER) and
  `03-sla-assignment-rules-workflows-notifications.md` (146: 60 / 73 / 13).
- No code changed. Next: batch 2 (files 04 problems, 05 changes, 06 releases and projects).

### 2026-10-24 — Parity spec phase 1 (docs only)

- Added `docs/specs/parity/`. `README.md` is the index: 14 modules in build order with their
  ID prefixes and the reference areas each draws on; the ID scheme; the fields every
  requirement has; how acceptance criteria become test names; and the cross-cutting lessons,
  each mapped to the requirement that implements it.
- Added `01-work-items-incidents.md` with 173 requirements: 24 engine-wide (REQ-WI) and 149
  for incidents (REQ-INC).
  - By decision: 89 SAME, 60 BETTER, 22 NEW, 2 SKIP.
  - By priority: 84 MVP, 73 V1, 16 LATER.
  - It also holds proposed tenant defaults (Appendix A) and 12 open questions.
- Gaps: reference Area 14 is not in the repo (the brief named Areas 1–14), and ESM has no
  research area. Neither blocks file 01.
- No code changed. Next phase: file 02 (service requests, catalog, portal).

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

### 2026-10-24 — WP-012b WP-012 follow-ups
- Decisions: D-035 (dayjs approved as a direct dependency; one shared date-time field in the
  user's profile time zone), D-036 (rich-text editor = Tiptap + server-side sanitising, with
  Knowledge; open question 2 closed).
- Dates: `DateTimeField` / `DateTimeRangeField` in `packages/ui/src/dates` (Ant Design
  DatePicker / RangePicker; zone from `/auth/me`, else the browser's, else UTC; ISO instants in
  and out; zone note under the field; picker "Now" hidden because it uses the browser clock).
  Zone conversion via `Intl` (`zone.ts`), not the dayjs timezone plugin (DST bugs with pickers;
  Arabic digits in formatted strings). dayjs locale follows the UI language (en/ar/ur). The
  announcement form's native `datetime-local` inputs replaced; module-template.md updated.
- Owner picker: `PolicyService.holders` / `user_holds` (identity_access; SQL narrows by granting
  roles incl. unmapped defaults, each confirmed with the user's compiled subject so licence
  entitlement applies); `get_policy` exported; `GET /announcements/owner-candidates?search=&
  include=&limit=` (needs `announcements.manage`; `include` names the current owner first); create
  and edit refuse an owner without `announcements.manage` (`owner_not_allowed`; an unchanged owner
  is not re-checked). Console: searchable owner select, author preselected, refetched on open.
- Teardown: `tooling/e2e_fixtures.py delete` also hard-deletes custom roles named "E2E …" that are
  already soft-deleted (their permissions cascade; live, system and other roles untouched).
- Fixed on the way: `test_today_follows_the_users_time_zone` failed between 19:00 and 10:00 UTC
  (it assumed Karachi midnight is before Honolulu's day starts); it now picks an instant that is
  today in Karachi but not in Honolulu at any time of day.
- Dev data: 23 soft-deleted "E2E …" custom roles (Demo Company; 0 holders) and their 43 permission
  rows hard-deleted, nothing else (no other suite records matched).
- Follow-ups: owner candidates do not update live while the picker stays open (refetched on
  every open); portal announcement page; delete API for sites/groups (from WP-012).

### 2026-10-23 — WP-012 walking skeleton (announcements)
- Decisions: D-032 (announcements in a new module, licensed by `incident`, banners in console and
  portal, four-eyes off by default, reasons on unpublish/archive, live publish window, checklist
  not scaffold), D-033 (plain-text body; Urdu for new strings; rich-text editor question before
  Knowledge), D-034 (field history now, hash-chained audit log = WP-018). ADR-024.
- Shared platform pieces: field history (`app/shared/history`, table `field_changes`, migration
  0008; source `ui`/`api` from `X-SupportX-Client`; reasons; history paging; 409s explained with
  `changed_fields` / `changed_by` / `changed_at`); status machines with a fixed action order
  (`app/shared/domain`); `PermissionSpec.defaults` (modules own their built-in role defaults);
  users' calendar filters in their time zone (`X-Time-Zone`, profile zone in `/auth/me`).
- Module `announcements` (migration 0009): RLS tables incl. audience links (same-tenant FKs) and
  tenant settings; service with scope checks before and after every write, history and outbox in
  the same transaction; API (list with DSL, trash, feed, settings, CRUD, publish / unpublish /
  archive / reopen with reasons, restore, history); action states with reasons and `can_manage`;
  requester read path (live-for-me public view, everything else 404); four-eyes as a SoD rule.
- Live: staff list and record channels (presence); ID-free tenant broadcast for banners and the
  portal; scheduled windows go live by a client timer from `next_change_in_seconds` (no
  scheduler). Console: list (filters, sort, trash, four-eyes switch), record (fixed actions,
  disabled with tooltip reasons, reason dialog, edit form with live notice and 409 "who changed
  what", History tab), create; banners in console and portal; portal home lists the feed.
- Follow-ups done: (a)+(b) relay purges expired idempotency keys and consumer records > 30 days
  (min 7, enforced by relay-only RLS policies, migration 0010); (c) time zone; (d) `make check`
  runs `CI=true pnpm install --frozen-lockfile` first; profile PATCH writes history and its 409
  says who changed what.
- Found on the way: a transition read the status after the repository had updated the same
  object (history said "draft → draft") → status kept before the update; generic OpenAPI enum
  names (`Status`, `Action`) would collide across modules → `Announcement…`; field codes passed
  through a helper were invisible to the label check (`errors.field.required` had no label) →
  written out literally; `permission_reason.*` and the new reasons merged into
  `action_reason.*` (checked by `tests/test_action_reason_labels.py`); axe: Ant Design's gold
  tag and default danger text fail contrast → severity as a dot + text, theme `colorError`
  darkened (light) / lightened (dark) for every danger control.
- Tests: backend 798 (announcements API 25 incl. 10k performance, domain 21, status machine 6,
  housekeeping 2, fixture tool, labels); Vitest 138; Playwright 24 journeys (6 new: two-browser
  live + 409 + reasons, scheduled publish 1 min ahead on a second browser, requester visibility in
  Arabic RTL, site-scoped technician, tenant isolation, axe light/dark/RTL). 10,000 rows: p95
  9.2–11.8 ms for every list and the feed.
- Dev data: migrations 0008–0010 applied to the dev database (new tables and policies only); the
  fan-out and consumer workers restarted to load the module; the suite's E2E records are
  hard-deleted by `tooling/e2e_fixtures.py delete` (also run once by hand: 10 history rows of the
  suite user `e2e.tech`).
- Follow-ups: ~~owner picker in the form~~ and ~~E2E role teardown~~ (done in WP-012b); portal
  announcement page; delete API for sites/groups; layer contracts for the older modules; history for
  role and unit changes; `field_changes` partitioning with WP-018.

### 2026-10-23 — WP-011 realtime pipeline end to end
- Decisions: D-030 (`centrifuge` client approved), D-031 (navigation layout as a server-side user
  preference, SDP parity). ADR-023 (realtime pipeline). Docs: docs/architecture/realtime.md.
- Backend: `app/shared/realtime` (§8.1 channel names, HS256 connection/subscription tokens,
  Centrifugo server API client, `ChannelSpec`/`RealtimeRoute`/`LiveList` declarations);
  `/api/v1/realtime/connection-token`, `/subscription-token` (policy layer decides),
  `/lists/{list}`; identity_access channels (own, tenant broadcast, user records with presence,
  users and roles lists) and routes; licensing route for plan changes; logout/tenant switch cut
  the old connection. Production now requires the Centrifugo settings.
- `workers/realtime_fanout` (`make worker-fanout`): windowed WP-007 consumer, list coalescing
  (250 ms), per-tenant token bucket, idempotent batch publishes, cache invalidation before
  publishing, revocation by disconnect (code 4000), metrics + heartbeat, reported by /ready.
- Centrifugo dev config: history + forced recovery, presence, SSE/HTTP-streaming fallbacks,
  Prometheus; namespace separator moved so the `t:` names stay as in §8.1.
- Frontend: `packages/realtime` (centrifuge-js; WebSocket → HTTP streaming → SSE → polling;
  shared channels, recovery, presence; hooks), live users list, roles list, access drawer,
  menus, licence banners, profile change notice + presence; reconnecting/polling banner.
- Navigation layouts: top bar (default, More overflow), side bar, compact side bar; stored in
  `users.nav_layout` (migration 0007), follows the user live to other sessions.
- Found and fixed on the way: dark-mode contrast of horizontal menu / "More" selection; a race
  where a plan change could be refetched before the entitlement cache was dropped (now dropped
  by the route before publishing); e2e navigation helpers made layout-independent.
- Tests: backend 739 (tokens, channels, live lists, registry, fan-out merging / rate limit /
  failures, pipeline through NATS, token endpoint attacks); 114 Vitest (incl. 12 realtime);
  Playwright 17 journeys (two-browser live updates, streaming and polling fallbacks, raw
  WebSocket attacks, revocation < 1 s, layouts with axe). Measured: 200 saves p50 153 / p95 275 /
  p99 291 ms; 2,000 connections × 200 changes p50 205 / p95 353 / p99 407 ms, 0 lost; Centrifugo
  ≤ 10 % CPU / 131 MiB, fan-out ≤ 5 % CPU / 91 MB.
- Follow-ups: Prometheus scrape of the worker (WP-014 ingress also routes /connection and
  /emulation to Centrifugo); work-item, dashboard and portal channels as those modules arrive;
  sites/groups lists live in the access drawer; fan-out horizontal scaling (one consumer today).

### 2026-10-23 — WP-016 authorization policy layer
- Decisions: D-028 (`@ant-design/icons`, `@hookform/resolvers` approved), D-029 (SupportX DB is the
  source of truth for authorization; Keycloak roles mapped once at first login). ADR-022.
- Backend: permission catalogue as code (30 permissions: users, roles, profile, sites, groups,
  settings, licence + reserved requests/problems/changes/releases/assets/cmdb/knowledge/reports),
  each tied to a licence feature; `ModuleSpec.permissions`. Migration 0006: roles,
  role_permissions (scope + filter-DSL condition), user_roles, sites, support_groups, members
  (RLS, same-tenant composite FKs, guard passes), users.roles_mapped_at.
- Policy service: compiled subjects (grants, memberships, entitlements) cached in Valkey per
  tenant generation; `authorize`, `authorize_stored`, `scope_filter` (SQL, OR over grants, DSL
  conditions via the WP-008 compiler), `visible` (hide/mask), SoD rules (`own_request_approval`).
  Invalidation after commit (`access_changed`) + consumer `identity_access__invalidate_authz`.
- Enforcement: `require_permission` / `require_signed_in` / `@public_route` on every route, guard
  test proven against a planted route; interim checks (technicians_only, tenant_admin role,
  admin-only Users page) replaced; `/auth/me` returns SupportX roles + effective permissions;
  licensing's admin notices use `licence.manage`.
- Admin API: permissions, roles CRUD (ETag/If-Match, Idempotency-Key), user access, role
  assignment, sites/groups with members. Protections: system roles immutable, no escalation, last
  tenant admin (advisory lock), role-in-use reassignment.
- Console: Admin (tabs Users / Roles), role editor with permission matrix (scope per permission,
  locked when outside the plan, read-only system roles), user access drawer (roles, sites,
  groups), menus and pages driven by permissions. en + ar labels for every permission, scope,
  role, reason and screen.
- Found by tests: `site`/`group` were wrongly treated as covering `own` (lost own rows) → only
  `all` covers; membership changes only reached the cache via the consumer → after-commit hook.
- Found by CI: on a cache miss the subject and the entitlement were read on a second connection
  while the request held one, so 5 concurrent requests deadlocked CI's 5-connection PgBouncer
  pool → both read through the request's connection (`REQUEST_SESSION_STATE`), test asserts one
  connection per request. Dark mode's selected menu/tab text was ~1.6:1 (Ant Design's dark
  primary) → light brand tint, contrast test for several brand colours. axe scans only the open
  modal (the page behind its mask is inert).
- Tests: backend 686+ (matrix, scopes on 100k rows ~1 ms/page, rules SQL ≡ memory, masking, SoD,
  escalation/system role/last admin/cross-tenant/stale cache attacks, guard, mapping once);
  frontend 110 Vitest; Playwright 10 journeys incl. custom role → menus and axe (roles list,
  editor, drawer; Arabic + dark).
- Follow-ups: SSO group → role mapping; condition editing in the UI; design-time SoD warnings;
  user_type (seat counting) still follows Keycloak; search/realtime/agent call sites (WP-011+).

### 2026-10-23 — WP-010 frontend foundation and design system
- Decisions: D-026 (react-router 7.x — 8.x needs React 19 —, openapi-fetch, @axe-core/playwright;
  CLAUDE.md §3), D-027 (Stage 1 WP-017 tenant branding and domains, planning only). Companions
  named for veto: `@ant-design/icons` 5.x (MIT), `@hookform/resolvers` (MIT). i18next 26.5.4 /
  react-i18next 17.1.0 chosen to respect pnpm's minimum release age (no policy exclusion added).
- api-client: openapi-fetch on `schema.ts`; middleware adds X-Request-ID, CSRF, Idempotency-Key
  (POST) and If-Match (from remembered ETags); `call()` → typed `ApiError` (problem details,
  field errors, request ID, outage detection); connectivity events; `queryKeys`; hooks for
  session, tenant switch, entitlements, users (infinite, filter DSL), user, update user.
- labels on i18next + react-i18next (flat keys, CLDR plurals incl. six Arabic forms,
  interpolation, humanize fallback); ~150 new en/ar keys, ur for the shell. ESLint plugin
  `@supportx/eslint-plugin` (`no-raw-enum`, `no-literal-text`; 23 rule tests). Backend
  `test_enum_labels.py`: every enum in the OpenAPI contract needs en+ar labels.
- ui: Extravis theme (#9619B5), light/dark/high contrast, AA-safe secondary text, tenant
  `Branding` override, antd locales; AppShell, header (tenant switcher, user menu, appearance),
  Ctrl+K palette, Coming soon / Not in plan; licence context, grace + read-only banners,
  `WriteButton`; error reporter (toasts + Copy reference), conflict dialog, reconnecting banner,
  error boundary, `createQueryClient`. forms: FormField + applyServerErrors. charts: themed,
  RTL-mirrored ECharts wrapper.
- Console: react-router with lazy routes (Home, 8 sections, Admin › Users, My profile, 404,
  dev-only /dev/components), entitlement-aware sidebar (hidden; locked + upgrade hint for
  admins). Portal: simple top-nav shell. Vendor chunk groups (`vite.chunks.ts`): largest chunk
  726 kB → 416 kB, no chunk over 500 kB.
- Found and fixed via e2e: every login bumped the user's `version` (JIT upsert), so signing in on
  a second device made an open profile form stale → version now moves only when a synced field
  changes (+ test); "keep my changes" re-sent untouched fields and wiped the other user's change
  → PATCH now sends only changed fields; antd secondary text / tags / dark sider failed axe
  contrast → tokens and badges fixed.
- Tests: frontend 102 Vitest (api-client 9, labels 25, ui 13, forms 3, eslint-plugin 23,
  console 25, portal 4); Playwright 8 journeys on the dev stack incl. axe (0 serious/critical on
  home, coming soon, users, profile, Arabic RTL, high contrast, dark); backend 602.
- e2e test data: suite-owned Keycloak users e2e.tech/e2e.admin (random password per run), 40
  `e2e-scroll-NN` requester rows (`tooling/e2e_fixtures.py`, deleted after the run), Other
  Company plan changed and restored with `make dev-subscription`. CI stack-smoke now starts the
  event workers and runs all journeys.
- Follow-ups: initial console download is larger than before (shell uses more of Ant Design;
  ~415 kB gzip) — trim with per-component imports or lazy header widgets; live entitlement
  refresh via WP-011; field-level permission rendering from WP-016; Urdu labels complete in
  Stage 2.

### 2026-10-23 — WP-009 entitlement interface (+ planning: WP-016, D-025)
- Part A: WP-016 "Authorization policy layer" (§11.2) added before WP-012 (WP-012 now depends on
  it); D-025 records it and that D-030..D-039 are released. WP-008 session-log entry moved to its
  newest-first place.
- `licensing` module (ADR-021, `docs/architecture/entitlements.md`): catalogue as code (3
  editions, 25 features, 5 counted limits, rate multipliers; en/ar labels CI-checked);
  `Entitlement` with derived state active / grace / read_only / invalid (expiry, suspension,
  WP-013 `degraded_since`), maintenance window; licence document parser (§13.3, whole-day UTC
  terms, canonical `signed_payload`). Interface: has_feature, require_feature, check_limit,
  remaining, hold_limit, reserve_capacity, current_state, summary.
- Providers (config `SUPPORTX_ENTITLEMENT_PROVIDER`): `subscription` (migration 0005
  `tenant_subscriptions`, platform table: app SELECT of its own row only, RLS guard allowlist),
  `licence_file` (unsigned accepted in dev/test only; production refuses to start; signed files
  wait for WP-013), `StaticProvider` for tests. Providers read through the caller's session.
- Enforcement: `ModuleSpec(feature=..., usage_counters=...)`; the registry adds a route guard to
  every module route (`app/core/entitlements.py`): 403 `entitlement_required` (params feature),
  403 `read_only_mode` for POST/PUT/PATCH/DELETE (params reason; `@read_only_exempt`,
  `@entitlement_exempt` for exports/health/login), grace headers `SupportX-Licence-*` for tenant
  admins (`TenantContext.roles` added). Technician seats reserved at JIT provisioning under a
  per-tenant advisory lock (`technician_limit_reached`, browser `?auth_error=`); requesters
  unlimited; existing technicians never re-checked. Rate-limit budgets ×1/×2/×4 by edition.
- Valkey cache per tenant with generation counter; `licensing.entitlement.changed` (outbox) →
  consumer `licensing__invalidate_cache`. `GET /api/v1/entitlements` (edition, features, limits
  with usage for staff, state, term; no secrets).
- Guards: AST test fails on deployment-mode references outside licensing; import-linter contract
  "Only the licensing module touches entitlement providers" (proven to break on a planted import).
- Dev: `make db-seed` → Demo Company Enterprise, Other Company Professional with 2 technician
  seats; `make dev-subscription TENANT=.. ARGS=..` changes a dev plan (row + event). Test tenants
  get an Enterprise plan by default; every test app gets a random Valkey prefix.
- Tests: 598 backend (coverage 97.5%), incl. 20-way provisioning race (exactly 5 of 20 at limit
  5), same user ×10 in parallel takes one seat, read-only on every write method, grace headers,
  both providers gating identically, production rejects unsigned licence, cross-tenant RLS on
  subscriptions, end-to-end cache invalidation over outbox → NATS → consumer → Valkey. The race
  test found a real pool-starvation deadlock (provider opening a second connection while holding
  the seat lock); fixed by reading through the caller's session. Verified live on the dev stack
  with real Keycloak logins (seat block, no lock-out, grace headers, read-only, ~1 s plan refresh).
- Follow-ups: UI use of `/entitlements` (menus, banners; WP-010/015) and live refresh via WP-011;
  counters for assets, desks, MSP customers, monthly AI-run meter; installation-wide on-prem
  counts; soft-deleted users must retake a seat on return; WP-013 verifier, fingerprint,
  15-minute re-check; admin targeting via WP-016.

### 2026-10-23 — WP-008 API conventions (Agent 1, parallel with WP-010)
- Part A: D-023 (opentelemetry-exporter-prometheus + prometheus_client approved for WP-014),
  D-024 + CLAUDE.md §11 "Working rules" (no destructive git command without stash/commit first;
  same protection for data).
- `app/shared/api/`: `concurrency` (ETag from version, If-None-Match → 304, If-Match required:
  428 precondition_required / 409 version_conflict / 400 invalid_etag), `idempotency`
  (`idempotency_keys` table, claimed + stored in the request transaction, tenant+user scoped,
  24 h TTL, replay / 422 idempotency_key_reused / concurrent duplicates wait and replay),
  `filters` (JSON DSL with and/or groups, 13 operators + 10 relative-date operators, typed
  per-resource allowlist, limits, JSON-path errors, simple `?field=value` params, bound
  parameters only), `listing` (sort allowlist + id tie-breaker, keyset pagination with NULL
  handling, HMAC-signed cursors bound to endpoint/tenant/user/sort/filter, page envelope with
  capped `estimated_total`), `ratelimit` (Valkey fixed window per user + per tenant per route
  group, RateLimit-* headers, 429 + Retry-After, policy-provider hook for WP-009, fail open),
  `deprecation` (Deprecation/Sunset/Link, 12-month minimum), `openapi` (FilterExpression schema
  published; generated TS types). AppError now carries response headers; PreconditionRequired.
- Migration 0004: `idempotency_keys` (RLS), users.signature/time_zone, keyset indexes
  (tenant_id, field, id). Endpoints: GET /api/v1/users (filter/sort/cursor), GET /users/{id}
  (ETag/304), PATCH /users/{id} (own signature/time zone, If-Match, emits user.updated).
  Permissions: technicians list/read others; anyone reads self; only own preferences.
- `tooling/openapi_diff.py` + `make openapi-diff` + CI step against the target branch (recursive,
  additive-aware; also catches renamed schemas). Fixed WP-007 event checker: a class docstring
  edit was wrongly reported as breaking.
- Labels: 10 problem codes + 22 field-error codes (en/ar); label test now also checks
  `errors.field.*`. CI backend job gains a Valkey service; Valkey tests are required in CI.
- Tests: 500+ backend (unit: DSL grammar/limits/injection, cursors, sorting, ETags; HTTP + real
  PostgreSQL: users API, idempotency incl. 10 concurrent duplicates, rate limits on real Valkey).
  Filter compile 0.2 ms (30 conditions); 100k-row filtered list p50 5.7-7.5 ms over HTTP.
- Follow-ups: cleanup job for expired `idempotency_keys`; API-token subject for rate limits once
  API keys exist; entitlement-based rate-limit provider (WP-009); user time zone for relative
  dates; 409 "what changed" needs field history (§7.4); a permission policy layer (none exists
  yet; the users service checks user_type directly).

### 2026-10-23 — WP-007 transactional outbox and event bus
- `app/shared/events`: `EventEnvelope` (UUIDv7 event_id, type, schema_version, tenant, actor,
  occurred_at, aggregate type/id/version, correlation/causation IDs, traceparent, payload);
  `DomainEvent` classes in each module's `events.py`, listed in `ModuleSpec(events=…)`;
  `EventRegistry` enforces `<module>.<entity>.<action>` and unique (type, version); unregistered
  events cannot be written. `record_event()` inserts into `outbox_events` in the caller's
  transaction. `ModuleSpec.event_handlers` replaced by `events` + `consumers`.
- Migration 0003: `outbox_events` (RLS; app role INSERT only), `processed_events` (RLS), NOTIFY
  trigger, relay policies `TO supportx_relay`. New role `supportx_relay` in `tooling/sql`
  (NOBYPASSRLS; outbox only). RLS guard checks relay grants (table + column) and allowlisted
  cross-tenant policies. `make db-bootstrap` (run by `db-migrate`) adds missing roles to an
  existing dev volume. ADR-019 records the conventions; ADR-018 note (dev logger lives in system).
- Workers: `outbox_relay` (LISTEN/NOTIFY + poll, SKIP LOCKED batches, Nats-Msg-Id dedupe, mark
  after ack, 72 h purge of published rows), `consumers` (durable pull consumers from modules,
  processed_events claim in the handler transaction, tenant SET LOCAL, exponential backoff, DLQ
  after N attempts, per-consumer replay subject), `bus.py` (streams + heartbeat KV as code),
  heartbeats → `/ready` informational checks (`outbox_relay`, `event_consumers`, `degraded`),
  OpenTelemetry metrics. Import-linter contract: no `nats` in `app/` except readiness probes.
- identity_access events: user.provisioned, user.updated (changed field names), user.logged_in,
  user.logged_out, session.tenant_switched (target tenant only). Dev-only
  `system__dev_event_logger` consumer. Event-type labels en/ar + CI test.
- Schemas exported to `docs/architecture/event-schemas.json`; `make events-check` (lint) and a CI
  step against the target branch fail on breaking changes.
- Make: worker-relay, worker-consumers, events-tail, events-stats, dlq-list, dlq-replay,
  events-schemas, events-check, db-bootstrap. Docs: `docs/architecture/events.md`, dev-setup.
- Tests: 362 backend (coverage 97%): atomicity, crash-after-publish dedupe, consumer crash
  before commit and before ack, poison → DLQ → replay, 2 parallel relays × 2,000 events, RLS for
  app and relay roles, worker entry points. Dev stack: latency p50 0.9 / p95 1.3 / p99 2.4 ms
  (1,000 events), relay ~20,900 events/s (10,000). CI starts NATS JetStream; NATS tests required.
  Verified live: real Keycloak login/logout → events in events-tail and the consumer log.
- Follow-ups: retention job for `processed_events`; Prometheus scrape endpoint (WP-014; exporter
  dependency needs approval); move the outbox purge to a Temporal schedule once Temporal workers
  exist; audit-trail consumer for auth events (audit module).

### 2026-10-23 — WP-006 identity and authentication
- Part A: role/grant definitions now live once in `backend/tooling/sql/*.sql`, run by both the dev
  stack's PostgreSQL init (psql) and `tooling/db_bootstrap.py` (tests, CI). Proven with
  dev-reset → dev-up → dev-check → db-migrate. D-021 (cryptography), D-022 (openapi-typescript).
- Keycloak: realm export `deploy/compose/keycloak/supportx-realm.json` imported on dev-up
  (Organizations on, confidential `supportx-console` / `supportx-portal` clients with PKCE S256,
  `supportx_organizations` + `supportx_roles` claims, password policy, brute-force protection),
  orgs Demo Company / Other Company (`tenant_id` attribute), six test users (one Arabic, one
  multi-org, one without org). Client secrets are generated into `.env` and injected.
- BFF (`identity_access/bff`): /auth/login, /callback, /logout, /me, /switch-tenant. ID tokens
  verified (RS256 via JWKS + issuer/audience/expiry/nonce). Sessions in Valkey, AES-256-GCM,
  hashed keys; opaque HttpOnly SameSite=Lax cookie (`__Host-` + Secure in production); new ID on
  login and tenant switch; idle/absolute timeouts; silent refresh (refused → session ends);
  synchronizer CSRF token + Origin check; back-channel Keycloak logout. Browser login failures
  return to the app with `?auth_error=` (translated), API clients get problem details.
- Users table (migration 0002, RLS, guard passes), JIT provisioning, `supportx_stamp_actor`
  trigger fills created_by/updated_by from `app.user_id`. Tenant context now comes from the
  session; `X-Tenant-ID` only with SUPPORTX_DEV_TENANT_HEADER=true in dev/test, never production.
  Readiness checks Keycloak.
- Frontend: generated `api-client/src/schema.ts`, `apiFetch` (CSRF header on unsafe methods),
  `useSession`/`useLogout`; ui `SessionGate` (login redirect, user locale → RTL) and `AppHeader`
  (name, tenant, sign out) in console and portal; labels en/ar (+ur for auth basics).
- Tests: backend unit (domain, crypto, JWT, fake IdP), DB tests for the full BFF flow, real-Keycloak
  integration tests (each user, JIT, logout ends both sessions, Other Company isolation, no-org 403,
  production ignores the header, brute force + password policy); Playwright login journey; all
  run in CI (stack-smoke on auth/deploy PRs and nightly). Verified by hand in Chrome as well
  (fixed a header contrast bug and a raw-JSON error page found that way).
- Follow-ups: tenant switcher UI (endpoint exists); Keycloak production hardening (WP-014);
  auth audit events with the outbox (WP-007); `errors.field.*` labels (WP-010).

### 2026-10-23 — WP-005 data layer, RLS and tenancy bootstrap
- Arabic label check: all ar/ur labels were already in correct logical order (the reversed text
  was the terminal's rendering); verified in Chrome (RTL, joined letters). Added
  `packages/labels/src/rtl-order.test.ts` (known values + a reversed-text detector). D-020 recorded.
- `app/core/database.py`: SQLAlchemy 2 async engine for supportx_app via PgBouncer (asyncpg
  statement cache off, SQLAlchemy prepared-statement cache off, unique statement names); tenant
  sessions write `app.tenant_id`/`app.user_id` with `set_config(..., true)` in an `after_begin`
  hook and refuse SQL without a tenant; `TenantSession` = one transaction per request, committed
  before the response (`Depends(scope="function")`). `app/core/tenancy.py`: X-Tenant-ID trusted in
  dev/test only; production ignores it (401 `tenant_required` until WP-006).
- `app/shared/db/`: `Base` with naming convention, mixins (`TenantEntity`: UUIDv7 id, tenant_id,
  timestamps, actors, version, deleted_at), RLS SQL helpers (ENABLE + FORCE, four per-command
  policies with `NULLIF(current_setting('app.tenant_id', true), '')::uuid`), generic `Repository`
  (keyset cursor, optimistic concurrency → 409 `version_conflict`, soft delete), `next_display_id`.
- Alembic (`backend/alembic.ini`, `migrations/`), as supportx_migrator directly to PostgreSQL;
  migration 0001: `tenants` (platform table; app reads only its own row, cannot write) and
  `display_id_sequences` (tenant-scoped). `organization` module with `GET /api/v1/organization/tenant`.
- Tooling: `db_bootstrap` (roles + database, shared by fixtures and CI), `rls_guard`, `seed_dev`
  (demo tenant `01900000-0000-7000-8000-00000000de30`), `db_testing` (throwaway
  `supportx_test_*` databases). Make: `db-migrate`, `db-downgrade` (asks "yes"), `db-revision`,
  `db-current`, `db-seed`, `db-guard`. Dev PgBouncer now routes any database name (`*`).
- Tests: 172 backend (64 against real PostgreSQL through PgBouncer), coverage 98%. Mutation checks:
  removing NULLIF fails 2 tests, removing RLS fails 9, asyncpg defaults behind a PgBouncer without
  prepared-statement tracking fail with "prepared statement does not exist".
- CI: backend job has PostgreSQL + PgBouncer (max_prepared_statements=0) service containers,
  bootstraps roles, migrates, runs the RLS guard and all database tests (cannot be skipped).
- Docs: `docs/architecture/tenancy.md`, dev-setup (database commands, demo tenant).
- New dependencies: sqlalchemy[asyncio] (+ greenlet), alembic (+ Mako, MarkupSafe) — all listed
  in CLAUDE.md §3; MIT/BSD.
- Follow-ups: `sites` (WP-005 scope in the plan) deferred to the first feature that needs it; the
  dev-stack init script and `tooling/db_bootstrap.py` duplicate role creation (keep in step, or
  switch the compose init to the Python tool); tenant provisioning API/role (WP-006 or later).

### 2026-10-23 — WP-004 backend application core
- Housekeeping: PR #7 was already merged; Dependabot PR #3 (jsdom 27 → 30) rebased, all checks
  green, merged; D-019 (uvicorn, structlog, uuid-utils, OpenTelemetry) recorded via PR #8.
- Settings (`app/core/config.py`): pydantic-settings, `SUPPORTX_` env vars + `backend/.env`,
  profiles dev/test/production (production requires every backing-service URL), secrets as
  `SecretStr`. `make backend-env` writes `backend/.env` from the dev stack's secrets.
- App factory + lifespan (`app/main.py`), `python -m app` entry point, `make backend-dev`
  (uvicorn, reload, 127.0.0.1:8000). Module registry (`app/core/modules.py`, `ModuleSpec`):
  modules are discovered from `app/modules/`, so main.py never changes; documented in
  `app/modules/README.md`. Example `system` module (ADR-018) with `/api/v1/health` and
  `/api/v1/ready` (PostgreSQL via PgBouncer, Valkey, NATS; concurrent, 2 s timeout, reason codes).
- RFC 9457 problem details with `code`, `message_key`, `params`, field `errors`, `request_id`;
  `AppError` hierarchy; framework 404/405/422 mapped; unhandled exceptions → generic 500.
  Request-ID and security-header ASGI middleware. structlog JSON/console logging with request_id,
  tenant_id placeholder, trace/span IDs and redaction. OpenTelemetry FastAPI instrumentation,
  exporter `none` by default (`console` opt-in). UUIDv7 `new_id()` and `Clock`/`FrozenClock`.
- OpenAPI 3.1 export to `frontend/packages/api-client/openapi.json` (`make openapi`); drift check
  runs in `make backend-lint` and therefore in CI. Error codes have en/ar labels (CI test).
- Frontend: Vite proxies `/api` → 127.0.0.1:8000 in console and portal; console home shows a live
  API status tag (TanStack Query, 10 s poll) with labels in en/ar/ur. Verified in Chrome: green
  "API online", then red "API offline" without refresh after stopping the API.
- Tests: backend 97 (2 dev-stack integration tests skip automatically when the stack is down),
  coverage ≥ 96%; frontend 24. The integration test found that PgBouncer reports a bad password as
  a protocol violation; the probe now maps it to `auth_failed`.
- New runtime deps (D-019 + D-004): uvicorn, structlog, uuid-utils, opentelemetry-api/-sdk,
  opentelemetry-instrumentation-fastapi, pydantic-settings, asyncpg. Official client SDKs (named
  for veto): valkey (valkey-py, MIT), nats-py (Apache-2.0). Dev: asyncpg-stubs (BSD-3, D-012).
  Frontend: @tanstack/react-query (listed stack).
- Follow-ups: field-level error labels (`errors.field.*`) arrive with i18next in WP-010; the API
  client generation from openapi.json is WP-010; OTLP exporter when the observability stack lands.

### 2026-10-22 — WP-003 CI pipeline and quality gates
- Recorded D-015..D-017 (private GitHub repo + Actions, S3-only object storage, Temporal without
  auto-setup); ADR-012 updated with the object-storage direction and the MinIO image situation;
  WP-014 notes added. Later D-018: the repo is temporarily public because of a billing block.
- Created https://github.com/devhat-pm/supportx-v2 (private), pushed full history.
- `.github/workflows/ci.yml` (backend, frontend, pre-commit jobs), `security.yml` (gitleaks over
  full history, pip-audit + pnpm audit, Trivy fs; weekly), `stack-smoke.yml` (core profile +
  `make dev-check`; on compose PRs and nightly). Jobs call Makefile targets; composite actions
  `setup-backend` / `setup-frontend` share the toolchain setup (uv cache, pnpm store cache).
  Actions pinned to commit SHAs; `permissions: contents: read`; concurrency cancels stale runs.
- New Makefile targets `precommit`, `audit` (`audit-backend`, `audit-frontend`).
  `backend/tooling/vuln_gate.py` adds the high/critical gate pip-audit lacks (GHSA severity
  lookup; unknown severity blocks), with tests; proven to fail on jinja2 2.10 (1 high).
- Dependabot (actions, uv, npm; weekly; minor/patch grouped), PR template (DoD checklist),
  CODEOWNERS (`@devhat-pm`).
- First runs were refused by GitHub billing; after the switch to public: CI, Security and Stack
  smoke green on main, CI and Security green on PR #1 (README badges), PR #1 merged. Branch
  protection refused while private (403, needs Pro); applied once public.
- Follow-ups: Trivy misconfig scanning only covers files Trivy knows (no compose); Dependabot
  `docker-compose` ecosystem could track the pinned dev images (not requested; suggest later).

### 2026-10-22 — WP-002 local dev stack (Docker Compose)
- Recorded D-012..D-014 (helper libraries + dev-helper rule, i18next for labels in WP-010,
  TypeScript 5.9.x) in `docs/DECISIONS.md` and CLAUDE.md §3.
- `deploy/compose/`: compose file with 13 services + `minio-init` one-shot, all images pinned and
  multi-arch (arm64 verified), ports on 127.0.0.1 in a 2xxxx range (5432, 6379, 4222, 8025 are
  taken by other projects on the dev Mac), memory limits on every service. Postgres init creates
  `supportx`, `keycloak`, `temporal`, `temporal_visibility`, extensions vector/pgcrypto/citext, and
  the roles `supportx_migrator` (owner) and `supportx_app` (no superuser/owner/BYPASSRLS, DML-only
  default privileges). `make dev-init` generates random secrets into git-ignored `.env`.
- `make dev-check`: 18 core checks + 7 full checks, including a rolled-back functional RLS probe.
  Results: core 18 PASS / 7 SKIP; full 25/25 PASS; restart from kept volumes 18 PASS. Verified that
  a stopped service yields FAIL + non-zero exit, and that `dev-reset` deletes nothing without "yes".
- RAM: core ≈ 0.8 GB, full ≈ 3.3 GB (docker stats). `make check` green.
- Image deviations: MinIO community images were withdrawn from Docker Hub/Quay, so dev uses
  `pgsty/minio` + `pgsty/mc` (community build, AGPL; dev only; feeds ADR-012). Temporal
  `auto-setup` stops at 1.29.7 (server is at 1.32); fine for dev, revisit in WP-014.
- Follow-ups: WP-005 must create the same two roles in Testcontainers fixtures (the init script
  only runs in this dev stack); WP-006 realm import; WP-014 must decide Temporal schema setup
  without `auto-setup`.

### 2026-10-22 — WP-001 monorepo skeleton and dev tooling
- Backend: uv project pinned to Python 3.12 (`.python-version`), FastAPI app factory with
  `GET /api/v1/health`, §6.4 package layout, ruff (`select = ALL`), mypy strict, pytest +
  pytest-asyncio + coverage (fail-under 90%), import-linter with a custom `module_boundaries`
  contract (`backend/tooling/import_contracts.py`) plus a layers contract. 8 tests pass, 100% coverage.
- Frontend: pnpm workspace (`frontend/`), console + portal (Vite 8, React 18.3, TS 5.9 strict,
  Ant Design 5.29 with light/dark tokens, RTL switch, language picker), packages ui, labels
  (humanize, label lookup, en/ar/ur resources), plus placeholder api-client, realtime, charts, forms
  and flow. ESLint 10 flat config (typescript-eslint strict type-checked), Prettier, Vitest 5.
  18 tests pass. Both production builds succeed (chunk-size warning, ~607 kB / 194 kB gzip).
- Root: Makefile (setup, lint, typecheck, test, format, check, build), pre-commit (large files,
  ruff, ruff-format, mypy, eslint, prettier), `tsconfig.base.json`, `.prettierrc.json`, `.nvmrc`
  (24). Placeholder READMEs in `licence-core/`, `deploy/`, `mobile/`.
- `make check` green. Follow-ups: route-level code splitting (WP-010/WP-015); copyright-header
  policy (ruff CPY001 disabled for now).

### 2026-10-22 — Product owner decisions D-001..D-011
- Created `docs/DECISIONS.md`; applied decisions to CLAUDE.md (stack, layout, monitoring boundary,
  DoD languages), ADR-006 (revised), ADR-012, ADR-017 (clarification), all ADR owners, the
  product-plan.md authority banner, and WP dependency notes (WP-006, 008, 013, 014, 015).

### 2026-10-22 — Spec figures added
- Added `docs/specs/media/` with `architecture-overview.png` (Fig. 1), `realtime-flow.png`
  (Fig. 2) and `licence-activation.png` (Fig. 3); repointed the three image links in
  `architecture.md` from hash filenames to these names. No spec text changed.

### 2026-10-22 — Project bootstrap
- Moved specs to `docs/specs/`. Created `CLAUDE.md`, `README.md`, `.gitignore`, `.editorconfig`,
  `docs/adr/` (ADR-001..017 + index) and this file. Initialised git.
- Environment: Python 3.12 is available via uv (system `python3` is 3.9.6); pnpm, k3d and kind are
  not installed (pnpm can be enabled via corepack).
- No application code written. Next: WP-001.
