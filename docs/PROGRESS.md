# SupportX v2 — Progress

## Current status

- **Stage:** 0 — Foundation (architecture.md §17). Not started.
- **Last completed:** Project bootstrap (rules, ADRs, plan). No application code yet.
- **Next work package:** WP-001 (Monorepo skeleton and dev tooling).
- **Blockers:** None for WP-001. WP-003 needs the CI platform decision; WP-014 needs the local
  cluster tool decision; WP-015 needs design input (see "Open questions").

### Open questions (awaiting product owner)

1. Confirm which product-plan scope that depends on monitoring data (pre/post change health checks,
   live health on impact maps, NOC wallboards with monitoring status) is still wanted, and whether
   SupportX may *read* health data from a MonetX API (ADR-017).
2. Which roadmap wins on timing: architecture.md §17 (Stage 0 = 3 months; MonetX connector and
   visual workflows in Stage 2) or product-plan.md §10 (Phase 0 = 4–6 weeks; both in Phase 1)?
   Assumed: architecture.md.
3. CI platform (GitHub Actions, GitLab CI, other) and git remote.
4. Local Kubernetes for dev: k3d (matches k3s on-prem) or kind? Neither is installed.
5. Approval for tooling the specs imply but the stack list omits: Rust toolchain + PyO3/maturin
   (licence core), asyncpg, pydantic-settings, Nuitka, OpenFeature SDK, pgvector, PgBouncer, Jinja2, pre-commit.
6. Is migration from SupportX v1 in scope (product-plan.md §8 says yes; architecture.md §18 covers
   only ServiceDesk Plus)?
7. When is Urdu in scope for the definition of done ("Urdu where in scope", §16.3)?
8. Owners for each ADR (all marked TBC).

## Stage 0: Foundation — work packages

Stage 0 outcomes (§17): ADRs signed off; repo, CI/CD, environments; identity, tenancy and RLS;
outbox and event bus; realtime pipeline; design system; licence core prototype; clickable prototype
of console and portal. Each WP is sized for one Claude Code session. Status: `[ ]` todo,
`[~]` in progress, `[x]` done.

### [ ] WP-001 — Monorepo skeleton and dev tooling
- **Goal:** Empty-but-real monorepo matching CLAUDE.md §4, with all quality tools wired.
- **Scope:** `backend/` uv project (Python 3.12, ruff, mypy strict, pytest, import-linter config
  with an empty contracts list); `frontend/` pnpm workspace with empty `apps/console`,
  `apps/portal` and `packages/*` stubs (tsc strict, ESLint, Prettier, Vitest); `deploy/`,
  `licence-core/` placeholders with READMEs; root task runner (Makefile) with `lint`, `typecheck`,
  `test`, `format` targets.
- **Acceptance:** `make lint typecheck test` passes on a clean clone for both backend and frontend
  (with one trivial test each); Python pinned to 3.12 via uv; pnpm via corepack; no dependency
  outside CLAUDE.md §3.
- **Depends on:** —

### [ ] WP-002 — Local dev stack (Docker Compose)
- **Goal:** One command brings up every backing service for local development.
- **Scope:** `deploy/dev/docker-compose.yml` for PostgreSQL 16 (+ pgvector), NATS JetStream,
  Temporal (+ UI), Centrifugo, Keycloak, Redis/Valkey, OpenSearch, MinIO, ClickHouse; named volumes
  prefixed `supportx_dev_`; health checks; `make dev-up`, `make dev-down` (never removes volumes);
  `.env.example`.
- **Acceptance:** `make dev-up` reaches all-healthy on the dev Mac; a smoke script connects to each
  service; ports and credentials documented in `deploy/dev/README.md`.
- **Depends on:** WP-001

### [ ] WP-003 — CI pipeline and quality gates
- **Goal:** Every push runs the §16.2 gates that are meaningful at this stage.
- **Scope:** CI workflow for backend (ruff, mypy, import-linter, pytest) and frontend (tsc, ESLint,
  Prettier check, Vitest); secret scanning; Trivy filesystem scan; caching for uv and pnpm;
  conventional-commit check on PR titles.
- **Acceptance:** Pipeline green on main; a deliberately failing lint/type/test is shown to fail
  the build (on a throwaway branch).
- **Depends on:** WP-001; CI platform decision (open question 3)

### [ ] WP-004 — Backend application core
- **Goal:** Production-shaped FastAPI app with cross-cutting concerns, no business modules yet.
- **Scope:** `app/main.py` app factory; `core/config` (env-driven; pydantic-settings pending approval); structured
  JSON logging with trace ID and tenant ID; RFC 9457 error model with machine codes; liveness and
  readiness endpoints; OpenTelemetry instrumentation hooks; `/api/v1` router; OpenAPI 3.1 export
  script.
- **Acceptance:** App starts against the dev stack; health endpoints tested; an unhandled exception
  returns a problem-details body with no stack trace; OpenAPI JSON exported to a file in CI.
- **Depends on:** WP-001

### [ ] WP-005 — Data layer, RLS and tenancy bootstrap
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
- **Scope:** Keycloak dev realm import (one realm per tenant pattern); BFF login flow (OIDC Code +
  PKCE, HttpOnly session cookie, tokens server-side in Redis); `identity_access` module (users,
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
  Idempotency-Key handling on POST (Redis-backed); cursor pagination; filter DSL v0 (field, op,
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
  `packages/labels` (dictionary, `humanize()` with missing-label warning, en/ar/ur resources);
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
- **Depends on:** WP-009; approval of Rust/PyO3 toolchain (open question 5)

### [ ] WP-014 — Deployment skeleton (Helm and local cluster)
- **Goal:** The same build runs on Kubernetes from day one (§14.3).
- **Scope:** Container images for API, workers, BFF; one Helm chart with `values-dev`,
  `values-single-node` profiles; local k3d (or kind) cluster script; readiness/liveness wired;
  in-cluster Postgres/NATS/Centrifugo for dev.
- **Acceptance:** `make cluster-up && make deploy-dev` installs the chart and the walking-skeleton
  e2e test passes against the cluster.
- **Depends on:** WP-002, WP-004 (WP-012 for the final acceptance run); local cluster tool decision
  (open question 4)

### [ ] WP-015 — Clickable prototype of console and portal
- **Goal:** Stage 0 product outcome: navigable prototype to validate journeys with stakeholders.
- **Scope:** Console shell (navigation, command palette, split list/record view, dashboard
  placeholder) and portal shell (AI-assistant landing, catalog, my requests) using mock data
  through the real `ui` and `labels` packages; en/ar.
- **Acceptance:** Product owner can click through the agreed journeys in both apps; all text via
  labels; no ManageEngine screens or wording reused.
- **Depends on:** WP-010; design input / agreed journeys from the product owner

## Session log (newest first)

### 2026-10-22 — Project bootstrap
- Moved specs to `docs/specs/`. Created `CLAUDE.md`, `README.md`, `.gitignore`, `.editorconfig`,
  `docs/adr/` (ADR-001..017 + index) and this file. Initialised git.
- Environment: Python 3.12 is available via uv (system `python3` is 3.9.6); pnpm, k3d and kind are
  not installed (pnpm can be enabled via corepack).
- No application code written. Next: WP-001.
