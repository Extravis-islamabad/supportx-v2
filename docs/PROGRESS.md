# SupportX v2 — Progress

## Current status

- **Stage:** 0 — Foundation (architecture.md §17). In progress: 5 of 15 work packages done.
- **Last completed:** WP-005 (data layer, RLS and tenancy bootstrap), 2026-10-23.
- **Next work package:** WP-006 (identity and authentication) — unblocked now. WP-007 (outbox),
  WP-008 (API conventions), WP-009 (entitlements) and WP-010 (frontend foundation) are also
  unblocked.
- **Blockers:** None for WP-006. WP-014 needs k3d installed (D-003; Homebrew is not installed
  either).
- **Repository:** https://github.com/devhat-pm/supportx-v2, **temporarily PUBLIC** (D-018) until
  the account billing problem is fixed; then set back to private (D-015).

### Open questions (awaiting product owner)

1. How k3d gets installed on the dev machine (no Homebrew): official install script, binary
   download, or install Homebrew first? Blocks WP-014.

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

### [ ] WP-006 — Identity and authentication
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

### [ ] WP-007 — Transactional outbox and event bus
- **Goal:** Non-negotiable rule (b) proven end to end.
- **Scope:** `shared/events` envelope (event ID, type, tenant, aggregate, version, occurred_at,
  payload); outbox table + writer used inside service transactions; relay worker publishing to NATS
  JetStream with per-tenant subjects; idempotent consumer base class recording processed IDs;
  stream/consumer provisioning.
- **Acceptance:** Tests show an event is published for a committed change, none for a rolled-back
  change, and redelivery is processed once; relay survives restart without loss.
- **Depends on:** WP-005

### [ ] WP-008 — API conventions
- **Goal:** Shared building blocks every module will use.
- **Scope:** Optimistic concurrency (version + ETag/If-Match, 409 with changed fields);
  Idempotency-Key handling on POST (Valkey-backed); cursor pagination; filter DSL v0 (field, op,
  value, AND/OR groups) compiled to SQLAlchemy; OpenAPI diff check script.
- **Acceptance:** Unit and integration tests for each block; a stale-version update returns 409; a
  repeated POST with the same key creates one record.
- **Depends on:** WP-004, WP-005

### [ ] WP-009 — Entitlement interface
- **Goal:** Non-negotiable rule (f) has a single, real seam.
- **Scope:** `licensing` module exposing `has_feature`, `check_limit`, `remaining`; provider
  protocol with a SaaS-plan provider stub and a dev provider (config-driven); FastAPI dependency
  for feature gates; problem-details error code for "not entitled"; import-linter contract that
  only `licensing` touches providers.
- **Acceptance:** Tests show gating works identically with both providers; a CI grep/lint fails on
  deployment-mode checks in module code.
- **Depends on:** WP-004

### [ ] WP-010 — Frontend foundation and design system
- **Goal:** Shared frontend packages that enforce rule (d) from day one.
- **Scope:** `packages/ui` (AntD 5 theme tokens, light/dark/high-contrast, RTL switch, app shell);
  `packages/labels` migrated to i18next + react-i18next (D-013; dictionary, `humanize()` with
  missing-label warning, plurals, interpolation, en/ar/ur resources);
  custom ESLint no-raw-enum rule; `packages/api-client` generated from the WP-004 OpenAPI export
  with TanStack Query hooks; console and portal apps boot with login redirect to the BFF.
- **Acceptance:** Both apps build and render in en and ar (RTL); ESLint rule test cases pass;
  regenerating the API client after a backend schema change breaks `tsc` where expected.
- **Depends on:** WP-001, WP-004

### [ ] WP-011 — Realtime pipeline end to end
- **Goal:** Non-negotiable rule (c) proven: commit → screen in under 1 s.
- **Scope:** Connection and subscription token endpoints with permission checks (§8.2); fan-out
  consumer NATS → Centrifugo using §8.1 channel names and minimal payloads; `packages/realtime`
  (Centrifugo client, channel hooks, TanStack Query cache patching, reconnect recovery, fallback
  indicator).
- **Acceptance:** Automated test: a change committed via the API reaches a subscribed browser
  client and patches the cache; an unauthorised subscription is refused; reconnect replays missed
  messages.
- **Depends on:** WP-006, WP-007, WP-010

### [ ] WP-012 — Walking skeleton: one demo entity through every rule
- **Goal:** A reference implementation future modules copy.
- **Scope:** A minimal throwaway-safe entity (e.g. `announcements` in a sandbox module) with the full
  four-layer shape: RLS table, CRUD API with version/ETag and idempotency, outbox events, entitlement
  gate, labels for its statuses, live list and record view in the console, Playwright e2e.
- **Acceptance:** Playwright test with two browser contexts: an edit in one appears live in the
  other without refresh; stale edit shows a 409 conflict message; tenant B never sees tenant A's
  records; no raw codes on screen.
- **Depends on:** WP-006, WP-007, WP-008, WP-009, WP-011

### [ ] WP-013 — Licence core prototype (Rust)
- **Goal:** De-risk ADR-009 early.
- **Scope:** `licence-core/` Rust crate: Ed25519 signature verify of the §13.3 licence JSON,
  fingerprint v1 (Linux sources in §13.4, 3-of-5 match), clock-rollback check; PyO3 bindings; an
  on-prem provider for the WP-009 entitlement interface; dev-only signing tool with a test key.
- **Acceptance:** Rust and Python tests: valid licence accepted, any edited field rejected,
  fingerprint tolerance works (2 changed components pass, 3 fail); no production key in the repo.
- **Depends on:** WP-009 (Rust/PyO3 approved by D-004; Rust toolchain must be installed)

### [ ] WP-014 — Deployment skeleton (Helm and local cluster)
- **Goal:** The same build runs on Kubernetes from day one (§14.3).
- **Scope:** Container images for API and workers (the BFF ships inside the API — D-009); one Helm
  chart with `values-dev`, `values-single-node` profiles; local k3d cluster script (D-003); readiness/liveness wired;
  in-cluster Postgres/NATS/Centrifugo for dev.
- **Acceptance:** `make cluster-up && make deploy-dev` installs the chart and the walking-skeleton
  e2e test passes against the cluster.
- **Depends on:** WP-002, WP-004 (WP-012 for the final acceptance run); k3d installed on the dev
  machine (D-003, open question 2)
- **Note (D-017):** Temporal is deployed without the `auto-setup` image; schema setup and
  migrations run as a job using `temporalio/admin-tools` (`temporal-sql-tool`) before the server
  starts. The dev compose stack keeps `auto-setup` 1.29.7.
- **Note (D-016):** object storage via S3 API only; the in-cluster dev store and the on-prem
  bundled store follow ADR-012.

### [ ] WP-015 — Clickable prototype of console and portal
- **Goal:** Stage 0 product outcome: navigable prototype to validate journeys with stakeholders.
- **Scope:** Console shell (navigation, command palette, split list/record view, dashboard
  placeholder) and portal shell (AI-assistant landing, catalog, my requests) using mock data
  through the real `ui` and `labels` packages; en/ar.
- **Acceptance:** Product owner reviews screenshots of the journeys in both apps (D-008); all text
  via labels; no ManageEngine screens or wording reused.
- **Depends on:** WP-010. Built from the spec with Ant Design defaults (D-008); no designer input
  needed.

## Session log (newest first)

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
