# SupportX v2 — Progress

## Current status

- **Stage:** 0 — Foundation (architecture.md §17). In progress: 14 of 16 work packages done
  (WP-014 = part 1 of 4; 014b-d are planned below).
- **Last completed:** WP-020f (resolution, closure, reopen and cancel; D-107), 2026-10-28.
  Before it WP-029-FIX (D-105) and WP-029 parts 1 and 2 (D-097, D-102, ADR-035); WP-021-FIX
  (D-096); WP-021 (D-092, ADR-032); WP-026 (custom fields). Lane B: WP-039 sessions 1-3,
  WP-023 notifications (D-106, in review).
- **Next work package:** lane A: WP-025 session 4 (sessions 1-3 built, #152 merged, #172);
  then the batched QA round (WP-020e + WP-025), WP-028, WP-030, WP-031, WP-032. Lanes: see docs/LANES.md.
  The shared dev stack runs from `../supportx-v2-stack` (main).
- **Other open packages:** WP-015 (clickable prototype), WP-013 (licence core), WP-014b.
- **Speed mode (D-122, until the MVP):** only the fast checks gate merges; e2e, the cluster, PDF and
  worker-resilience jobs run nightly and on PRs labelled `full-ci`. **WP-043 makes the full gate,
  e2e included, required again before the pilot.**
- **Lane C (reports, dashboards and knowledge):** WP-035 sessions 1-4 done (engine #73, viewer
  #77, export #84, scheduled reports #88), on lane A's incident source, e2e in English and Arabic;
  the 1M-row volume test runs in GitHub (`report-scale.yml`; slowest median 0.73 s at 1M). QA
  round done (~/Desktop/qa-wp035, 8 bugs), all fixed in WP-035-FIX (#103). WP-036 dashboards
  merged (#106), free-form layout follow-up (D-110, #115). WP-033 knowledge (plan D-108, moved
  from lane B): session 1 merged (#118); session 2 (review, publishing, withdrawal, trash,
  requesters, notifications) built, waiting for the merge queue; sessions 3-4 next. Lanes and claimed
  numbers: docs/LANES.md.
- **Working mode:** two lanes (MVP build plan): lane A = the WP-020 chain (main folder), lane B =
  WP-018 audit log (done 2026-10-26), then branding (done 2026-10-26, branch `feat/branding`,
  D-078). Lane B's next WP follows the MVP build plan.
- **Blockers:** None. Homebrew, k3d 5.9.0, kubectl 1.37.1, Helm 4.3.1 and Rust 1.99.1 are installed
  on the dev Mac; Docker Desktop has 12 GB (D-038).
- **Repository:** https://github.com/devhat-pm/supportx-v2, **temporarily PUBLIC** (D-018) until
  the account billing problem is fixed; then set back to private (D-015).

### Known gaps

- **Bulk actions on service requests** (QA10V-05, the coordinator, 2026-11-10). REQ-SR-002 gives
  requests the engine's bulk actions, but the API has no bulk route for them and the requests
  list has no row checkboxes or selection bar. It is built in **WP-047a** (SR V1, lane A). Until
  then the list shows no checkboxes at all, rather than dead ones.

### Must fix before the pilot

1. **Workers do not survive a PostgreSQL or NATS restart** (found 2026-10-28; product owner:
   must-fix, before the pilot; **lane B**, next after #99 and the CI follow-ups). The relay,
   fanout and consumers workers exited when the dev PostgreSQL and NATS restarted
   ("database system is shutting down", NATS ServiceUnavailable) and nothing brought them back:
   the shared stack delivered no events for about two hours. Required:
   - workers reconnect automatically with backoff when the database or the message bus goes
     away and comes back, with no lost or duplicated effects (outbox and idempotency hold);
   - a worker that cannot recover exits non-zero so Kubernetes restarts it, and its
     readiness/health check reports unhealthy while disconnected;
   - `/ready` and the admin view show event delivery as stalled, so nobody is left guessing;
   - an automated test restarts PostgreSQL and NATS under a running worker and proves events
     flow again.

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
4. **Lane A's part of WP-040 (agreed with lane B, 2026-10-29), after #131–#134 and lane A's
   queue:**
   - Identity keeps one event, `identity_access.user.status_changed` (v1), with two defaulted
     fields: `reason` (`admin` | `directory` | `erasure`, default `admin`) and `source`
     (`entra` | `ldap` | none).
   - work_items consumes it idempotently (by event ID):
     - `disabled` sets `assignee_inactive_since` on that tenant's open incidents assigned to
       the person, per tenant under RLS, through the service (outbox events, live lists);
     - `active` clears the flag only where they are still the assignee;
     - any reassignment clears it in the normal save path.
   - A built-in view "needs reassignment" with a live count, and a record banner "the assignee
     is no longer active", in en/ar/ur.
   - Pending approvals wait for WP-030.
5. **`sr-only` is not defined** (lane C, 2026-10-29): screen-reader-only column titles in Admin
   › Automation (Triggers, Transitions, Business rules, Routing) and Admin › Organization use a
   class nothing defines, so they are probably visible. Switch them to `.sx-visually-hidden` once
   lane C's header branch lands; check with axe and a screenshot.

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
- **Checklist (product owner, 2026-11-04):** re-enable the pre-upgrade licence check. WP-014b's
  pre-upgrade Job reports "no licence file: check skipped" until the licence core exists (plan
  decision 4); WP-013 must turn that check on, and isn't done until it does.

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
- **Local AI (REQ-AI-003, WP-037; D-139):** the installer **asks** the customer whether to install
  the local AI model, showing the recommended choice (yes). Only when they choose it does it switch
  on `ai.local.enabled` (the chart default stays off), and it records the decision. When
  installed, it ships the pinned weight files in the bundle and fills the model volumes
  (`<release>-llm-cpu-models`,
  `-llm-embed-models`, and `-llm-gpu-models` with a GPU node) at
  `/models/<revision>/<file>`. Air-gapped installs set `ai.mirror: ""`. The servers check every
  file against the chart's pinned sha256 before they start. The images are
  `images.llamaCpp` and `images.vllm`, mirrored like the other third-party images.
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

### [x] WP-020 — Work item engine and incident record (ADR-026; D-051..D-056, D-069; done 2026-10-24)
Contract: docs/specs/parity/01-work-items-incidents.md. Two sessions.
- [x] Session 1 (backend): module `work_items` (shared `work_items` table, type registry,
  per-tenant life cycle / scales / matrix / reasons / categories seeded on first use), incidents API
  `/api/v1/incidents` (list + views + counts, create, get, lookup, edit, actions, assign, take,
  trash/restore, history, assignees, settings, categories), D-052 visibility, D-053 hand-over,
  events, realtime routes, permissions `incidents.*`, labels en/ar/ur, nh3 sanitiser, migrations
  0011–0012, ADR-026; 876 backend tests green (94.8 %), 100k-row list p95 9–66 ms.
- [x] Session 2: console screens (list with views and a notice of what the view leaves out,
  record with fixed actions and tabs, inline edit, create form, assign/take dialogs, reasons,
  hand-over warning, history, trash), Tiptap `RichTextField` (lazy) and `RichTextView`,
  `useDateTime`, `nav.incidents`, pickers with email as the second line, Vitest (13 new) and
  Playwright (3 new; 27/27), reserved `requests.*` relabelled as service requests, Appearance
  popover fix (e2e retry removed), Valkey chart test fix (our smoke pod checks auth; upstream pod
  excluded from `helm test`).
- QA data left in the dev tenant (no delete API for groups and sites yet): support groups
  **QA-Desk A** and **QA-Desk B** and site **QA-Site** (no members). Remove them in WP-021 when
  group and site management arrives. QA incidents INC-21..23 are in the trash.
- Open (D-068, REQ-INC-151, MVP): keep following an incident after handing it over; needs the
  follower model, so it lands with WP-020b. The D-053 warning ships now.

### [x] WP-020b — Conversation, notes, followers, richer editor (D-079, D-080; done 2026-10-26)
REQ-INC-057, 058 (saved, not sent until WP-024), 061, 065, 128, 151 (D-068); REQ-INC-063 and
REQ-WI-006 AC2 (typing) pulled forward from V1. One session (planned two).
- [x] Migration 0016: `work_item_conversations`, `work_item_followers`, `work_item_reply_templates`
  (RLS, no DELETE grant, actor triggers); type settings `keep_following_on_handover`,
  `first_response_on`.
- [x] API: conversation (list, add with Idempotency-Key, make public/private with If-Match and
  audit), followers (follow, add, remove by self/assignee/manager), mentionable people, typing
  signal, personal counters (each also a list view), reply templates (admin, audited). New
  permissions `incidents.add_note`, `incidents.reply`, `incidents.manage_followers`.
- [x] D-068: hand-over keeps following by default (`keep_following`); the follower may view and add
  private notes only, through the policy layer's new `shared_scope` (ADR-026 amendment); removal
  revokes their realtime subscriptions.
- [x] Console: Conversation tab (filters, public/private clearly different, "not sent" notice,
  first-response tag, make public/private with confirmation, typing indicator, composer with
  To/Cc and reply-all/forward), followers card and Follow button, hand-over dialog with
  "Keep following", personal counters on the list, record and create pages use the full width.
- [x] Editor: three heading sizes, palette colours and highlights, logical alignment and indent
  (right in RTL), quote, code block, horizontal line, undo/redo, clear formatting, full screen,
  clean paste from Word/Outlook/web (real lists), @mentions, reply templates; same allow-list on
  the server (`data-*` codes only). Inline images: placeholder in `paste.ts` for WP-022.
- [x] Empty-table text contrast (found by WP-018): shared `EmptyText` used by incidents,
  announcements and the command palette.
- Not done here: notifications for replies, notes, mentions and followers (WP-023, from the
  events); sending replies (WP-024); "pending my approval" counter (WP-030); edit/delete notes
  (REQ-INC-062, V1); sharing (REQ-INC-056 sharing part, V1); overdue/due-today counters change by
  time only every minute until SLA timers (WP-025); the first-response settings screen (WP-020c).

### [x] WP-020b-FIX — WP-020b QA findings (D-081; done 2026-10-26)
Every finding of Desktop/qa-wp020b/QA-REPORT.md has a test named after its ID that failed first.
- [x] BUG-01 readable tags: shared `ToneTag` and palette (`packages/ui/src/tones.ts`), automated
  contrast check for every tone in light, dark (4.5:1) and high contrast (7:1).
- [x] BUG-02 one realtime connection per tab in development (StrictMode) and production
  (acquire/release with a deferred close); a refused or ended channel and a dropped connection are
  shown (`limited` / `reconnecting` banner) and retried with backoff, then refetch what was missed.
  Verified on a production build (`vite preview`) and the dev server: one connection token per
  tab, one channel subscriber, live note received.
- [x] BUG-03 each list item reads in its own direction (view and editor), lists indent per item.
- [x] BUG-04 typing heartbeat (start repeated every 3 s while typing; shown for 8 s).
- [x] BUG-05 full screen fills the window, a click anywhere focuses, Escape works from anywhere.
- [x] BUG-06 counter views show which view is active and how many incidents it leaves out.
- [x] BUG-07 open composers reload reply templates live. BUG-08 follower search ignores stale
  answers. BUG-09 removing a follower who would lose access (or unfollowing it yourself) asks
  first. BUG-10 reply menu opens on click and closes after a choice.
- [x] C1 Arabic hand-over wording; C2 invalid addresses named, no second "required"; C3 mentions
  of unknown users become plain text; C4 singular/plural notice (ar six forms); C5 history word
  gap; C6 group name isolated (bidi); C7 paste into an empty line keeps the first block's alignment.
- [x] D-081: warning before sending a mention of someone who cannot see the incident; the record
  opens on the last-used tab per user (Conversation first). Demo data restored.

### [x] WP-020c — Incident settings screens and templates (D-083; done 2026-10-26)
REQ-INC-035, REQ-INC-006, REQ-INC-007 (V1, pulled forward on request), REQ-INC-009 AC4,
REQ-INC-044 AC4, REQ-INC-045 AC3 (values only, D-056), REQ-INC-047 AC3, REQ-INC-093 (the list),
REQ-INC-017 AC1, REQ-ADM-043, REQ-ADM-045 (incidents), REQ-WI-002 AC4, REQ-WI-009 AC4, Impact
details (REQ-INC-001). One session (planned two).
- [x] Migration 0019 (0018 when built; renumbered after lane B's files migration): `work_item_templates` (RLS, no DELETE grant, actor triggers; one default per
  type), `work_items.template_id`, `level`, `impact_details`; `work_item_reasons` is the pick-list
  table (lists `level` and `closure_code`, optional colour); `work_item_type_settings.seed_version`
  (tenants seeded before WP-020c get levels, closure codes and the standard template on their next
  read, once, race-safe); `users.form_density`.
- [x] API (all admin writes `settings.manage`, If-Match on the catalogue version, field history on
  the settings record, outbox event, audited): status labels and colours, reason prompt per
  transition, scale labels and colours, the matrix (saved whole, a gap refused), pick lists (add,
  rename, colour, retire / bring back, reorder; "Other" kept), next number (never backwards);
  templates (list for `incidents.view`, create, change, copy, default, turn off); create applies the
  template's required fields on the server and refuses a turned-off template; catalogue carries
  retired values (marked) so old records keep their labels. New audit actions
  `incident.template_created` / `incident.template_changed`.
- [x] Console: Admin › Incidents (General: numbering, defaults, automatic steps, first response;
  Templates with editor drawer; Statuses and reason prompts; Reasons; Priority: matrix and scale
  names; Categories tree; Levels; Closure codes; Reply templates, moved out of the composer). New
  incident form: template picker (searchable, grouped, default preselected), switching keeps typed
  values and asks before clearing, hidden fields listed, retired starting values announced,
  template-required fields checked; 3-level category picker with "search all levels" and a
  clearing notice; Level; Impact details; comfortable / compact layout (user preference, also on
  My profile). Record: Level, Impact details, Template; admin names and colours of priority,
  impact and urgency everywhere; retired reasons not offered, unknown codes read "Unknown value".
  Settings changes reach every open screen live (`work_items.settings_changed` in the console
  frame).
- [x] Labels en/ar/ur for every new key (202 each; Arabic plural forms).
- Not done here: REQ-INC-020 (log an incident already resolved) needs the resolution field
  (WP-020f); REQ-INC-011 AC2/3 (no-SLA marker and view) with WP-025; category merge (REQ-ADM-043
  AC3) and reordering categories; the duplicate-name warning (REQ-WI-027 AC2, WP-021); the
  all-record-types numbering page (REQ-ADM-045) once a second type exists; the portal flags take
  effect with WP-028; template life cycle and workflow (REQ-INC-035 last sentence) with the
  designers (V1).

### [x] WP-020c-FIX — WP-020c QA findings (D-086; done 2026-10-26)
Every finding of Desktop/qa-wp020c/QA-REPORT.md has a test named after its ID that failed first
(backend `tests/db/test_incident_settings_qa.py`, Vitest `admin/incidents/qa-wp020c.test.tsx`,
Playwright `qa-wp020c.spec.ts`).
- [x] BUG-01 settings saves are all-or-nothing: `PATCH /settings` takes `next_number` too, checks
  every field first, names every problem at its field (one version step). BUG-02 own saves never
  read as "changed elsewhere" (the api-client remembers the versions this tab made). BUG-03 no
  sideways scroll at 390 px on any admin screen (tables scroll in their own box, app-wide; the
  settings tab bar folds into "more"). BUG-04 transitions in life-cycle order. BUG-05 the copy
  dialog suggests a name in every language from that language's labels (English stays
  required). BUG-06 category tree opens expanded. BUG-07 Reset clears the problem shown. BUG-08
  no null radio value. BUG-09 name dialogs focus their first field.
- [x] C1 numbering problems at their fields; C2 rename starts from the built-in names in every
  language, "No colour" in our words; C3 no colons; C4 "Without a group" (headings only when some
  template has a group); C5 "Other" offers no Retire, with the reason; C6 the tag picker opens only
  while typing (shared `TagsInput`); C7 reply templates: New in the header, "Remove" says replies
  already sent keep their text; C8 records mark retired category and level; C9 a retired starting
  subcategory falls back to its active category.
- [x] D-086 (recorded as D-084, renumbered on merge: lane B's WP-022 answers took D-084): a field the template requires cannot be emptied later (edits and assignment; a field
  made required later blocks only emptying); subject and requester locked "requester can see /
  fill in" with an explanation. Found on the way: a partial field rule sent to the API reset the
  other flags (nested defaults); now only the flags sent change.
- [x] Flaky `qa-fixes` BUG-04 (language after reload): a real race, not only a test one. The
  choice applies at once but its save takes two requests; a reload in between aborted the save
  and the abort cleared the choice. Preferences (language, navigation, form density) are now kept
  in the browser until the server confirms them and re-sent on the next start; only a refusal
  forgets them. The test now runs with a slowed save (1.5 s) and passes; three runs green.
- [x] Dev Keycloak: login theme restored (`docker compose restart keycloak`; the bind mount had
  gone empty); `docs/dev-setup.md` troubleshooting.
- [x] Accessibility: the WP-022 file-scanning banner's link is underlined (axe
  `link-in-text-block`, on every console screen while no scanner is installed). Lane B informed.

### [x] WP-026 — Custom fields for every module (REQ-INC-014; D-087, D-088; ADR-030; done 2026-10-27)
- [x] Definitions in the new `metadata` module (`custom_fields`, RLS, history, outbox,
  audit): 14 types (text, long text, whole and decimal numbers, money with one ISO currency,
  date, date and time in UTC, pick one, pick several as list or buttons, yes/no, email, phone,
  web address, person), names and help in en/ar/ur, choices (a removed choice stays retired),
  validation (required, min/max, lengths, a format pattern; patterns that backtrack
  catastrophically are refused), a starting value, order, retire, remove (a field in use asks
  first, Retire is the recommended answer; values and history stay; keys are never reused).
- [x] Values on the incident as typed JSON (`work_items.custom`), checked by the metadata
  module (people must exist in the tenant), required by the field or by a template (D-086
  rules), recorded in history as `custom.<key>`, filtered through the shared DSL (typed:
  numbers, dates, date-times, multi-choice, yes/no, person) and searchable
  (`work_items.custom_text` in `search_vector`, migration 0021 after lane B's 0020).
- [x] Indexes on request (AC2, D-088): `workers.custom_field_indexes` (its own Deployment, the
  only one besides the migrate Job with the migrator role) builds them every 30 s with CREATE
  INDEX CONCURRENTLY, one at a time; states pending, building, active, failed with a labelled
  reason, live; the migrate Job runs one pass as a fallback. Found on the way: `::date` and
  `::timestamptz` can never be indexed (not immutable); dates and times are now built from
  their parts.
- [x] Console: Admin › Incidents › Custom fields (list, editor drawer, reorder, retire, remove,
  index), the create form (template rules, starting values, required checks, switching
  templates), record properties with edit in place, History labels, template editor rows and
  starting values, one custom field filter in the incidents list; all live.
- [x] Found on the way: a template still requiring a removed or retired field blocked new
  incidents and later template edits; leftover rules are now ignored or dropped.
- [ ] Later (D-087): asset and CI lookups (with their modules); list columns and export
  (WP-020d); portal (WP-028 uses the template's requester flags).

### [x] WP-026-FIX — WP-026 QA findings (D-091; done 2026-10-27)
Every finding of Desktop/qa-wp026/QA-REPORT.md has a test named after its ID that failed first
(backend `tests/db/test_custom_fields_qa.py`, Vitest `customFields/qa-wp026.test.tsx`).
- [x] BUG-01 lost update: an open editor keeps its version; "changed by <name>" at once; the save
  asks (conflict dialog). Same fix in every admin editor that had the pattern: incident settings
  drafts (General, Priority) and rename dialogs (levels, reasons, closure codes, statuses,
  priority values), file rules (also no longer reset while typing), roles. The 409 of a custom
  field names who changed which parts; the field list carries `changed_by` / `changed_at`.
- [x] BUG-02 email, web address and phone values searchable, also by their parts.
- [x] BUG-03 nothing typed is changed silently, app-wide: number inputs no longer clamp or round
  (custom fields, file rules, audit settings, incident numbering), text inputs no longer cut
  (`lengthLimit` counter instead of `maxLength`, 27 inputs); limits refused at the field with the
  limit in the message; a non-whole number gets "Enter a whole number".
- [x] BUG-04 problems clear when the field is edited; BUG-05 names need a letter or digit;
  BUG-06 risky patterns say why; BUG-07 tone tags; BUG-08 problems at their fields.
- [x] C1 Enter adds a choice; C2 choice columns named, choices reorder; C3 "Use at least N
  characters"; C4 separator and isolated names; C5 Arabic "(موقوف)" for fields and choices;
  C6 the type is read-only text when editing; C7 no starting value is SQL NULL.
- [x] D-091 (O5): retired fields under a "Retired fields" heading in the list filter.

### [x] WP-021 — People, sites, departments, groups, desks (D-092; ADR-032; done 2026-10-27)
- [x] The person record (REQ-ADM-002): first and last name (or an own display name), email
  (optional: a contact who never signs in needs none), employee ID, job title, phones, VIP,
  site, department, manager (loops refused), language, time zone, portal visibility override,
  notes. SupportX owns it after the first sign-in (D-092): sign-in records only the time; the
  first sign-in of a person added by an admin or an import links them by email.
- [x] Admin › People: views (active, technicians, requesters, contacts, VIPs, deactivated),
  site and department filters, add, edit (keeps the version it opened; conflict dialog),
  technician or requester (a technician takes a licence seat), sign-in on/off (ends sessions),
  deactivate (keeps records, roles, groups; ends sessions) and reactivate (keeps only the roles
  and groups confirmed). The access drawer is now the person drawer's Access tab.
- [x] Imports (REQ-ADM-003): CSV (UTF-8) and Excel (.xlsx, openpyxl read-only, values only),
  5 MB / 5,000 rows / 40 columns / 5,000 characters per cell, zip "bomb" check; processed by the
  `identity_access__people_imports` schedule in the consumers worker, one savepoint per row,
  progress live; matches by email or employee ID; empty cells change nothing; rows beyond the
  technician seats are refused with the reason. The file is cleared once read.
- [x] Admin › Organisation: sites (details, default site), departments (code unique per tenant,
  site, head, parent), support groups (description, lead, own address and sender name, sites
  served, desk), desks (ESM only; licence limit `desks`, renamed from `departments`, D-092).
  Inactive instead of removed while in use (409 with counts of people, records, members,
  departments, groups); unused ones can be removed; live through `organization.structure_changed`.
- [x] Every record, template and support group belongs to a desk (IT desk by default, D-061,
  D-062). Incidents take the requester's department (and its site); department on the form and
  the record. Deactivated people are marked in person pickers.
- [x] Lane B's WP-039 lookups: `find_department` (code, then English name; active only) and
  `find_site` (name), exported by organization.
- [x] D-073: the technician-visibility question is a tenant setting (`access_settings`), asked of
  role admins in a banner until answered ("their groups" preselected) and changeable in
  Admin › Roles; "everything" widens the technician defaults modules declare at `group`.
- [x] Migration 0023 (after lane B's 0022): desks, departments, group_sites, access_settings,
  people_imports (RLS, isolation tests), person columns, record and template desks; existing
  tenants get an IT desk and a default site. Reversible.
- [x] D-095: the six breaking API changes this WP needs (nullable email, `desks` limit key,
  site and group schemas) are accepted on /api/v1 in `docs/architecture/openapi-accepted-breaks.json`
  until the first external API release; CI enforces the end date flag.
- [x] Removed the leftover QA-Desk A, QA-Desk B and QA-Site from the dev data (in the QA, with the
  new Remove action).
- [ ] Later: the invitation email when sign-in is turned on (WP-024, on lane B's mail sender);
  department and site sync from directory attributes is lane B's WP-039.

### [x] WP-021-FIX — WP-021 QA findings (D-096; done 2026-10-27)
Every finding of Desktop/qa-wp021/QA-REPORT.md has a test named after its ID that failed first
(backend `tests/db/test_people_qa.py`, Vitest `admin/people/qa-wp021.test.tsx`).
- [x] BUG-01 request-validation codes in the app's own words: a missing or null value is
  `required`, Pydantic's `string_too_long` is `value_too_long` with its limit (app-wide).
- [x] BUG-02 too-long values say the limit ("Use at most 200 characters.",
  `errors.field.value_too_long_max`) in people and organisation forms and request checks.
- [x] BUG-03 the person editor follows the record while clean, never takes its own type,
  sign-in or status changes for someone else's, and after a save (also "keep mine", which now
  reads the latest version first) shows the stored record.
- [x] BUG-04 the new-incident form fills the requester's department and site as soon as they
  are picked (never over a value already there).
- [x] BUG-05 phone numbers stay left to right in Arabic (inline style; Ant Design's RTL CSS beat
  the `dir` attribute).
- [x] BUG-06 a type change swaps the system role (no Requester role left on a technician).
- [x] BUG-07 no null select option in the person form.
- [x] BUG-08 (found while fixing) changing a person's site, department or manager failed with a
  500 (field history got raw IDs); an import updating them failed as a whole.
- [x] C1 "Site" column for departments; C2 "N people"; C3 plain "Saved."; C4 (D-096) the
  department's site suggested, never overwriting; C5 making someone a technician asks first (seat).
- [x] docs/LANES.md: three lanes, worktrees, claimed numbers, dev-stack QA lock.

### [x] WP-029 — Business rules, triggers, routing, auto-assignment (D-097, D-102; ADR-035; built 2026-10-27)
New `automation` module (migration 0025); incidents register their rule fields (work_items
`service/automation.py`). Tests: `automation/tests/test_domain.py`, `tests/db/test_automation_api.py`
(31, incl. RLS for 7 tables), Vitest `admin/automation/automation.test.tsx`.
- [x] Business rules (REQ-RUL-001..005, 029): conditions with AND/OR and "changed / changed from /
  changed to", set a field (only if empty / replace) or refuse with an en/ar/ur message; order,
  "stop after this rule", drafts; checked when saved. Run on create, edit, assignment and
  life-cycle moves (rules cannot set the status).
- [x] Order inside the save (REQ-RUL-006): rules → priority matrix → routing → auto-assignment.
- [x] Routing (REQ-ASG-001): ordered routing rules (site-scoped, "replace a chosen group"), the
  category's group, then a fallback group (none by default, D-097).
- [x] Auto-assignment (REQ-ASG-002..006, 011): per group, off by default; round robin (row-locked
  turns) and load balancing (weights 4/3/2/1, loads named); only Available members of the
  record's group; nobody available → stays in the queue with `automation.assignment.waiting` and
  a log entry. On create and on a move to the group.
- [x] Every automated change is a history line naming the rule, method and loads ("why" line in
  the record history); run log `GET /automation/runs` (30 days).
- [x] A group, site, department or custom field a rule uses cannot be removed (REQ-RUL-029 AC3).
- [x] Screens: Admin › Automation (own section: Business rules, Routing and assignment); header
  Available/Away switch for technicians; all live through `automation.changed`.
- [x] Available / Away: in the header from 1200 px, in the user menu below it, and on My profile.
- [x] Follow-up for the WP-029 QA-fix round (product owner, 2026-10-28; done in WP-029-FIX): group leads and admins
  set a member's availability from the person's page or the group's member list, recorded in
  history ("set Away by <name>"), so a sick technician stops receiving auto-assigned work.
- [x] Reporting provider for lane C (WP-035 port): every work item type registers its list query.
- [x] Part 2 (D-102; migration 0028; plan ~/Desktop/wp-029b-plan.md): triggers after commit
  (REQ-RUL-009/010) in the `automation__triggers` consumer, actions set a field (through the
  save path) and add a private note, each in its own savepoint with its outcome on the record's
  Automation tab; loop guard (REQ-RUL-028: depth 5, 20 per record per minute, never on its own
  change; record warning, admins' banner, told once per hour); transition settings
  (REQ-WF-003/004: who may run, offered when, confirmation, "after" actions; 403
  `transition_not_allowed`). Tests: `tests/db/test_automation_triggers_api.py` (12),
  `automation/tests/test_triggers_domain.py` (9), Vitest `automation-part2.test.tsx` (9), e2e
  `automation.spec.ts`.
- [x] Name resolvers for report exports (group, site, department, desk; category path, template,
  incident status and level; custom choices): written by lane C in lane A's modules, reviewed by
  lane A, merged with #84 (2026-10-28).
- [ ] Kept drafts (REQ-INC-019, REQ-SEC-029 AC2): the new-incident form keeps its input through a
  timeout (lane B, #87). The record page's in-place edits and the reply/note composer follow in
  WP-020d/e (lane A).
- [x] QA round on main (2026-10-28, ~/Desktop/qa-wp029/QA-REPORT.md): 14 e2e journeys pass;
  5 bugs (refusal message shows `{{message}}` and twice; editor problems don't name the field;
  Arabic plural forms fall back to English; automation conflict dialog doesn't say who/what)
  and 4 cosmetic notes, for WP-029-FIX.
- [x] **WP-029-FIX** (2026-10-28, D-105; branch `fix/wp-029-qa`). One test per finding, named
  after its ID:
  - BUG-01 rule refusal showed `{{message}}`: the error describer passes params for every code.
    Tests: `packages/ui/src/qa-wp029.test.tsx` (every `errors.*` placeholder filled, en/ar/ur),
    `backend/tests/test_error_label_params.py` (every raise site sends its labels' params, CI),
    e2e `qa-wp029.spec.ts` (a real rule refuses a save on screen, nothing mocked).
  - BUG-02 refusal twice as error toasts: refusals at the form (`FormProblem`) in every editor,
    neutral notice for one-click actions, each error shown once. Tests: `qa-wp029.test.tsx`
    (incidents), `qa-wp029-refusals.test.tsx`, ui `qa-wp029.test.tsx`, the e2e above.
  - BUG-03 editor problems name and mark their field (automation editors). Test:
    `automation.test.tsx` "BUG-03".
  - BUG-04 Arabic plural forms: CI check `packages/labels/src/plurals.test.ts`; all 20 counted
    labels fixed across the app.
  - BUG-05 conflicts name who, when and which fields: `app/shared/history/conflicts.py`
    (`stale_version`) for every version check; every editor opens the shared dialog. Tests:
    `tests/db/test_conflict_details_api.py`, `automation.test.tsx` "BUG-05",
    `qa-wp029-conflicts.test.tsx`.
  - C1 "Hand over this incident?": `qa-wp029.test.tsx` "C1". C2 who may run a move:
    `test_automation_triggers_api.py` "c2", `qa-wp029.test.tsx` "C2". C3 rule, routing and
    assignment steps on the Automation tab: `automation-part2.test.tsx` "C3". C4 leftover QA
    custom fields retired in the dev data (see the session log).
  - Availability follow-up: `test_automation_api.py` "follow_up", `automation.test.tsx`
    "follow-up" (lead's card on My profile; also the person page and the group editor).
- [ ] Later: "test against an existing record", drag-and-drop ordering (buttons for now),
  notification / approval / task / webhook actions with their WPs.

### [x] WP-020f — Resolution, closure, reopen and cancel (D-107; built 2026-10-28)
- **Plan:** ~/Desktop/wp-020f-plan.md (approved 2026-10-28, with the product owner's auto-close
  rule). Migration 0034 (after WP-023's 0033).
- [x] REQ-INC-090: resolve takes a resolution (sanitised rich text, required by default); shown
  on the record. Deferred: knowledge search in the editor (WP-033), worklog in the same step
  (WP-020e).
- [x] REQ-INC-093/094: close takes a closure code (seeded list, translations, retire); closure
  rules per type (fields required before resolve and before close, standard and custom) on the
  one move path (record, API, automation; bulk and e-mail reuse it); 422 `closure_rules` with
  field errors; each action says what the record still lacks; lists filter by closure code.
- [x] REQ-INC-095: open-work port (tasks, checklists, child incidents from WP-020e; approvals
  from WP-030 register their checks): warn with an explicit, recorded confirmation (default) or
  block (default for approvals); "complete on close" setting.
- [x] REQ-INC-096: the requester confirms (closes; closure code "fixed" when one is required and
  none was set) or rejects (reopens, comment as their public reply) through
  `/resolution/confirm|reject` (portal WP-028 and e-mail links WP-023 call them). Auto-close
  after N business days (Monday to Friday until WP-025 calendars) counts **only from when the
  requester was told** (`resolution_notified_at`, set by the channel that told them); off by
  default and refused while no channel reaches requesters (product owner, 2026-10-28).
- [x] REQ-INC-097: reopen keeps the earlier resolution, closure code and times in history; the
  current values clear so the next resolve asks again; reopen count filterable.
- [x] REQ-INC-051/098: a requester's public reply resumes "awaiting requester" (per-status
  switch; third party unchanged); within the reopen window (7 days, 1–30) it reopens; after it a
  new record follows the old one (`follows_id`) and the answer names its ID.
- [x] REQ-INC-100: cancel with a reason and undo were built in WP-020; a canceled record takes
  no edits (test added).
- [x] Port for e-mail and the portal: `work_items.add_requester_reply` saves a requester's reply
  from outside the console (requester or on-behalf-of only) and runs the reactions above; an
  automatic reply (out-of-office) is recorded and moves nothing (`automatic` on the event).
- [x] Follow-up (lane C's #103): lane A's hand-joined visible lists moved to `useListFormat` /
  `useJoinParts`, with a guard test (`packages/labels/src/list-joins.test.ts`; #111).
- [x] Migration 0034's data step ran without a tenant and changed nothing under FORCE RLS (lane
  C's finding); it now loops per tenant (#116, `tests/db/test_closure_migration.py`).
- [ ] Wired by later packages: requester notified (`resolution_notified`, WP-023/024/028),
  confirm/reject links (WP-023), e-mail replies (WP-024), tasks and links (WP-020e), approvals
  (WP-030), knowledge search (WP-033), working calendars and SLA resume/restart (WP-025).
- Tests: `tests/db/test_closing_api.py` (17, named after the criteria),
  `work_items/tests/test_closure_domain.py` (8), Vitest `pages/incidents/closing.test.tsx` (15),
  `pages/admin/incidents/closing.test.tsx` (7), `businessDays.test.ts` (2), e2e
  `closing.spec.ts`.
- Screens: one move dialog (reason, resolution, closure code, what the record still lacks,
  open-work confirmation); resolution and closure code on the record with "closes on …" or
  "waits until the requester is told"; history and why-lines in words; Admin › Incidents ›
  Closing (closure rules, open work, auto-close disabled with the reason while no channel
  reaches requesters, reopen window); "a requester reply resumes it" on paused statuses.

### [x] WP-020d — Views, columns, bulk and export (D-111, approved; built 2026-10-28; QA and fix round 2026-10-29)
- **Plan:** ~/Desktop/wp-020de-plan.md (approved 2026-10-28). Migration 0038 (after lane B's 0037 mailboxes, lane C's 0036 knowledge and
  0035 dashboards): `work_item_views`, `work_item_list_settings`, `work_item_bulk_jobs` (RLS,
  actor audit, isolation tests) and `field_changes.batch_id`. Draft PR #114.
- [x] REQ-INC-104: column chooser over every list field (custom fields as `custom.<key>`, system
  times), reorder by buttons, resize on the header (mouse or arrow keys), sort by any sortable
  column on the server; saved per user per view. List rows carry custom values and more fields.
- [x] REQ-INC-105/152: built-in views overdue, due today, followed by me, shared with me, from my
  direct reports; each tested against its definition, with live counts. Deferred: pending
  approval (WP-030), the type filter (WP-031).
- [x] REQ-INC-106: saved views (private, chosen groups or everyone; D-111 as approved) built with lane C's FilterBuilder; "apply
  without saving" changes only the screen; the saved filter is the list API's `filter` as is.
- [x] REQ-INC-108: time range (created, updated, due, resolved; presets and custom; quarter exact
  in the user's zone); the active range names its field.
- [x] REQ-INC-109: search chips from suggestions ("Status is Open"), no syntax; results in place.
  (The search panel over the current screen is WP-027's palette.)
- [x] REQ-INC-110: page size 25/50/100, saved with the view's settings.
- [x] REQ-INC-119/120: select rows, the page or "all N" (frozen when the job starts, ≤1,000);
  actions disabled with the reason until something is selected; bulk edit (only ticked fields),
  assign, take, resolve, close as a background job in the consumers worker, as the requester;
  per-record results with reasons in words; live progress; "Bulk changes" keeps results;
  history names the job; lists refresh once per batch.
- [x] Export through lane C's report export (`content: records`); built-in views travel as their
  filter equivalents (`GET /incidents/view-filters`, each tested to return the view's rows).
- [x] Export columns and sort: the file has the list's columns and sort (lane C's #108).
- Tests: `tests/db/test_list_views_api.py` (13), the new-views test in `test_incidents_api.py`,
  Vitest `pages/incidents/list/list.test.tsx` (7), e2e `incident-lists.spec.ts` (runs at QA).

### [ ] WP-020e — Tasks, worklogs and links (D-112, approved; built 2026-10-28, QA next)
- **Plan:** ~/Desktop/wp-020de-plan.md (approved 2026-10-28). Migration 0039 (after WP-020d's
  0038): `work_item_tasks`, `work_item_worklogs`, `work_item_links` (RLS, actor audit, isolation
  tests), `task_owner_access`, and `follows_id` copied into `follows` links per tenant. Draft PR
  #120 (stacked on #114).
- [x] REQ-INC-072: tasks with their own status, owner, group, priority and due time; "done /
  total" on the tab, live; reorder by buttons, saved for everyone; open tasks are open work for
  resolve and close; task-only owner access (off by default) with `/incidents/my-tasks`.
- [x] REQ-INC-067: worklogs (owner, type, start, end or duration, description); the end is never
  before the start; start + duration fills the end and back; totals per person and type, live.
- [x] REQ-INC-084: related links shown and recorded on both records, removable from either side;
  a record you cannot see shows as a link without its ID or subject; follow-up records are
  `follows` links.
- [ ] Deferred: child incidents (REQ-INC-095) with parent/child links; "log time in the resolve
  step" (REQ-INC-090 AC3) in the move dialog; admin-editable worklog types; the `follows_id`
  contract step.
- Tests: `tests/db/test_parts_api.py` (9), `test_parts_domain.py` (3), the follows link in
  `test_closing_api.py`, Vitest `parts.test.tsx` (3), e2e `incident-parts.spec.ts` (runs at QA).

### Planned after WP-020 (sequence from the WP-020 plan)
WP-020b conversation, notes and followers · WP-020c incident settings screens and templates · WP-020d views
and bulk · WP-020e tasks, worklogs (time) and links · WP-020f resolution and closure · WP-021 people
and departments · WP-022 files (aioboto3, D-054) · WP-023 notifications · WP-024 email channel ·
WP-025 SLA v1 with Temporal (D-055; needs parity file 03) · WP-026 custom fields · WP-027 search ·
WP-028 portal incidents (needs parity file 02). Open item from D-052: the first-run setup must offer
"technicians see all incidents" vs the group default.

**WP-028 follow-up (2026-10-29, coordinator; from `fix/requester-file-access`):** requesters may
not join the staff record channel `t:{tenant}:wi:{id}` (correct: it carries private-note and
internal events), so today they get no live updates on their own incident. The portal needs a
requester-scoped live channel per record, joined only by its requester or the person it is for,
that publishes **public-entry events only**: public replies and their files, status and
resolution changes the requester may see; never private notes, internal fields or their files.
Same rules as the files access (D-052): out of scope is a refused join. Portal screens patch from
it with no reload (rule c). Not built yet.

### [ ] WP-032 — Portal: home, catalog, approvals inbox and preview (lane A, 2026-11-05; 3 sessions; #220)
- **Plan:** ~/Desktop/wp-032-plan.md (coordinator approved 2026-11-05; 3 sessions). Numbers:
  0096, 0097, D-143.
- **Decided (D-143):**
  - the portal's own settings live in work_items (one row per tenant);
  - most requested counts the last 90 days;
  - bulk approve takes at most 20, approve only;
  - the decided list covers 30 days.
  - Lane C asked me to build announcement dismissal and follow in their module (reviewed,
    approved).
  - Preview as a person (S3) waits for Haider's OK on the conditions the coordinator listed
    (dedicated permission and MFA, read-only on the server, a banner, a time limit, audited,
    nothing notified).
- [x] Session 1 (#220):
  - The home (REQ-PRT-002): the greeting with the search box, three starting points, a live
    summary (`GET /portal/summary`: my open requests by status, approvals waiting, open tasks),
    featured then most requested items (`GET /catalog/items/popular`, through a new
    request-count port), and the announcements.
  - One search box (REQ-PRT-003): items, articles, announcements and my requests, each from its
    own search, in groups. With nothing found, a report with the words as its subject.
  - Cards say "needs approval" (unless hidden from requesters).
  - After submitting (REQ-PRT-006): whose approval it waits for, when to expect it (shown due
    times only), and links.
- [x] Session 2 (#220, 0096, 0097):
  - Bulk approve (REQ-PRT-008): ≤ 20, one comment, a confirmation that names each request, each
    one a decision of its own (audited). There is no bulk reject. The decided list covers 30
    days, and delegated approvals are marked.
  - Portal settings (REQ-PRT-031): `work_item_portal_settings` (RLS; search sources and order,
    profile editing, reminders; audited with old and new values; live). Admin › Portal shows
    every portal setting in groups, each saved where it lives, with the later ones marked.
  - Attachments on the catalog item form (REQ-PRT-005).
  - Announcements (REQ-PRT-009):
    - dismissed on every device (stored, per person);
    - follow and unfollow;
    - followers are told of updates and the end through the one notification engine, with the
      audience checked at send time.
  - Not yet (recorded):
    - the item cards' expected delivery and price wait for item cost and SLA estimates
      (WP-047);
    - related articles and the help card on the item page wait for WP-034's portal knowledge
      (lane C), which also brings the portal's article page (search shows titles until then);
    - expiry has no event yet, so followers hear of unpublish and archive only (lane C's
      WP-062b);
    - the acknowledgement e-mail's "what happens next" text needs lane B's template (REQ-PRT-006
      AC3);
    - REQ-PRT-031's preview links come with S3.
- **Shipping (2026-11-05):** S1-S2 merge through the queue as #220 (stack smoke green, run
  41944547602; 0096 now follows 0092). The coordinator approved this exception to one PR per
  WP because S3 is blocked on a decision.
- [ ] S3 preview as a person (REQ-PRT-032): **open, waiting for Haider's OK** of the conditions.
  It ships as its own PR once approved; lane B builds the read-only preview session.

### [ ] WP-044a — Problems: record, creation, templates, statuses, assignment (lane A, 2026-11-05; 5 sessions; #211)
- **Plan:** ~/Desktop/wp-044-plan.md (all of WP-044, 13 sessions; coordinator approved
  2026-11-04). Numbers: 0076, 0077, 0089 (044a), 0078 (044b), 0079 (044c), ADR-040
  (investigators widen record access).
- **Decided (D-140, Haider 2026-11-05):**
  - Q1: closing offers "Resolve linked incidents", ticked by default, each through its own
    service;
  - Q2: one causing problem per incident (built, S3);
  - Q3: target dates plus a tenant switch for full SLAs;
  - Q4: review required for major and P1, P2 optional;
  - Q5: an upgrade prompt in Essentials;
  - Q6: AI grouping wherever the local model runs, pg_trgm without AI;
  - Q7: the root cause is for problem roles only (API and search), admins can widen it;
  - Q8: the React Native app is V1, built by Extravis's mobile team; every 044 feature goes
    through the public API.
  - Q3's switch goes in S5; Q4 in 044b S4; Q1 in 044b S5; Q7 in 044b S1 and 044c S2; Q5 and
    Q6 in 044c S3; Q8 is checked in 044c S3.
- [x] Session 1 (#211):
  - Problems as a registered work-item type: PRB counter, `/problems`, licence feature
    `problem`, custom fields for problems.
  - The Appendix A life cycle with the actions investigate, confirm_root_cause, await_fix and
    hold. On hold resumes where it was put on hold (`status_before_pause`, the same way as
    undo-cancel).
  - Each type lists only its own life cycle's actions (fixed when an incident listed the
    problem actions).
  - `problems.*` moved from identity's reserved list into work_items (lane B agreed; lane B
    reviews):
    - technicians: view and create all, and work their groups' problems;
    - delete stays with the admins.
  - Migration 0077 maps saved roles: problems.manage(S) becomes create, edit, assign and close
    (never delete).
  - Tests: domain (life cycle), DB (API, permissions, RLS, the 0077 migration and a role still
    editing group problems).
- [x] Session 2 (#211, migration 0089):
  - problems have their own priority matrix (the per-type seed copies the incident one);
  - problem type (reactive / proactive) and root cause category, from admin-editable pick lists
    seeded for problems (Appendix A);
  - the outage window (the end not before the start);
  - target dates on the SLA engine: resolution only, P1 5 to P4 40 business days, no first
    response; pausing and escalation as for incidents;
  - problem-only fields refused on other types; field history; labels en/ar/ur.
- [x] Session 3 (#211, 0089 extended): creating problems.
  - From an incident: prefilled (subject, description, impact, urgency, site, the same seeded
    category; reported by the creator) and linked "caused by" on both records with history.
  - From many incidents: the already-caused ones are listed first and moved only when
    confirmed; the others are linked by an incidents bulk job (`link_problem`, ≤ 1,000).
  - An incident has at most one problem (partial unique index); a second gives 409
    `incident_has_problem` unless moved.
  - Similar open problems while typing (search port, visible ones only).
  - Copy with the fields, a title marked with the original's ID, retired values left empty and
    named, and history naming the original.
  - Record links show caused_by / causes and the other record's type, checked against that
    type's own permissions.
  - Not yet (recorded): copying attachments (REQ-PRB-011 AC3), and the analysis and solution
    parts of a copy (their fields come in WP-044b); creating from changes, releases, CIs and
    reviews (REQ-PRB-013) waits for those records.
- [x] Session 4 (#211, 0089 extended): named life cycles and the major problem template.
  - A type can seed more than one transition set on its statuses. A template chooses one, and a
    record keeps the one it was created with (`lifecycle`).
  - Problems get "guided_analysis" (REQ-PRB-025): gathering facts, why-analysis, cause
    confirmed, fix planned, fix verified, in review, closed. There is no close before the
    review.
  - New tenants get the standard and major problem templates (REQ-PRB-017 AC1).
  - Not yet (recorded):
    - the analysis and solution sections, and "cause confirmed needs a root cause", come with
      the WP-044b S1 fields;
    - template tasks on entering a status (REQ-PRB-020 AC2), template groups (REQ-PRB-021) and
      the designer's explanations (REQ-PRB-022) are console work for S5;
    - copying and editing a life cycle (REQ-PRB-025 AC3) comes with the life cycle designer.
- [x] Session 5 (#211, 0089 extended; ADR-040):
  - Investigators (REQ-PRB-029): a follower row with reason `investigator` and access.
    - They see the problem and add notes, work its tasks, and log their own time (lane B's
      review: never others' worklogs).
    - Fields, status, assignment and links stay closed to them.
    - Named or removed by whoever may edit the problem; anyone may step down.
    - Audited and in history. The record channel follows the access.
  - Full SLAs on problems (D-140 Q3): `sla_settings.full_sla`, off by default. While it is off
    only the target date counts, and response targets are refused on save.
  - Console screens:
    - the problems list (live), and creating a problem from an incident or from many (the
      already-caused ones to move or leave), with similar problems while typing;
    - the record, with the incidents' status bar, the guided steps, the incidents it causes,
      investigators and copy;
    - "Create problem" on incidents.
  - Lane B's review of 0077: the downgrade refuses rather than lose a grant.
  - Audit labels for every service_request.* and problem.* action.
  - Stack smoke dispatched with the new e2e spec (problems.spec.ts).
  - Not yet (recorded):
    - an assign dialog and a technician picker on the problem page come with 044c S1's record
      page (assignment works through the API and the list);
    - the analysis, tasks, worklogs and conversation tabs come in 044b and 044c;
    - template groups and designer hints (REQ-PRB-021, -022) go to 044c S1;
    - creating from many incidents through the incident list's bulk bar goes to 044c S1 (the
      URL form works now).
- WP-044a is complete once #211's full-ci is green; it then leaves draft.

### [ ] WP-044c — Problems: lists, views, permissions, notifications, detection (lane A, 2026-11-06; 3 sessions; #240)
- **Paused** for the product owner's full QA stop (2026-11-06). The resume point is in
  docs/lanes/A.md.
- [ ] S1 (in progress):
  - done: the views "known errors" and "accepted, due for review"; Tasks, Worklogs and History
    tabs on the problem page (the parts and history hooks take the type's prefix); the list's
    views with counts, one search for words or a PRB number, ellipsis and sticky ID/subject;
    print a problem; assign its group and owner (the incident's dialog with the problems'
    rules and assignees); "Create problem" from the chosen incidents in the bulk bar;
  - next: REQ-PRB-021 templates limited to groups (one migration, number asked); REQ-PRB-022
    the problem admin area and designer hints, on lane C's shared settings layout (#258) once
    it lands.
- [x] S2 (D14, D15), on #240:
  - the causing problem on an incident, narrowly, for every technician (REQ-PRB-071):
    `GET /incidents/{id}/causing-problem` and the "Caused by a problem" card, never the root cause;
  - the built-in `problem_manager` role (Appendix A; lane C's review), made per tenant on demand
    (no data migration);
  - problem notifications on the engine (lane B's review): assigned, investigator added, known
    error and solved (to the linked incidents' technicians), target date, mentions; no event is
    public;
  - requesters told "known and being worked on" or "fixed" on their portal incident
    (REQ-PRB-075), never the problem;
  - the problem report source's own fields and names; measures and widgets are lane C's WP-063;
  - not yet: the requester-facing workaround (REQ-PRB-040, waits for lane C's WP-034 portal
    knowledge).
- [x] S3 (D16, D17), on #240:
  - repeat incident rules without AI (REQ-PRB-068, migration 0110): the 15-minute evaluator
    (one open set per rule and key, members capped, a handled set returns only for new
    incidents), the problem module's (not in Essentials), the group told once, the problems
    list's "Repeated incidents" card, Admin › Incidents › Repeated incidents (locked through
    the shared featureState for licence managers outside the plan);
  - D17: every problem operation in the public API (a contract test); the mobile app itself
    stays a cross-lane question;
  - en/ar/ur for every new screen; Arabic e2e with axe for the causing problem, the rules and
    the list at 390 px;
  - not yet: the rules screen and REQ-PRB-022's admin area on lane C's settings layout (#258).

### [x] WP-044b — Problems: analysis, links, known errors, tasks, closure (lane A, 2026-11-05; 5 sessions; #222)
- **Plan:** ~/Desktop/wp-044-plan.md (D8..D12). The branch starts from #211's head; main is
  merged in once #211 lands. Migration 0078 (already allotted in the WP-044 numbers).
- [x] Session 1 (#222, 0078): analysis, evidence and impact (REQ-PRB-030, -032, -033).
  - Root cause and symptoms on problems (rich text, sanitised; each save is one history entry).
    Changing them needs `problems.edit_analysis`.
  - Reading the root cause needs `problems.view_root_cause` (D-140 Q7). Without it:
    - the record says `root_cause_hidden`;
    - the history leaves the change out;
    - the console shows it locked, never empty.

    Technicians hold both rights for their groups' problems, and admins can widen them. Search
    and notifications never carried the root cause.
  - Who last changed each field, and when (from the field history).
  - Confirming the cause (`confirm_root_cause`, standard and guided) needs a root cause written.
  - `GET /problems/{id}/impact` counts over the caused incidents the reader may see:
    - open, by priority and site, people, worklog time;
    - total time open;
    - an 8-week trend;
    - `partial` when some incidents are left out.
  - `GET /problems/{id}/evidence`: the caused incidents by report time. Changes, releases and
    other problems on the same items are named as not yet available, never faked.
  - Console: overview, analysis and evidence tabs, live on the record channel; labels in en, ar
    and ur.
  - Not yet (recorded):
    - impact by service and CI, and the evidence from changes, releases and the same items,
      wait for WP-045, lane C's releases and lane B's CMDB;
    - cost waits for worklog costs (D-047);
    - copying the analysis with a problem (REQ-PRB-015) comes with S3's known errors.
- [ ] S2 links and merge (in progress, 0104):
  - done:
    - merge with undo: `merged` status, incidents move, undo leaves since-moved ones and names
      them;
    - unlinking incidents, one at a time or in bulk (`unlink_problem`);
    - related problems through the generic link;
    - the `merged_into` / `merged_from` relations;
    - console: unlink buttons, related problems, a Merge into dialog, a merged banner with undo.
  - Not yet (recorded):
    - `fixed_by` (to changes) and `released_in` (to releases) stay hidden until those types
      register (WP-045, lane C's releases);
    - an announcement from a problem waits for lane C's WP-062b: `POST /announcements` takes
      `source: {type, id}`, and the console prefills the title (agreed, rule 8).
  - **Gap on record (D-140 Applied):** the generic link delete could remove an incident's cause
    with problem edit alone (since WP-044a). The fix (409 `link_has_own_route`) ships as its own
    small PR from main after #211 lands; it is not held for this WP.
- [x] S3 known errors (0078 extended, still unmerged):
  - The workaround, under `problems.edit_solution`. Incident technicians see it.
  - The known error flag, under `problems.mark_known_error`:
    - marking needs a workaround or root cause written (422 names both);
    - removing needs a reason;
    - both are in history.

    The menu has one action that flips in place.
  - Resolving a known error retires it, in the same save and history entry.
  - Every linked incident shows the marker, live. The incident listens on its problem's
    channel.
  - The known error database:
    - `GET /problems/known-errors` and the console page;
    - it searches subject, symptoms and workaround, never the root cause;
    - retired ones are marked, and it updates live.
  - Suggestions in the incident's editors: "apply the workaround" links the incident to the
    problem and inserts the workaround at the caret, without sending.
  - Problems join the record-facts port, so knowledge works for them: article links
    (REQ-PRB-035) and "save the resolution as knowledge" (REQ-PRB-041).
  - 0078's downgrade refuses while any tenant has data.
  - Fixed on the way: incident links to a problem opened `/incidents/<id>` (since WP-044a).
  - Not yet (recorded):
    - Publishing the workaround as a technician article that follows the problem (REQ-PRB-039).
      Lane C agreed the shape: from-record `part: workaround`, a facts-port `workaround_of`,
      staff-only, and a work_items event for the review task. It lands in their WP-060, or
      sooner if I send the port change.
    - Portal known issues (REQ-PRB-040) and withdrawing them on retirement (REQ-PRB-042 AC2,
      AC3) wait for lane C's WP-034 portal knowledge.
    - Recording whether a suggestion was used (REQ-PRB-038).
- [x] S4 work on the problem (0078 extended):
  - The review (REQ-PRB-053): summary, lessons and actions. Closing needs the summary for major
    problems and the priorities in `review_required_priorities` (P1 by default, D-140 Q4); the
    close action lists it as missing.
  - Approvals on problems through the WP-030 engine:
    - `POST /problems/{id}/approvals` asks named people (`problems.approve`);
    - the engine's list, inbox and decision routes serve problems, with no withdrawal;
    - a decision sets the approval status, never the problem's status;
    - an approved `accept_without_fix` sets `accepted_at` and a review date 90 days ahead
      (REQ-PRB-050).
  - Messages (REQ-PRB-052):
    - recipients by set (followers, the linked incidents' technicians or requesters, visible
      incidents only);
    - one message to the requesters, sent as a reply on each linked incident, with the problem's
      history naming them.
  - Console:
    - the review section;
    - Ask for approval and the approvals list with decisions;
    - Message the affected requesters.
  - Not yet (recorded):
    - The tasks, worklogs and conversation tabs on the problem page are 044c S1's record page
      (the engine routes already serve problems).
    - Stopping worklogs on closed problems (REQ-PRB-051).
    - The admin control for `review_required_priorities` (API only for now).
    - A "due for review" view for accepted known errors (044c's views).
- [x] S5 closure and follow-up:
  - Pending approvals block closing (409 `approval_pending`, REQ-PRB-054).
  - Follow-up on linked incidents (REQ-PRB-055, D-140 Q1):
    - `GET /problems/{id}/follow-up` lists the open linked incidents the technician may see;
    - `POST` resolves the chosen ones (unticked ones stay) through the incidents' own bulk
      resolve job, so each one's transition and closure rules apply;
    - each gets the resolution, the workaround or both, lands in resolved for its requester to
      confirm, and its history names the problem.
  - Console: a follow-up dialog, ticked by default, with the bulk drawer showing progress and
    results live.
  - e2e (problems.spec.ts):
    - the analysis tab, written in place and live;
    - a linked incident moving the impact and evidence;
    - a known error showing live on its incident and found in the database.
  - Not yet (recorded):
    - Close conditions on linked changes and releases (REQ-PRB-054) wait for those types.
    - Problem-specific closure codes (REQ-PRB-056) use the shared closure code list for now.
    - The tenant defaults for the follow-up (notify, copy as a note) beyond Q1's resolve.

### [~] WP-045b — Changes: risk, advisory boards, approvals, re-approval (lane A, 2026-11-10; 4 sessions; backend; PR after #299)
- **Plan:** ~/Desktop/wp-045-plan.md D8-D11, approved by the coordinator. Migrations 0116-0118.
  Haider's decisions of 2026-11-10 (SoD default, optional members, sending back) and D-144.
- **S1 risk (0116):** levels low to very high; a scored questionnaire per template (Appendix A by
  default, versioned); rules may raise it; a person's override always needs a reason.
- **S2 advisory boards (0117):** `/api/v1/change-boards`, with two seeded boards per tenant
  (default, emergency) and no members. An admin's board needs at least one member, and the
  default board can't be removed. Each board has a mapping (types, risk levels, sites,
  templates), an order and a rule (any, all, majority, majority with the chair). Tenant
  isolation is tested for both tables.
- **S3 approvals:**
  - a level may name the mapped board or a specific one; the rows record which board and why;
  - a board with no members goes to the approval administrators (`board_has_no_members`);
  - strict segregation of duties is a tenant setting (audited);
  - a submit-time preview names who is left out;
  - every fallback is audited (`change.approval_rerouted`);
  - admin guide: docs/guides/change-approvals.md.
- **S4 re-approval (0118):**
  - each approved stage's window, risk and plans are kept; `changes-since` lists, field by
    field, what changed since approval;
  - the tenant policy (restart, notify or ignore, with a tolerance) decides;
  - a restart sends the change back to the stage's raising status by an audited system move,
    with a warning preview first;
  - optional members' votes are advisory and never counted;
  - the emergency override (D-144) needs a permission and a reason, is audited, and makes the
    review mandatory;
  - notices are recorded in the outbox for WP-056.
- **Not yet:**
  - sending the notices (WP-056);
  - the chair's tie-break (lane C's WP-048b S2 wires `chair=`);
  - CIs and services in the snapshot (with the CMDB);
  - the screens (UI pass 3 templates).

### [x] Change screens — taken forward from WP-045d D19 (lane A, 2026-11-11; the coordinator; 4 sessions, 2 PRs)
- **PR 1 (S1+S2, no migration, #372, merged):** the changes list on template C (path, stage, status, the
  emergency flag, a Pending approval view); a new change on template B (prefilled when raised
  from another record), opening on its risk questionnaire; the record on template A (stage rail
  and moves, properties, details with a risk override that says why, the questionnaire, roles,
  plans, schedule and downtime read-only, history). The staged parts' hooks by type
  (`api-client/staged.ts`) and one move dialog for staged types (`pages/staged`, lane C's split).
- **PR 2 (S3+S4, no migration):**
  - the Approvals tab: each approval's board and why, advisory votes, the administrators'
    fallback, decisions with If-Match, and what changed since approval;
  - the move that raises a stage shows who would approve and who is left out (the preview now
    names them);
  - a new risk that sends approved stages back says so before saving;
  - the emergency override (D-144), only on a change sent back (`sent_back` on its details);
  - a stage's outcome on the Schedule tab;
  - change advisory boards on template E (`/admin/change-boards`, `changes.manage_boards` or
    `settings.manage`), whose people come named;
  - QA flow 4 end to end in Playwright, and walked move by move over the API.
  - **Fix:** a move says where it lands (`lands_in`), so a move that closes a change after
    an automatic advance ("Review complete") asks for the closure code. Before, a change
    could not be closed from the console.
  - Lane B gives the blocking review (D-149).
- **Not yet:**
  - risk and type columns on the list (not in the list API);
  - conversation and attachments on the record;
  - labels for questions an admin adds to a template's questionnaire (only Appendix A's are
    labelled);
  - editing schedules and downtime (WP-045c);
  - a "failed" outcome's issues text (the server asks for it; the select has no field for it
    yet).

### [~] WP-045c — Changes: windows, conflicts, calendar (lane A, 2026-11-11; 3 sessions; ADR-042; migration 0132; D-156 held)
- **S1 (backend, 0132):**
  - freeze and maintenance windows, `/api/v1/change-windows`, with block/warn, a weekly repeat
    and a site/group/service/CI scope;
  - one pure conflict check (freeze, outside maintenance, overlapping changes in the same group
    or at the same site);
  - a guard on every save of a change's implementation window or planned downtime
    (409 `change_window_blocked`);
  - `GET /changes/{id}/conflicts`;
  - the freeze override (`POST /changes/{id}/freeze-override`: `changes.override_freeze` at the
    change's scope, a reason, audited, in history);
  - `changes.manage_windows` (the change manager and admins);
  - live via `work_items.change_windows_changed`.
  - Defaults per D-156 (held): a freeze blocks, a maintenance window warns, weekly repeat only.
  - Lane B gives the blocking review.
- **S2 (built; its PR opens after #376):**
  - the record's Schedule tab, with the editable implementation window and downtimes and a live
    conflicts panel;
  - the override dialog, which passes only the freezes named, then retries the save;
  - "announce" for a planned downtime, which makes an announcement draft.
- **S3 (built; its PR opens after S2):**
  - `GET /change-calendar`, and the calendar at /changes/calendar: month, week, day and agenda;
    the freeze and maintenance layers; "only mine"; zone days; drag to reschedule with the
    re-approval warning and the freeze guard;
  - the windows admin at /admin/change-windows (template E).
- **Not yet:**
  - a pixel-time grid in the week and day views (entries are listed by day);
  - CI and service layers (with the CMDB);
  - full recurrence rules (D-156 (c)).

### [~] WP-045d — Changes: the rest (lane A, 2026-11-11; 4 sessions; migrations 0133, 0137; REQ-CHG-088..117)
- **S1 (0133, #378):** tasks per stage, the post-implementation review and its date, closure
  codes and rules per stage, closing waits for child changes and releases, closed changes locked
  (REQ-CHG-088, 090-097). Lane B reviewed the lock.
- **S2:** the change list, the record and bulk work:
  - REQ-CHG-098: type and risk columns; views for the CAB, in implementation now, emergency and
    due for review.
  - REQ-CHG-100: the change's conversation and attachments on its record.
  - REQ-CHG-101: bulk assign (D-154a: the owner must be in the group), take and close, through
    the shared bulk dialog. Each change follows its own life cycle, and skips say why.
  - REQ-CHG-102: the CAB pack print view, with the conflict list.
  - **D-156 (Haider, 2026-11-11; migration 0137, lane B blocks):**
    - change replies are e-mailed to the requester; notes never are;
    - monthly windows ("first Sunday", on the tenant's local days); repeat_weekly is kept in
      step for one release;
    - a tenant setting makes outside-maintenance block (off by default), on the windows page,
      audited;
    - an emergency change in a blocking freeze is saved and marked, never refused. Its work
      starts only once its emergency CAB passed the freeze (an approval with a reason, which
      stamps it, is audited and shows in history) or the change manager overrode it. Normal
      and standard changes are unchanged.
  - **Open under REQ-CHG-101:** bulk edit fields, add to a CAB agenda, cancel and delete.
    - Cancel and delete need the `work_item_bulk_jobs` action_code check widened, which is a
      migration.
    - All four come with lane A's next migration WP (WP-045d S3/S4 or WP-046a), with DB tests;
      no migration slot is taken for the check alone (coordinator, 2026-11-11).
    - Until then the change list doesn't offer them at all.
- **S3:** a change notification source with the Appendix A defaults, schedule reminders, the
  workflow run on the record (lane C's Workflows tab, #379), and rules, triggers and SLAs on
  changes (REQ-CHG-103..107). No e-mail reply threading unless Haider says yes.
- **S4:** the portal (raise, follow, approve), the mobile API audit, report dimensions and
  personal counters (REQ-CHG-109, 110, 116, 117). Lane B blocks the portal access.

### [ ] WP-030 — Service requests and the approval engine (lane A, 2026-11-04; 3 sessions; #182)

### [ ] WP-031 — Service catalog administration (lane A, 2026-11-04; 2 sessions; #200)
- **Plan:** ~/Desktop/wp-031-plan.md (coordinator approved, 2026-11-04). Decisions: D-133
  (edition split), **D-138** (starter catalog), ADR-039 (catalog search in Postgres).
  Migrations 0073 (schema) and 0074 (per-tenant data step: `enabled` → `status`, existing
  tenants marked as seeded), so the PR runs full-ci.
- [x] Session 1 (backend, #200):
  - Category tree (4 levels, no loops; a disabled category hides its items from requesters;
    delete only when empty, 409 with counts).
  - Item life: draft → published → retired → published, with planned `publish_at` /
    `retire_at` (schedule `service_catalog__lifecycle`, every minute, audited). An incomplete
    item stays a draft at its publish time. Copy makes a draft; delete is soft and only without
    requests (409 → retire).
  - Publishing needs English, a category and a group; missing translations are listed for
    managers.
  - D6 question kinds with option words, help text, defaults and audiences (requester,
    technician, approver; a requester never sees or sets the others), plus a subject template.
  - D10 "report a problem" entries: a requester incident template, checked through work_items'
    port.
  - D12 search on the shared port: names, keywords, summaries and descriptions in en/ar/ur, with
    Arabic/Urdu normalisation and typo tolerance; p95 ≤ 500 ms for 1,000 items, tested.
  - D7 tenant setting `hide_default_incident_template`; a GET never writes.
  - D13 starter catalog (D-138): 6 categories and 14 items in en/ar/ur, seeded as drafts on the
    new `organization.tenant.provisioned` event, once per tenant. Also: the "choose a group and
    publish" action, `make catalog-starter TENANT=<slug>`, and the showcase seed publishes them.
  - The WP-030 API stays compatible (`enabled` kept: true publishes, false retires; no OpenAPI
    breaks).
  - Tests: domain 16, API 15 (RLS, tree, life, schedule, audiences, entries, search and its
    budget, settings, starter, tooling, the outbox event).
- [x] Session 2 (console admin and portal wiring, #200):
  - Admin › Service catalog: the category tree (add, nest, move up/down, edit, disable, delete
    only when empty), the items (search, status filter, order, featured, copy, delete with the
    "retire instead" answer), the starter banner with "choose a group and publish" (D-138), and
    the tenant setting "hide the general incident form" (D7).
  - One item's page with tabs (Details, Form, Approval, SLA and assignment, Fulfilment,
    Publishing), each saying in one line what it controls.
    - Editors: questions of all 15 kinds with words per language, help, audiences and keys;
      the plan; the approval stage. More stages show as Professional / later (D8).
    - Behaviour: publish, retire, publish again and planned times; missing translations named
      in words; a save sends only what changed (If-Match, the conflict dialog on 409); a
      preview as a requester sees it, read-only.
  - The portal catalog:
    - browse by category, featured items, search in every language;
    - an item's page shows its description before the form (the password item's
      self-service first), then only the requester's questions;
    - "report a problem" entries open the incident form with their template;
    - live through `service_catalog.changed`, also in the console (it was not listened to
      before).
  - One shared question renderer (`packages/ui/catalog`) for the console raise page, the portal
    and the preview, and answers shown in words on both request pages (rule d: no codes or
    IDs). The console raise page lists published service items only.
  - The service requests list in the UI pass 2 style (QA 2026-11-04 #6): view tiles, labelled
    pickers, channel icon and status tag, a loading state and a real empty state.
  - Fix: the portal report form added each file twice.
  - Tests: console admin 5, portal catalog 3, a D7 DB test; e2e `catalog.spec.ts` ("build,
    preview, publish, request", live in the portal).
- **Not done in WP-031 (recorded for WP-047, V1 of service requests):**
  - The subject template is stored and checked, but a new request doesn't fill its subject from
    it yet. That needs work_items' create to accept an empty subject for an item that has a
    template.
  - Ordering is by keyboard move buttons only (no drag).
  - Missing translations use en/ar/ur; switch to `organization.offered_languages` (new on main
    from WP-042).
  - Person and attachment questions in the portal show a hint for now (no people picker or
    upload in the portal form yet).
- **Notes for later:**
  - Popularity ranking ("most requested") is WP-032.
  - Drop `catalog_items.enabled` in a contract migration once no client sends it.
  - Tenant provisioning, when it is built (lane B, identity), emits
    `organization.tenant.provisioned` once the tenant is ready.
  - `docs/guides/urdu-review.md` gets lane C's section from #183 (union).
  - Arabic and Urdu catalog texts wait for native-speaker review.

### [x] WP-030 — Service requests and the approval engine (lane A, 2026-11-04; 3 sessions; #182, merged 2026-11-04)
- **Plan:** ~/Desktop/wp-030-plan.md (coordinator approved D1, D2, D4/D5, D6, D8, D9).
- **Decided (product owner, 2026-11-04):** D3 in **D-133** (catalog basics in Essentials,
  `service_request`; the advanced catalog in Professional, `catalog`); D7 in **D-132** (e-mail
  approval links work without sign-in by default, a confirmation page first, single use, 72 h,
  bound to the approver, audited; reject needs a reason; "require sign-in for approvals" off by
  default; lane B's precondition: bodies holding a link are cleared once sent).
- [x] Session 1 (2026-11-04): done: the service request life cycle (awaiting_approval,
  fulfilled, rejected; system actions approve/reject; migration 0059); the `service_catalog`
  module (categories and items with form questions, one approval stage, plan, priority, SLA
  policy, group, technician; API with If-Match, audit, RLS; migration 0062); the service request
  type in TYPES (`/api/v1/service-requests`, SR counter; requests.* moved from identity under
  lane B's pins); creation from an item (refused without one, answers checked, awaiting approval
  when needed, item priority marked `catalog_item`, group and technician from the item,
  technician after approval; migration 0063 also widens priority_source and
  custom_fields.entity); SLA record type. Tests: domain (life cycle 4, start 4, items 5), db
  (catalog 5, service requests 7, requests.* pins 4). Then: list filters by item and approval
  status (REQ-SR-009); the console's service requests (list, raise from the catalog, one
  request's item details; REQ-SR-010, REQ-SR-003 AC1; Vitest 3); on behalf of within the
  tenant's scope `on_behalf_scope` (REQ-SR-011, migration 0064; never a deactivated person,
  "any requester" can sign in; lane B approved); labels in module files (#181). Then: built-in
  views per type: service requests add "pending approval" and "awaiting fulfilment" (incidents
  never show them; "from my direct reports" already serves both; the requests page picks a view
  with its live count; db 1, Vitest 1); Admin > Service requests sets the on-behalf scope
  (If-Match, a conflict reloads; Vitest 1). The portal's "for someone else" followed once #178
  landed (see session 3's portal work). Migrations: 0059, 0062, 0063, 0064, 0065 (coordinator).
- [ ] Session 2 (in progress, 2026-11-04): done: the approval engine (`domain/approvals.py`;
  migration 0065 `work_item_approvals`, RLS): the item's stage snapshotted at submission
  (approvers by name or the requested-for person's manager, REQ-SR-022; a later manager change
  never moves it), never the requester or the person it is for unless the item allows
  self-approval (REQ-SR-027, 403 `approval_segregation`), never nobody: the backup, else the
  approval administrators (`work_items.approve_any`) with the reason (REQ-SR-023 AC1); the
  first decision decides the stage, a rejection needs a reason, comments when the item says so,
  private comments for staff only (REQ-SR-028); approve moves it on with the item's technician
  after approval (then "assigned"); reject ends it; withdraw while it waits (REQ-SR-061 AC1);
  a deactivated approver's approvals go to the fallback (the first work_items consumer,
  REQ-SR-023 AC2) and a daily check catches what the event missed (AC3); `requests.approve`
  for requesters and technicians (REQ-SR-022 AC2, -063).
  API: `my-approvals`, `{id}/approvals`, `…/decision` (If-Match), `{id}/withdraw`; outbox event
  `work_items.approval.changed` on the record channel and the approver's personal channel
  (administrators' approvals: one broadcast signal); audit `service_request.approval_decided`,
  `.withdrawn`. Service requests get SLAs; the resolution clock waits in awaiting approval
  (REQ-SR-007 AC1); an item that counts approval time keeps it running (AC2,
  `work_items.sla_counts_approval` in 0065); the item's own SLA policy wins over the conditions
  (REQ-SR-006; `item_sla_policy_id`, the SLA module's `preferred_policy` hook). Console: the
  approvals panel on the request page (each entry, Approve / Reject dialog, Withdraw), the
  header approvals drawer with its live count (REQ-SR-024, -025); Admin › Service requests
  can hide approvals from requesters (REQ-SR-024 AC3, a setting in 0065).
  Tests: domain 6, db 16 (incl. RLS), Vitest 3. **Still to do:** the portal approve / reject
  and withdraw (needs #178's portal); notifications to approvers (WP-023 engine registration,
  with session 3's e-mail approvals under lane B's review). At the merge after #178: drop the duplicate
  `permission_module.work_items` label (both PRs add it).
- [ ] Session 3 (started 2026-11-04): done: fulfilment from the item's plan (D8): the plan
  becomes the request's tasks in order at submission without approval or on approval, never
  before and never after a rejection (REQ-SR-021 AC1, -046 AC1, -060); tasks carry `from_plan`,
  `required`, `internal` (0065); the last required one done fulfils the request when the item
  says so (REQ-SR-058; history automatic, rule `fulfilment`; resolution = the tasks done;
  optional tasks may stay open, a "block" open-work rule still stops it; a refused move leaves
  the task's save standing). Tests: db 3. Signed one-time action links (REQ-NTF-024,
  `app/shared/action_links`, migration 0070; lane B reviewed and approved against their five
  conditions): a 32-byte random token kept only as its SHA-256 (RLS), bound to recipient,
  action, object and version, single use, 72 h; POST peek (never acts) and use (audited,
  refusals too), rate-limited, no-referrer, sign-in required (D7 interim); someone else's
  link answers exactly as an unknown one (lane B); the approval engine decides from a link
  with channel `email_link`, a decided or withdrawn approval revokes its links (REQ-SR-061
  AC2). Console page `/requests/approval-link#token` (the token read from the fragment and
  removed from the address bar). Tests: domain 4, db 4 (incl. RLS), Vitest 2. Approval
  notifications (lane B's design and review): `service_request.approval_requested` to the
  approver (urgent, required; the e-mail carries that approver's own link, made by the
  engine's new `RecordSource.recipient_links` hook during their render, in the delivery's
  transaction, skipped when that e-mail already exists; `SECRET_VARIABLES` shows a
  placeholder everywhere else), `service_request.approval_fallback` to `approve_any` holders
  in-app only without a link; category `approval`. Tests: db 3 (one link per recipient, no
  second link on a redelivery, none in-app, no token in the outbox or the logs).
  **Precondition of any no-sign-in mode (D7, lane B):** mail_messages and
  notification_deliveries keep the rendered body, link included, until purge; safe today as a
  link is recipient-bound and needs sign-in, but bodies with links must be cleared at send
  before that mode exists (to go in WP-030's D-file when D7 is decided). Portal (after #178 landed,
  2026-11-04): "for me / for someone else" on the report form, the search listing only the
  people the on-behalf scope allows, names only (`/portal/incidents/on-behalf-people`); the
  Approvals page (a requester-only approver decides there, REQ-SR-022 AC2) and the portal's
  `/requests/approval-link` page; My service requests (`/portal/service-requests`, `/{id}`,
  `/{id}/steps`): plain statuses (new: waiting for approval, not approved), the item's answers,
  only the approvals the tenant shows requesters, the steps with internal names hidden
  (REQ-SR-051 AC2), Withdraw while it waits, and receipt confirmation of a fulfilled request
  (REQ-SR-059). Tests: db 3 + 1, portal Vitest 6. D-132 built (2026-11-04): e-mailed approval
  links work without sign-in by default on the portal's public page `/approve#token` (a
  confirmation page first, nothing decided until a click); `POST /public/action-links/peek|use`
  find the tenant by the address used, run the action as the recipient (their permissions,
  audit and history), ask the entitlement gate for the action's feature (and read-only), are
  rate-limited per tenant and address, and refuse with `action_link_sign_in_required` when the
  tenant's "require sign-in for approvals" is on (Admin › Service requests; then the signed-in
  page); single use by one atomic UPDATE, 72 h, a used or someone else's link answers as an
  unknown one, a link the step no longer needs is spent ("no longer needed"), refused uses
  capped at 5 (lane B's review). Never stored, never logged (Haider's addition): bodies hold a
  marker and the message keeps only the link request; the mail sender mints the token at send,
  a retry or resend mints a fresh one and revokes the old. Tests: db 6 public + 3 notification,
  portal Vitest 2.
  E2E (`e2e/tests/service-requests.spec.ts`, green on the stack smoke 2026-11-04): raise,
  approve from the console drawer, the plan's task done, fulfilled, receipt confirmed in the
  portal, all live; the e-mailed link approved in a window with nobody signed in, once; the
  portal pages in Arabic with axe. **Still to do:** out of draft after #183 (the final
  re-point of 0059, with the coordinator). (E2E: see below.)
- **Found outside WP-030 (lane A's next polish PR, agreed with lane B 2026-11-04):**
  `work_items/service/conversations.py` decides a reply's delivery state from the global
  `get_settings()`, so a checkout whose `backend/.env` sets SMTP fails `test_reply_delivery`
  and a `test_conversation_api` case locally (CI and clean worktrees pass). Inject the Settings
  where delivery is decided (the API passes `app.state.settings`, the worker its own); lane B
  takes any change needed in `app/shared/mail`.
- **Also for that polish PR (from lane A's #197 review, 2026-11-04; lane C left them to lane A):**
  in `IncidentConversation.tsx` / `PersonalCounters.tsx`:
  - join event lines with the list formatter or a label, not a Latin "; " (Arabic and Urdu
    use "؛");
  - sort timeline rows with `Date.parse`, not `localeCompare`;
  - note that event lines cover only the history pages loaded so far;
  - check the counter tiles' hard-coded tints in dark and high contrast (tokens per mode, or
    one dark view measured).
  - Also drop the e2e PORTAL_URL host/port workaround in service-requests.spec once #202
    (portal links on the portal's origin) has landed.

### [x] WP-028 — Portal: shell, sign-in and requester incidents (lane A, 2026-11-03/04; 2 sessions; #178)
- **Plan:** ~/Desktop/wp-028-plan.md. Coordinator approved D1, D3-D5, D8-D10 (2026-11-03).
  D2 decided in D-129 (option a): engine-level `work_items.view_department` and
  `work_items.view_reports`, behind the one scope check `service/portal.py: viewer()`.
- [x] Session 1 (backend, #178, 2026-11-03/04): `domain/portal.py` (plain status, allow-list,
  reach, live rule); `/api/v1/portal/incidents` list, record, templates, create, public
  conversation, replies, confirm/reject; requester channel `t:{tenant}:portal_wi:{id}` (D4);
  requester-side notifications use the portal status and link to the portal record
  (`RecordContext.public_link`, lane B approved); BFF sends a requester signing in on the console
  to the portal and sessions carry the stored type (D-029; lane B approved); contact details
  setting `people_edit_contact` (migration 0058, lane B approved).
- [x] Session 2 (portal UI, #178): done: My requests (filters, search, show more, live), one
  request (fix, conversation, reply, files, camera, live), Report an issue (files, camera),
  contact details card (both apps) and the Admin > Security toggle, manifest start_url/scope,
  console guard; D5 expected resolution time behind `portal_show_due_time` (off by default).
  E2E (portal.spec en/ar at 360x740 with axe, roles.spec under D-129) runs in #178's full-ci
  run; 0058 revises #172's 0054.
- **Paused 2026-11-04 (Haider).** Resume point: merge main into feat/wp-028, re-point 0058, then the e2e users and specs above.
- **D-129 (product owner, 2026-11-04)** replaces the earlier AC1 reading: any role but
  `requester` opens the console (with a Requester portal link); requester-only people always get
  the portal, enforced at sign-in and at /auth/me (also on a shared host), audited. D2 = option
  (a): engine-level `work_items.view_department` / `work_items.view_reports`. Lane B approved.
  E2E: no new suite users needed; roles.spec reworked (not run yet: the shared stack is in use).
- **Follow-ups (not #178):** revoke the dropped console refresh token at a requester's console
  sign-in (needs an OIDC revocation call); warn an admin who gives a requester a role with
  console permissions; requester rows of a wider reach (reports, department) are not live yet
  (own rows are).
- **Moved out (coordinator, 2026-11-03):** admin "preview the portal as a requester"
  (REQ-INC-147 AC4) to WP-032; knowledge suggestions while typing (REQ-INC-028) to WP-034, the
  form keeps a slot; the portal bell stays in WP-023 session 2 (lane B); the approval delegate
  (REQ-PRT-013) and on-behalf-of in the portal to WP-030.

### [~] WP-049a — Assets: foundations, products, the asset record, life cycle, ownership, components, loans (lane B; D-141; 5 sessions; session 1 built 2026-11-05, draft #216)

- **Scope:** parity 07 §1-7, REQ-AST-001..031, plus 058 (permissions by action), 059
  (notifications) and 062 (warranty), folded in by the approved plan. Licence feature `assets`.
  Migrations 0080-0088 are lane B's.
- [x] **Session 1, module and catalogue:**
  - The `assets` module: ModuleSpec, import-linter contract, outbox events, tenant broadcast
    `assets.catalogue_changed` (no IDs).
  - `assets.view` and `assets.manage` moved from the reserved list into the module; added
    `assets.reinstate` and `config.assets`.
  - Migration 0080: life cycles, states, moves, product types, products, settings. RLS FORCE and
    an RLS test on all six tables.
  - Appendix A seeded per tenant on first use: 35 product types, 7 states, 21 moves, the
    standard life cycle. Names are en/ar/ur data (D-041); every row has a stable lowercase code
    that is never shown.
  - D-141: IT or non-IT and the kind are set on top-level types and inherited below. Price and
    tax are stored apart, the total is worked out, and costs include tax by default.
  - The admin page `/admin/assets` (new "Assets" setup group) with tabs for types, products,
    states, life cycles and settings. Live through the broadcast; If-Match and Idempotency-Key.
- [x] **Session 2, the asset record and vendors:**
  - Minimal `procurement` module (migration 0081): vendors with their own list and API, active
    flag (an inactive vendor stays on old records only), and deletion refused while records name
    a vendor.
  - Migration 0082, assets:
    - tag and serial unique per tenant ignoring case, trash included;
    - tags from the nearest type pattern, else the tenant's, never reused;
    - search over the name, every identifier and the custom text;
    - history, outbox, audit, a live list and record channels, trash and restore.
  - Migration 0083: `asset` custom fields (live-check pattern).
  - D-141 counter: only IT assets of kind asset that aren't disposed take a slot (reserve on
    create, restore, product change).
  - Console: /assets list, /assets/:id (Details, History) and /assets/vendors.
  - Downgrades of 0080-0083 refuse while tenants have data (rule 5h).
  - Region and the hardware tab come with discovery (WP-050).
- [x] Session 3: life cycle in use (#216; migration 0108; REQ-AST-010, 011, 012, 013, 017).
  - Moves along the type's life cycle with reasons, required fields and move permissions
    (assets.reinstate); copy up to the tenant's limit; bulk moves with per-asset results.
  - Dispose with a record (date, method, reason, cost, approver) and a certificate file (owner
    type asset_disposal); a disposed asset is read-only without assets.edit_disposed (admins
    only by default), and every change to it asks for a reason.
  - A guard port for what still holds an asset: loans (session 5) and licence allocations
    (WP-052) register theirs.
  - Console: change state, copy, bulk moves, dispose, the disposal record; a searching product
    picker; custom fields in the form and on the record; the asset's age.
  - **Open:** AC4 of REQ-AST-017 (the disposal cost in the cost table and TCO) comes with the
    cost table (session 4/5).
- **Two PRs (coordinator, 2026-11-06):** #216 holds sessions 1-3 (it passed 14k lines); sessions
  4-5 go on a new PR from main after #216 merges. Session 4 has migrations 0111 (ownership,
  assignments, relationships), 0112 (acknowledgements) and 0113 (asset groups).
- [x] Session 4: ownership, acknowledgement, components, groups, relationships (migrations
  0111-0113; REQ-AST-018, 019, 020 for assets, 023, 024, 025's interfaces, 026, 027, 028).
  - Holders (a person, a department or a parent asset) with the holding history; never fitted
    inside itself; assets follow their owner's site (a consumer of identity's user.updated,
    idempotent); held-by lookups within scope.
  - Acknowledgements (pending, accepted, disputed with a comment; a dispute never touches the
    holding) with an `asset` notification source; My assets in the portal, live.
  - Components (fitted assets; disposing asks to detach or dispose them) and typed links shown
    from both ends with history on both.
  - Static and dynamic groups (the shared filter DSL), counts matching their lists, live.
  - The picker and `can_see` / `asset_refs` / `assets_of` for lane A's work-item forms.
  - Console: "Holder and links" tab, groups page, add-to-group from the list's selection.
  - **Deferred:** 021/022 (auto-assign, workstation mapping) with discovery (WP-050); 020's
    consumables and licences with WP-052; 024 AC2 "report a problem" and 025's forms are lane
    A's, on the picker.
- [x] Session 5: loans, warranty, notifications, e2e (migration 0114; REQ-AST-029, 030, 031,
  059; the PR with session 4 opens from main after #216 merges).
  - Loanable assets (bulk from the list); loans of loanable, in-stock assets to a person until a
    due time, moving them in use and to the borrower; one open loan per asset is a unique
    partial index, so two loans racing for one asset never both win (race test).
  - Returns of some or all assets, to stock or to repair (a comment needed); the last return
    closes the loan; an asset on loan is not disposed of (the disposal guard port).
  - Due and overdue notices to the borrower and the loan's creator, and warranty-ending notices
    to the asset managers within the tenant's notice days (Appendix A: 30, a setting), each
    claimed once by one UPDATE ... RETURNING (two-worker test), from a scheduled sweep.
  - Console loan register (/assets/loans) with New loan and Take back; the portal's My assets
    shows when a loaned asset is due back, red once overdue; all live (loans_changed, and the
    borrower's own channel). Shared page parts only, ready for the UI pass 3 list template.
  - e2e: tests/asset-loans.spec.ts (loanable in bulk, lent, due in the portal, taken back).
  - **Open:** REQ-AST-017 AC4 (a disposal certificate file) waits for the file link of WP-022's
    record attachments on assets; REQ-AST-030's display ID, department borrower, site and
    filters, and REQ-AST-032 (booking ahead), go to WP-049b.
- **Also lane B:** the REL-024 AC2 duty-preview port `register_duties` is #223; the role-editor
  preview UI follows lane C's release lookup.

### [~] WP-049b — Assets: consumables, minimum stock, bookings ahead, the loan's leftovers (lane B; sessions 1-3 built 2026-11-11)

- [x] **Session 1 (migration 0130, down revision 0129; REQ-AST-030's
  leftovers, 032, 033, 034, 035):**
  - Consumables (033): a product of a consumable type (D-141) kept in stock with barcode, vendor,
    unit cost and comment; batch tracking chosen when made, a switch refused with the reason
    (AC3). Stock per product and site (one row each, "no site" included); receiving raises only
    that site's (AC1); lots with lot number, reference, made and expiry dates, an expired lot
    flagged (AC2).
  - Allocations (034) to a person, a department or an asset, with a date and optionally the
    request (an ID only, rule e). One conditional `UPDATE ... WHERE quantity >= n RETURNING`:
    more than there is is refused with the amount available (AC1); of two people taking the
    last unit one wins, the other is told it ran out (AC3, race test); a CHECK keeps stock at
    zero or more. The request's side reads `GET /assets/consumable-allocations?work_item_id=`
    and the `assets.stock.moved` event names the request (AC2).
  - The ledger (receive, allocate, adjust, return) with who, when, why and the balance after;
    append-only (the app role may only SELECT and INSERT; tested).
  - Minimum stock (035) per product type or product and per site or every site, the most
    specific rule winning, with the people told: one notice when stock falls to or below it,
    re-armed only above it (`low_alerted_at`, claimed by one conditional UPDATE; AC1). New
    notification event `asset.stock_low` (en/ar/ur templates). AC2's draft purchase request is
    the `DraftPurchaseRequests` port for procurement (WP-054); until it is registered none is
    made (logged, never faked).
  - Bookings (032) of one specific loanable asset: the asset row is locked, then the period is
    checked against its bookings and its open loan; a clash is refused with the next free day
    (AC1, race test); a loan over a booked time is refused (`asset_booked`); handing over makes
    a loan with the booking's dates (AC2); requesters book in the portal only while
    `asset_settings.portal_booking` is on (default off; AC3).
  - Loans (030's leftovers): display ID `LN-n` on new loans (older loans keep none), a
    department borrower (the department holds the assets, the borrower collects them), a site,
    and register filters by status (open, overdue, closed) and site.
  - Console: `/assets/consumables` and `/assets/consumables/:id` (stock, lots, ledger; receive,
    allocate, adjust, take back; `?allocate_for=<request>` links an allocation), the asset's
    Bookings tab (book, cancel, hand over, take the suggested day), the loan register's columns
    and filters, Admin > Assets "Minimum stock" and the portal-booking setting. Portal: My
    bookings on My assets while booking is on. All live (`assets.consumables_changed`,
    `assets.bookings_changed`); labels en/ar/ur; both new screens in the visual matrix.
  - Permissions reused: `assets.view`, `assets.manage`, `config.assets` (no new rights, no role
    matrix change).
  - **Open:** the request page's own panel for its allocations (lane A's screen, on the API
    above); a calendar screen of availability by product and site (`GET /assets/availability`
    is there, and the portal's picker uses the same query); AC2 of 035 with WP-054.
- [x] **Session 2 (migration 0131 after 0130; REQ-AST-036, 037, 038, 048, 049, 050; branch
  backup/wp-049b-s2, its PR after #367 lands):**
  - Cost lines (move, service, contract, other) in the base currency, the disposal record's cost
    as the only disposal cost (counted once), and the total cost
    of ownership, exact decimals (036 AC1, AC3); depreciation as a pure domain (straight line,
    declining balance 150 %, double declining, sum of the years' digits, none; prorated by month;
    golden-value tests) with the asset's own settings or its product's (037 AC1-AC3); book value
    on any day and the schedule by year; "today" is the tenant's local day (its time zone).
  - Cost centre and GL code (free text; GL from the product) on assets; `asset_valuations` for
    reports by cost centre (038 AC2), refreshed on save and by a daily sweep. Dimension codes for
    lane C: `cost_centre`, `gl_code`; money fields `book_value`, `total_cost`.
  - New right `assets.view_financials` (asset manager, admins) guarding all money in API and UI.
  - Notes with mentions, edit history and "note deleted" lines; attachments as the asset's files
    (050). History sub-views (state, assignment) and filters by field, source, person and days
    (049). The record page gains Financials and Notes and files tabs and the panel's value (048).
  - Guide: docs/guides/asset-financials.md.
  - **Open:** 048's hardware, software, contracts and scan-history tabs (discovery, S3, WP-054);
    049 AC1's `discovery` source (S3); 036 AC2 and 038 AC1 with WP-054.
- [x] **Session 3 (migrations 0134 and 0135 after 0131, re-pointed at the lane's turn; REQ-AST-039,
  042, 043, 054, 056; branch backup/wp-049b-s3):**
  - Shared PDF renderer (agreed with lane C): `app/shared/pdf` holds the bundled fonts, the fetcher
    that refuses every URL but those fonts, `available()` and `render(html)` with page and byte
    caps; analytics keeps its report HTML and its `pdf_not_available` code. The fetcher and
    fonts-only tests moved with `git mv` (history kept); the report-only tests stay in analytics.
    The worker-test image runs the shared and asset PDF tests too.
  - Labels (039): QR (segno) and Code 128 (python-barcode; D-141, CLAUDE.md §3) as inline SVG in
    one PDF per job (up to 500, one label per page; cable and laptop layouts; Arabic right to
    left), built by the consumers worker (`assets.label.requested` → `assets.label.printed`),
    downloaded by the person who asked for a week. The QR holds only the console link (AC2).
    `assets.view` on every asset printed, scoped (404 naming none). Every print and reprint
    writes an append-only `asset_label_prints` row (SELECT, INSERT only; AC3). Vendor codes print
    through the same generator. AC1: 100 assets make one 100-page PDF (pdf test).
  - Audits (042, 043): plan with `assets.manage` (sites, product types with their children,
    asset groups; dates; named auditors); start freezes the expected items (AC1: exactly the
    site's assets); named auditors with `assets.view` mark by scan or by hand while it runs;
    found at another site is the wrong place (043 AC1); unexpected assets added; bulk fixes (move
    site, change state, assign) each through the asset service in a savepoint, history naming
    the audit (043 AC2, `automation_ref` kind `asset_audit`); progress live on
    `t:{tenant}:asset_audit:{id}` (043 AC3); closed is read-only on the server. Self-audits ask
    each holder again through their acknowledgement (one per holding and audit; accepted =
    found, disputed = missing with the holder's comment kept on the item and shown in the
    discrepancy list); a requester sees and answers only their own. View-only people may select
    assets to print labels; every other bulk action stays assets.manage (server-tested).
  - Scans (054): `app.modules.assets.record_scan` (the discovery port; nothing calls it yet),
    the asset's Scans tab, `last_scanned_at`; the daily `assets__scan_cleanup` deletes scans past
    the asset settings' retention (the existing `scan_retention_months`, Appendix A: 6 months),
    per tenant, one audit summary each run; assets and history lines stay (AC2).
  - Overdue rule (056): off by default (`config.assets`), N days, product types, a state or the
    trash (never a delete), preview count before saving (AC2), the hourly
    `assets__overdue_scans` job records each run that changed something with its list and names
    the rule in each history entry (AC1); trashed assets restore with their history (AC3).
    It follows the life cycle: only reachable target states are accepted
    (`asset_overdue_state_unreachable`), and an asset whose state cannot move there is skipped,
    unchanged, and listed in the run with its reason.
  - Migration 0135: `ix_field_changes_change` (tenant_id, change_id), built and dropped
    CONCURRENTLY.
  - Console: Assets › Audits (list) and an audit (record: items, scan box, discrepancies with
    bulk fixes), Print labels on the asset list selection and the asset page, Labels and Scans
    tabs, history lines naming the audit or the rule, the overdue rule in Admin › Assets ›
    Settings. Portal: the self-audit question in My assets. Visual matrix: asset-audits,
    asset-audit, asset-scans; the showcase has a running audit with marks and two scans.
  - Guide: docs/guides/asset-labels-and-audits.md.
  - **Open:** label PDF progress is reported at the end only (the worker renders in one step);
    the API cannot tell beforehand whether a worker can render PDFs (a job without one fails
    with `pdf_not_available`); the label designer (040) and mobile scanning (041) are later;
    discovery calls `record_scan` (WP-050).

### [~] WP-064 — Record lifecycle in the tamper-evident audit log (lane B; D-150; ADR-045, ADR-046; sessions 1-2 of 4 built 2026-11-10/11)

- [x] S1: the audit sink port in `app/shared/history.record_changes` and the audit module's sink;
  one entry per save listing all its events (route's code first, merged with the route's entry
  in the same transaction); `events` inside the entry hash only when set (migration 0122, GIN;
  older entries hash as before); the action filter, saved searches and exports match events;
  event tables for assets and the five work-item types (lane A reviewed the field lists;
  statuses by category through work_items' annotator, never stored in history); the subtype
  resolver; catalogue and en/ar/ur labels; tests (unit, DB, the history guard).
- [x] S2 (ADR-046, migration 0129): each save's entry holds two `fp1:` commitments to its
  values in record history (never the values), inside the entry hash only when set: the
  ordinary fields unsalted (they always verify, so an erasure never hides a change to them)
  and the personal fields salted; the canonical
  encoding fixed in ADR-046 with a golden vector; personal fields per record type in
  `audit/domain/lifecycle.py` (work items: free text and save reasons, subjects = requester and on-behalf
  person; assets none; people later) for lanes A and C to review; per-subject salts in
  `audit_subject_salts` (no app rights, definer functions only); the verifier reports
  verified / mismatch / erased on request (runs and the entry view; erased only when the
  ordinary half matches); erasure blanks the
  person's free text in history and destroys the salt; labels en/ar/ur.
- [ ] S3: per-category retention and legal hold (0120), sealing to about 2,000/s, the 10M run,
  the save-latency check.
- [ ] S4: the console (before/after from history beside a verified mark, a filter by record,
  file events in a record's list), e2e, docs.

### [x] WP-048b — Visual workflows: designer and durable runtime (lane C; ADR-043; sessions 1-5 built, #233, #374, #379)

Full-build plan: REQ-WF-008..029 (file 03 §15). Plan approved by the coordinator 2026-11-05.
Numbers: ADR-043; migrations 0105 (S1), 0106 (S2), 0107 (S3, if needed); D-146 (approval chair).

- [x] **S1 — the runtime core (#233).**
  - ADR-043, reviewed by lanes A (§6 work_items touch points, §7 the shared action library)
    and B (§8 the guarded HTTP client, the run-as identity).
  - Definitions and validation (`domain/workflows.py`): the node registry, problems named by node
    or link, the Appendix A limits.
  - The interpreter (`domain/interpreter.py`): a pure step function with tokens, joins, waits
    (overtaken and timeout outputs), timers, commands whose results choose the output, and the
    loop and step limits. 49 automation domain tests.
  - Migration 0105: workflows (with start templates), versions, instances, steps, all with RLS.
  - The runtime (`service/workflow_runtime.py`): start and run, with commands through the
    record type's `run_command` port. work_items implements it through its public services, as
    the workflow's run-as identity; history names the workflow through `history.automated`.
  - The run-as identity: a service identity per workflow, with source "workflow"
    (UserCreatedV4). Roles come only through the guarded path, and a never-list (tenant_admin;
    identity, role, user, preview and API-key management) holds on every path. Lane B approved.
  - Wakers: the `automation__workflow_events` consumer (record changes, template starts) and the
    `automation__workflow_wake` minute sweep; Temporal's `WorkflowInstanceWaker` with
    `workers/workflow_timers`, signalled by `automation__workflow_scheduler`.
  - Admin service and API `/automation/workflows`: create, draft with problems, publish, enable,
    start templates, start on a record, instances and their log; `workflows.manage` and
    `workflows.run` behind the `workflows` licence feature.
  - The trigger action "start a workflow" (REQ-WF-010 AC2; lane A reviewed): checked on save,
    its own savepoint, refusals logged by code; a loop guard through the shared
    `app/shared/events.caused_by` (a workflow command's events name the instance as their cause).
  - Lane B's chart (#268, after #233): a `workflowTimers` Deployment beside slaTimers with
    Temporal.
- **Two PRs (coordinator, 2026-11-06):** S1 lands alone on #233, so lane B's chart (#268) can
  follow; S2-S5 go on a new PR from main after #233 merges. Within S2, the guarded HTTP client is
  its own commit for lane B's review; the function node is the runner port only (§6.7).
- [x] **S2** — built on backup/wp-048b-s2; the PR opens in 0106's migration turn (after 0123).
  - Variables, retries and error outputs, sub-flows (S2a); D-146's chair in the shared level
    outcome and the approval settings (S2b); the guarded HTTP client, reviewed by lane B (S2e).
  - **Approval node:** one level on the record (purpose `workflow`, naming the instance and
    the command); people, groups or roles; administrators when nobody can be named; the chair
    breaks a tie. The decision continues the node through the outbox
    (`automation.command_finished`). Offered on SRs, releases, problems and changes.
  - **Task node:** a checklist of 1-20 tasks with an owner and a due date in working days;
    all done continues it, a canceled or removed task takes its error output.
  - **Function node:** the runner port only, run by a worker (§6.7); offered with SANDBOX and
    CUSTOM_FUNCTIONS and a registered runner (no runner ships: ADR-011).
  - **Webhook node:** one call through the guarded client from a worker, with an idempotency
    key; the status can be kept as a variable.
  - **Notify node:** through the one notification engine (lane A's design): a
    `workflow_audience` resolved at send time, access checked per recipient, the node's own
    words; incidents first (lane A adds SRs and problems after).
  - 0106 adds `work_item_approvals.workflow_command` and the task pair; the downgrade refuses
    while any are set (rule 5h).
  - For lane B's security review: named workflow approvers decide by being named (as stage
    approvers), the egress use, the function port, NotificationCategory.WORKFLOW.
  - Open: run-time error codes (`webhook_*`, `task_canceled`, …) get labels with S4's
    instance view; a task owner that does not exist is refused by a foreign key, not a code.
- [x] **S3** — built on feat/wp-048b-s3 (backup/wp-048b-s3); one PR from main, opened in 0107's
  migration turn (after 0130). Session log: progress-log/2026-11-11-wp-048b-s3-lane-c.md.
  - **S3a, stop, restart, retry (REQ-WF-025 AC2, REQ-WF-026):** on a record, in the workflow domain
    (`domain/operations.py`), audited. Canceling a record stops its workflows (lane A's hook).
  - **S3b, the overview and bulk jobs (REQ-WF-025):** runs by workflow, state and node, failures
    with node and error. Bulk retry and cancel are background jobs (`workflow_jobs`, migration
    0107): a savepoint per run, each result kept, live on the queue channel.
  - **S3c, versions and migration (REQ-WF-021, -027):** runs stay on their version. A migration
    maps occupied nodes; unmapped runs stay and are listed; a dry run changes nothing; the record's
    history shows the version move. Versions show who published and the live runs per node.
  - **S3d, copy, export, import, delete (REQ-WF-027):** a copy is an independent draft. Export and
    import within one tenant give the same definition. Import refuses another tenant's file, other
    shapes, files over 1 MB and template IDs that aren't here. A workflow with live runs is never
    deleted.
  - **S3e, test mode (REQ-WF-022):** the same `advance()` on a record's facts or sample values, in
    `workflow_test_runs` (0107). Commands are shown and answered by hand; timers fire on the run's
    own clock. Nothing reaches the record, its history or the outbox. One live call per run, for a
    webhook or notify node on a record: workflows.manage only, audited with who, node and record.
  - Cross-tenant import is out of scope (coordinator, 2026-11-11). It needs an ID-mapping step
    (templates, people, groups) later.
- [x] **S4** — the designer, test mode and the record's Workflows panel (feat/wp-048b-s4, backup
  branch backup/wp-048b-s4); one PR from main, no migration. Session log:
  progress-log/2026-11-11-wp-048b-s4-lane-c.md.
  - **packages/flow:** @xyflow/react 12.12.0 (companions listed in the PR), the definition ↔
    canvas mapping (a saved definition re-opens to the same diagram, both directions), positions
    stored left to right and mirrored in RTL, an in-house layered layout (no dagre or elkjs),
    undo/redo history (100 steps).
  - **The list** (Admin › Workflows, template C) and **the designer** ("template A header + canvas
    body"):
    - palette (drag, or a button that places the step below the selected one);
    - canvas with labelled, always-visible handles;
    - details with forms for if, switch, notify, timer, wait and set status, plus "Advanced";
    - link details with a clear delete;
    - an outline that builds and unlinks by keyboard (REQ-WF-028 AC1);
    - problems that select their step;
    - save, publish, enable;
    - live on the workflows channel.
  - **Server:** the palette (`node-types`), outputs from the registry (`node-ports`), workflow
    changes on the list channel, typed created responses.
  - **Test mode panel (REQ-WF-022):**
    - a run on a record (display ID) or on sample values;
    - each step answered by hand, a described change, the clock moved on;
    - the path taken and the current step on the canvas (`current_nodes`);
    - the one live call behind a confirm that says it is audited.
  - **The record's Workflows panel (REQ-WF-023, -024, -026)** on incidents, requests, problems,
    changes (placement agreed with lane A) and releases:
    - the diagram with the path and the current step, and the log to the second;
    - a failure banner in words;
    - retry, run again and stop.

    Its endpoint is gated by workflows.run and the record's own view rule (404); the instance
    log got the same gate. Every run-time failure code has a label (tested).
  - **Visual matrix:** admin-workflows, admin-workflow (+ outline), incident-workflows; the
    off_screen check skips controls inside a strip that scrolls sideways.
  - **Bundled (coordinator):**
    - the "Book value by cost centre" and "Total cost of ownership" reports (asset money
      measures, listed only for assets.view_financials);
    - the release downtime delete asks first (lane A's #377).
- [x] **S5** — the runs overview, versions and moving runs, skip, waiting longer than, e2e and
  guides (feat/wp-048b-s5, backup/wp-048b-s5; one PR from main, no migration). Session log:
  progress-log/2026-11-11-wp-048b-s5-lane-c.md.
  - **S5d, skip a failed step (REQ-WF-024 AC2):**
    - goes on through the failed step's "next" output only; a step that decides its own path
      is refused with skip_without_next;
    - POST /instances/{id}/skip: If-Match, may_edit, audited (who, step, record);
    - "Skip this step" on the record panel, behind a confirm.
  - **S5b, waiting longer than (REQ-WF-025 AC3):** `waiting_over_hours` on the overview. It
    reads the last step on workflow_steps' tenant-first primary key, backwards (EXPLAIN checked
    in a test), so no index or migration.
  - **S5a, Admin › Workflows › Runs (template C):**
    - filters for state, record type, workflow, step and waiting longer than;
    - failures in words;
    - a run's record named and linked only for those who may see it, via a read-only `labels`
      port that lane A agreed (rule 8);
    - bulk retry and cancel (with a reason) as jobs, one per workflow, at most 1,000 runs, with
      live progress; the job's audit keeps its kind, run count and reason.
  - **S5c, versions and moving runs (REQ-WF-021):**
    - the designer's Versions tab: who published each version, when, and its live runs;
    - the move dialog maps each occupied step, then a mandatory dry run, then the move as a job;
    - new: `versions/{n}/steps` and the overview's `version_number` filter.
  - **S5e, e2e and guides:**
    - docs/guides/workflows.md;
    - e2e/tests/workflows.spec.ts: a workflow built by keyboard and run on an incident, a test
      run's timer, a failed step skipped;
    - Visual matrix screens for Runs and the versions dialog.
    - **Not a journey:** a webhook failing at its receiver needs the consumers worker and a test
      receiver in the e2e stack. The DB tests cover it (test_workflow_webhooks.py); an e2e
      journey waits for an e2e receiver (follow-up), never a retry loop (the coordinator).
- **Follow-ups noted:** a workflow note in the recipient's language (S2 note templates); the
  `users.preview` test once that permission lands (lane B).

### [~] WP-058a — Releases: record, stages, templates, roles, planning, approvals (lane C; ADR-041; sessions 1-6 of 6 built 2026-11-05; #214 merged, #219)

Full-build plan (docs/specs/parity/full-build-plan.md): REQ-REL-001..037 (file 06 §1-7). Order agreed
with the coordinator: S1-S5, then S6 without workflows, then WP-048b (workflow designer), then
WP-059-062; REL-020..022 move to WP-058b once lane A's WP-045c lands.

- [x] **S1 — the stage engine and the release record.**
  - ADR-041, reviewed by lane A for changes' reuse.
  - Migrations: 0090 (the five stage tables), 0091 (saved `releases.manage` grants), 0092
    (release details and lists).
  - Releases live at `/api/v1/releases`, with the rail (`/stages`), listed moves (`/moves`) and
    the release's own fields (`/details`).
  - Appendix A seeds.
  - Labels in en, ar and ur.
- [x] **S2 — templates, stage rules, type defaults, copy (#219, migration 0093).**
  - Templates choose the path and carry rules per stage (shown, required, read-only), checked
    on save.
  - Standard and emergency templates are seeded.
  - Read-only per stage is enforced through the API.
  - A release type can set its default template and risk.
  - Copy (REQ-REL-009).
- [x] **S3 — required to leave a stage, stage access (#219, migration 0094).**
  - Required-to-leave checks run in the engine on every path; a move can carry the values.
  - Stage access is an AccessRule in identity_access's policy layer (lane B reviews), applied
    after the scope check. Visibility is never narrowed.
  - Offered moves show their reasons and missing fields; a refused move returns the full list.
  - A group change takes effect without signing in again.
  - Not done: bulk stage moves (REQ-REL-018 AC2) go to WP-058b with the release lists. Record
    roles in stage access come with S4.
- [x] **S4 — roles, plan, schedules, outcomes, downtimes (#219, migration 0095; REQ-REL-023..028).**
  - Roles are held by people or groups, with eligibility through the policy layer; holders
    are part of the own scope. Lane B reviewed the policy part; lane A checked the tables for
    changes.
  - Plan sections have their own If-Match.
  - The engine stamps actual stage dates; corrections need a reason.
  - Stage outcomes: a failed outcome needs its issues.
  - Downtime windows name the affected services and CIs.
  - Not done:
    - Notifying a new role holder (REQ-REL-023 AC1) and the "behind schedule" list column
      (REQ-REL-026 AC3) come with WP-058b's notifications and lists.
    - Copying downtime from a linked change (REQ-REL-027 AC1) needs changes (058b).
    - Listing a person's open roles before a permission is removed (REQ-REL-024 AC2) is
      **lane B's**: identity_access adds `register_duties(lookup)` (as register_owner_access).
      The role editor's "remove permission" and "remove role from user" previews show the
      affected users' open duties, labels only. work_items then registers one lookup: open
      releases where the user holds a role whose eligibility needs that permission. Queued by
      lane B after WP-049a s1; they send the port signature first.
    - REQ-REL-029 (environments) is LATER.
- [x] **S5 — stage approvals, review, sub-releases (#219, migration 0098; REQ-REL-030, -031, -037).**
  - Approvals at each stage run on the WP-030 engine (lane A reviewed): up to five levels of
    people, groups and record roles, each decided by any, all or majority (an exact majority
    split rejects). The final decision sets the outcome through system_stage_move.
  - Named approvers decide by being named; `releases.approve` (admin roles only) is for
    approvals one is not named on. A role nobody holds, or a requester under segregation of
    duties, goes to the approval administrators with the reason shown.
  - Review sections and the review result.
  - Sub-releases: one parent, no loops, and no deployment before the sub-releases pass
    testing.
  - Not done:
    - REQ-REL-034 (incident, request and problem links) waits for lane A's cross-type links
      (#211). REQ-REL-033 (changes) and REQ-REL-035 (CIs and services) go to WP-058b and
      WP-063.
    - REQ-REL-032 reminders, backups and clarification, the review-date reminder, and
      follow-ups as problems or changes go to WP-058b's notifications.
    - The override of the sub-release check is recorded for WP-058b.
- [x] **S6 — console screens, e2e and RTL (#219).**
  - Releases list with the emergency flag, live.
  - New release from its template.
  - The record: the rail, moves with their dialog, and tabs for details, roles, plan,
    schedule, downtime, approvals and sub-releases, live.
  - Console tests, and an e2e spec with axe in English and Arabic.
  - Admin guide: docs/guides/releases.md.
  - Not done:
    - The release screens join the Visual matrix after #219 merges (they would collide with
      the matrix selector fix now).
    - Admin screens for stage access, stage approvals, role definitions and template stage
      rules come with the admin pass (their APIs are in and tested).
- **Not done in S1 (recorded for later sessions):**
  - REQ-REL-003: a type's default template and default risk come with templates in S2.
  - REQ-REL-005 AC2: the "unique versions per service" tenant setting comes with services in
    S5 (REQ-REL-035).
  - REQ-REL-006: custom fields placed per stage come in S2. The `release` entity exists.
  - No console screens yet (S6). The API is complete and public (mobile-ready, the
    coordinator's 2026-11-05 note).
- **Not done in S2:**
  - REQ-REL-010 (import releases) moves to **WP-062b** (data administration and import, file 11
    §11; the coordinator's decision, 2026-11-05).
  - REQ-REL-008: from an incident or problem once lane A's link kinds are on main; from a change
    in WP-058b.
  - Required-to-leave-stage is S3. Tasks and checklists per stage are S4.

### Recorded for WP-062b (lane C: announcements and data administration)

- **Announcement expiry for followers:** lane A's #220 (WP-032 D7) notifies followers when an
  announcement is updated or taken down. A window that simply runs out raises no event, so
  followers are not told; it needs a timer (Temporal or a sweep) to raise "ended" at
  `publish_until`.
- **Release import (REQ-REL-010)**, from WP-058a S2.

### [~] WP-058b — Releases: changes, calendar, guard, stage work, closure, lists, notices, DevOps (lane C; plan approved 2026-11-11; 7 sessions)
- [x] Session 1 (2026-11-11): changes in a release and the shared calendar. Migration 0138.
  - **Changes in a release (REQ-REL-033):**
    - link kind `in_release`;
    - GET/POST/DELETE `/releases/{id}/changes`;
    - a change is in one open release at a time, and adding it to another names the first;
    - history on both records;
    - a change the viewer may not see shows only that it is there;
    - the release page's **Changes** tab.
  - **Calendar (REQ-REL-038, -039):**
    - `/release-calendar` uses lane A's `calendar()`, generalised by planned stage (change
      implementation, release deployment) and scoped by each type's own permission;
    - the change calendar moved to `pages/staged/ScheduleCalendar` with its behaviour kept
      (Move…, role=row, the re-approval preview and conflict path, #381's tests); the Move dialog
      now uses the shared DateField;
    - new: a timeline view and a quick-view drawer; `/releases/calendar`.
    - both types on one calendar: "Show changes" / "Show releases" with a legend (REQ-REL-038
      AC1), each moved by its own stage and rules;
    - the release's scheduler: `/releases/calendar?focus=<id>` from its Schedule tab, opened on
      its deployment with only its changes by default (REQ-REL-039 AC1).
  - Tests: `tests/db/test_release_changes_api.py` (4); Vitest `release-calendar.test.tsx` (3),
    the Changes tab in `releases.test.tsx` (2). Matrix screens: `release-calendar` (+ timeline)
    and the release's Changes tab.
  - **Open:** per-environment guarding (WP-053). A release move has no re-approval preview; the
    type-neutral guard comes in S2 with the ADR-042 addendum. A change does not yet show its
    release on its own page (S3, with the page tabs). REQ-REL-033's copy-downtime-on-add and
    "a change behind its schedule" marker, and REQ-REL-038's service/site/type/group filters
    and stage colours, go to S5 with the lists.
- [ ] S2: the guard by planned stage, conflict acks, release freeze override (after lane A's
  WP-045d S2, 0137). S3: stage on tasks and worklogs, page tabs. S4: closure and rollback.
  S5: lists, staged board, bulk. S6: notices and the release-reply mail (D-156; lane B blocks).
  S7: DevOps links (after WP-055).

### [ ] WP-023 — Notification engine and in-app notifications (lane B, assigned 2026-10-28; D-106; 2 sessions)
- **Plan:** ~/Desktop/wp-023-plan.md. Built on `app/shared/mail` (D-089) and the server labels (D-100 D7).
- [x] Session 1 (2026-10-28): one engine through `app/shared/notifications/ports.py` (REQ-NTF-001; the
  consumer reads every event, `ConsumerSpec.accepts` skips the rest without a claim); incidents
  register from `work_items/service/notifications.py` (lane A reviews); rules per event with
  defaults, conditions, If-Match, audit, reset (REQ-NTF-008); recipients relative to the record, one
  message per person, never the actor (REQ-NTF-009); access at send time, requesters public side
  only, private notes never (REQ-NTF-010); default templates en/ar/ur as labels (REQ-NTF-013 part,
  -014); delivery rows with state and reason, mail-waiting banner and hand-over when mail works
  (REQ-NTF-020 part); centre with live badge, day groups, read one/all, do-not-disturb (REQ-INC-131);
  personal preferences with required events locked (REQ-NTF-016); recipient's language and zone
  (REQ-INC-133); delivery log API for the incident History tab (REQ-INC-134, lane A places it).
  Migration 0033. Tests: `tests/db/test_notifications_api.py` (9), domain (8), console Vitest (6),
  e2e `notifications.spec.ts`.
- [ ] Session 2: template editor (versions, compare, restore, preview, test send, shared
  header/footer; REQ-NTF-011/012/013), throttling and storm protection (REQ-NTF-022), digests
  (REQ-NTF-017), signed action links (REQ-NTF-024; incident confirm/reject with WP-020f), group
  subscriptions and "unpicked for N minutes" (REQ-NTF-026, REQ-INC-130), resend (REQ-NTF-020 AC2),
  retention 90/180 days, the portal bell (WP-028); call WP-020f's `resolution_notified` when
  `incident.resolved` really reaches the requester (e-mail sent; in-app once the portal exists).

### [x] WP-017 — Tenant branding and domains (lane B; D-027, D-090; ADR-031; built 2026-10-27, 1 session)
- **Goal:** Each tenant gets its own address and look without a redesign.
- **Done:** REQ-ADM-055, REQ-PRT-016, REQ-SEC-003, REQ-SEC-004 (docs/architecture/branding.md):
  - tenant colours, product and portal names, welcome text (en/ar/ur), logo, dark logo and icon;
    WCAG AA checked on the server, failing colours refused with the nearest passing one;
  - Pillow variants (logo per theme, icon, favicons) served publicly on versioned URLs;
  - console and portal follow the address's brand before sign-in and the tenant's after it,
    live on save (favicon included); portal name and welcome text on the portal;
  - Keycloak sign-in page branded per organization (template block + per-tenant stylesheet);
  - tenant addresses: subdomain `<slug>.<tenant_base_domain>`, custom domains proved by an HTTP
    token, own certificate upload; sign-in on an address asks for that organization only;
  - e-mail branding contract for the WP-039 mail foundation;
  - Admin › Branding with live preview (light, dark, high contrast) and an Addresses card;
    everything audited (`branding.updated`, `domain.*`).
- **Decided (D-093, ADR-031 accepted):** a separate domain worker with its own minimal service
  account provisions certificates and routes (built with the SaaS cell, WP-014d), ACME only where
  there is internet, never from an air-gapped install; registering custom domains as Keycloak
  redirect URIs comes with it. Offering only the sign-in methods a tenant enabled (REQ-SEC-003
  AC2) needs WP-039 SSO.
- **Depends on:** WP-010, WP-014, WP-016

### [ ] WP-039 — Identity: SSO, MFA, invitations, sessions, my account (lane B; D-089, D-094; ADR-036; session 1 of 3 done 2026-10-27)
Plan: ~/Desktop/wp-039-plan.md (answers D-089). docs/architecture/identity.md.
- [x] Session 1 — foundations and SSO:
  - service account `supportx-identity` (least privilege, verified on 26.8.1) and its upgrade
    step (chart Job, `make keycloak-identity`, stack-smoke); admin API client;
  - `identity_settings` (migration 0024): console and portal session limits per tenant
    (REQ-SEC-029), people creation on first sign-in (REQ-SEC-013); `prompt=login` after a
    timed-out session;
  - REQ-SEC-031 (deactivation): sessions end and live connections close at once;
  - single sign-on (REQ-SEC-007, 008): Entra ID, Okta, Google, any OIDC, SAML 2.0; connection
    check on save; test in a private window; switch on and off; email domains routed on the
    tenant's organization (Keycloak 26.8 domain routing); department and site from SSO on first
    sign-in (D-089 D6);
  - Admin › Sign-in and security, live, en/ar/ur, axe clean in three themes.
- [x] Session 2 — mail foundation (`app/shared/mail`, D-089 D3), invitations (SEC-018..020),
  reset (SEC-006), installation password policy and breached list (D1 c, D2; SEC-005), rate
  limits (SEC-035). PR #80 (D-099, D-103); e2e `invitations.spec.ts` and the full suite green
  on the shared stack.
  - [x] mail foundation: `app/shared/mail` (outbox `system.mail.queued`, worker send, retry with
    backoff, content purge), interface for lanes A and C in docs/architecture/mail.md;
  - [x] Keycloak's realm SMTP and e-mail theme from the same settings (D-099), en/ar/ur;
  - [x] invitations: invite from the person's record, resend, withdraw, accepted at first sign-in,
    7 days (1 to 30), live list (`invitations` channel);
  - [x] reset page `/password-reset` (console, portal; no session), 5 per address and 20 per
    network address an hour, always 202; admin "require a new password" (sessions end);
  - [x] password policy (installation-wide; read-only on multi-tenant installations) applied by
    the worker as `supportx-realm` (manage-realm only), breached list shipped (46,941 entries),
    Urdu policy messages and Urdu right to left on Keycloak's pages;
  - [x] audit-integrity banner axe fix (failing test first);
  - [ ] REQ-SEC-005 AC2's "try again at" lock-out message: session 3.
- [ ] Session 3 — MFA (SEC-022, 024, 025 with recovery codes), my account (SEC-028), idle
  warning and kept drafts (SEC-029 UI), the "everything through SupportX" e2e (SEC-017),
  Security administrator role (D7). Built on `feat/wp-039-session3` (D-104); waiting for: the
  e2e `sign-in-security.spec.ts` on the shared stack (QA lock), PR.
  - [x] lock-out: 15 minutes growing to an hour (LINEAR; Keycloak cannot double, measured), one
    message for every failed sign-in (en/ar/ur; a locked account reads like an unknown one);
  - [x] MFA policy per role (Appendix A defaults), counts, grace period; enforcement at sign-in
    and hourly; recovery codes offered at sign-in; admin reset (never one's own, audited, the
    person e-mailed); Security administrator role;
  - [x] My account (console My profile, portal My account): password, MFA set-up, recovery codes
    on Keycloak's pages with the current password asked; recent sign-ins; MFA reminder banner;
  - [x] idle warning 2 minutes ahead, sign-out at the limit; kept input in New incident (PR #87,
    agreed and reviewed with lane A; the record page and composer are lane A's);
  - [x] proved on Keycloak 26.8.1: TOTP enrolment from a link, wrong and old codes refused,
    recovery codes once each, credentials read and removed through the admin API.
- **Domain proof (D-098):** multi-tenant installations refuse SSO routing for unverified domains
  (guard built); the DNS TXT proof itself is WP-014d's. Session 2 also fixes the audit-integrity
  banner's axe failure (failing test first). OIDC is checked
  end to end by hand against Keycloak as the customer's provider; CI runs the SAML journey (in
  Compose, Keycloak cannot call itself on the browser's address, which OIDC would need).

### [ ] WP-040 — Connector framework and directory sync (lane B; D-118; session 1 of 2 built 2026-11-02, draft #150)
- **Plan:** ~/Desktop/wp-040-plan.md (approved 2026-10-29; decision 1 by the product owner, D-118).
- **Session 1 (built, draft #150, stacked on #134):**
  - [x] Connector registry `app.shared.connectors` and catalogue `GET /integrations/catalogue`
    (REQ-INT-001): categories, live status, edition through `has_feature` only, keywords;
    read-only with a reason without set-up rights (REQ-INT-013 AC1).
  - [x] Secrets store `connector_secrets` (REQ-INT-003, REQ-SEC-042), migration 0045 (expand):
    mailbox secrets copied sealed, never opened; old columns kept and still written; a store
    copy that cannot be read falls back, counted (`supportx_connector_secret_fallback`), logged by
    code and shown as degraded. "Ending in …" for display only, long random secrets and
    certificate thumbprints, never a password (product owner, 2026-11-02; enforced by the table).
  - [x] Runs, health and error list (REQ-INT-004, REQ-INT-005), migration 0049: failing after 3
    failed runs or at once on a refused credential; `connector.failing` / `connector.recovered`
    once each; runs kept 7 days, errors 90; mailbox fetches are runs; each tenant's
    `mailbox.failing` rule copied to `connector.failing` (alias kept until the contract step).
  - [x] Set-up rights per category `integrations.manage_<category>` (REQ-INT-013): permission keys
    are two-part, so not `integrations.<category>.manage` as the plan said (coordinator,
    2026-11-02). `mailboxes.manage` → `integrations.manage_email` by expand/contract (0049 copies
    every grant); `integrations.manage_identity` registered for session 2.
  - [x] Console: Admin › Integrations (catalogue by category, search by keyword, live status on
    `integrations.connectors_changed`, Arabic RTL); Admin › Mail uses the new key.
  - **Moved to session 2 (coordinator, 2026-11-02):** service identities (REQ-INT-012), built with
    directory sync, their first real user. Session 2 tests: kept out of pickers, seat counts
    (entitlement interface only) and sign-in; history tagged "integration".
  - **Later:** tenant-editable defaults (sync interval, rotation reminder, retention, failing
    threshold; D-041) with the session 2 settings screen; generalising the 14-day credential
    warning to every kind; the contract step (drop the mailbox secret columns, `mailbox.failing`,
    `mailboxes.manage`) once the store is proven.
- **Session 2 (in progress on #150):**
  - [x] `identity_access.user.status_changed` gains `reason` and `source` (defaulted, still v1;
    agreed with lane A).
  - [x] Service identities (REQ-INT-012), migration 0052: user type `service`, one per connector
    instance in `connector_identities` (RLS), made with the instance or at its next run, disabled
    (never deleted) when it is removed. A database check keeps it from ever signing in; it takes
    no seat, is left out of people lists, search, pickers and permission holders, and the people
    screens and imports cannot make, change or retype one (`PersonType` input,
    409 `service_identity_managed`). Its history says "integration". `identity_access.user.created`
    v3 carries `service` and `integration`. The downgrade keeps every row (disabled requesters).
  - [x] Entra ID sync (REQ-INT-063), migration 0053, on `feat/wp-040-entra`: a separate
    least-privilege sync app (User.Read.All, GroupMember.Read.All) by client credentials, its
    secret sealed in the store; `/users/delta` and `/groups/delta` (throttling honoured, an
    expired link starts over, Graph-only links); everyone or chosen groups; attribute mapping
    (address, names, job, employee ID, phones, department and site by name or code, never
    created; manager after the round); skips counted by reason and shown; an address match
    adopts the person (no duplicate); `users.directory_source`, directory-owned fields
    read-only in the API and the drawer ("managed by the directory"), imports leave them alone;
    mapped groups follow their directory groups; acts as its own service identity; every 30
    minutes (15 to 1440, per connector) plus "sync now"; catalogue entry; Admin › Integrations
    › Directories; labels in en/ar/ur.
  - [x] Leavers (REQ-INT-064): removed or disabled, or out of every scope group → deactivated,
    never deleted; their sessions and live screens end from the worker; `UserStatusChanged`
    with `reason="directory"`, `source="entra"`; the last administrator is never deactivated by
    a sync (counted as `last_admin_kept`); enabled again → reactivated with what they held.
  - [ ] AD/LDAP through Keycloak federation (D-118): next.
  - [ ] Tenant-editable connector defaults (D-041) screen: with AD/LDAP.

### [x] WP-017-FIX — WP-017 QA findings (lane B; D-093; done 2026-10-27)
Every bug of ~/Desktop/qa-wp017/QA-REPORT.md has a test named after its ID that failed first
(Vitest `admin/branding/branding.test.tsx` "WP-017-FIX", `tests/test_keycloak_theme.py`, the
Playwright `branding-admin.spec.ts` for the contrast bugs).
- [x] BUG-01 the preview draws the colours a save makes (server rule: own gradient, else the
  primary at both ends, else the default), never the ones saved before.
- [x] BUG-02 domains: a host that is not one is refused at the field as typed; the server's
  refusals (reserved, already used, limit) at the field; the certificate dialog checks PEM as
  pasted and shows the server's reason (wrong host, key mismatch …) and stays open.
- [x] BUG-03 a colour that is not #rrggbb/#rgb is flagged at once, never sent to the check, and
  Save stays disabled; a refused save says why at its fields.
- [x] BUG-04 readable tone tags in the contrast list (and the domain status tags).
- [x] BUG-05 the empty domain list text is readable in dark mode.
- [x] BUG-06 an image card without an upload shows the SupportX default image it stands for.
- [x] BUG-07 removing the logo drops the dark logo's and icon's waiting uploads; Save follows.
- [x] BUG-08 the sign-in page names the organization under the logo (escaped; readable in every
  theme).
- [x] BUG-09 brand images are checked on selection (type from the file's bytes, at most 5 MB and
  25 megapixels, at least 16 px, decoded by the browser; SVG refused, D-090) and never uploaded
  when refused; the server still checks on save.
- Housekeeping: the 8 QA uploads in scan_failed purged through the files service's own purge;
  the shared dev Keycloak recreated (timing agreed with lane A), so its sign-in page is branded.
### [~] WP-025 — SLA v1 on Temporal (lane A; D-115, ADR-037; sessions 1-3 of 4 built 2026-11-03)

Plan: ~/Desktop/wp-025-plan.md (approved). Four sessions (D-115 D1).

- [x] **Session 1 — calendars and business time** (#148, stacked on #144; migration 0044):
  - the `sla` module (feature `sla`, permissions `sla.view` for technicians, `sla.manage`);
  - one business-time service (`sla/domain/calendar.py`): any working week in a time zone,
    split shifts, periods across midnight (one period, owned by the day it starts), full and
    half-day holidays, daylight saving right on its day, around the clock;
  - the published table `docs/architecture/sla-business-time.md` (73 cases, read by a test)
    and a seeded property test `between(a, add(a, s)) == s`;
  - **special working hours for a date range** (product owner 2026-11-02, MVP for Pakistan and
    the Gulf; REQ-SLA-011 brought forward): e.g. Ramadan 09:00-14:00 with a Friday prayer break;
    inside the range its own week replaces the calendar's; holiday > range > week; ranges of one
    calendar never overlap (`exception_ranges_overlap`); table `sla_calendar_exceptions` in 0044;
    14 named rows in the case table (93 cases); the three business-time rules confirmed;
  - calendars, holiday lists and holidays (REQ-SLA-010, 012): two system calendars on first use
    (around the clock; Monday-Friday 09:00-18:00 in the default site's zone, D-115 D2),
    presets, iCalendar import with a skip report (size, line, event and day limits; byte,
    line and structured fuzz tests, and 46 hostile uploads over HTTP that answer 201 or 422),
    copy to next year flagged for review;
  - sites and support groups name their calendar (REQ-ADM-040, D-115 D3): organization stores
    `calendar_id` and asks the sla module through a check sla registers at import
    (`register_calendar_check`), so the packages never import each other in a loop; a
    calendar in use cannot be deleted and its page lists its users;
  - every write permission-checked, versioned (If-Match, 409 naming who), in history,
    audited (9 new actions), on the outbox; screens live via `sla.setup.changed`;
  - Admin › SLA screens (calendars, week editor, holidays, import, copy a year) and the
    calendar picker on the site and group forms; en, ar (all plural forms), ur;
  - tests: 130+ domain, 22 API/DB (RLS for every new table and for the site and group links),
    11 console.
  - **Not yet in session 1:** auto-close on the business-time service (waits for #140, which
    changes the same code); REQ-SLA-010 AC3 (how many open records a calendar change affects)
    needs the per-record SLA state of session 2; the e2e journey is in session 4.
- [x] **Session 2 — policies and due dates without timers** (#152; migration 0047, after 0044
  which now follows main's 0040):
  - policies, ordered targets by priority and kind, calendar source per target, settings
    (warning point, priority-change and reopen rules), the default policy seeded and always
    last (D-074); API with audit, outbox, If-Match and Idempotency-Key; "never matches" flag
    (REQ-SLA-001); conditions in the filter DSL on the incident fields minus SLA fields and
    timestamps, evaluated in memory;
  - the SLA on every incident save, in the same transaction (REQ-SLA-015..020, 029): apply on
    create, choose again when a condition field changes, recalculate or restart on a priority
    change, pause and resume by status category, met (on time, late, at resolution, D-115 D8),
    stopped on close or cancel, reopen resume or restart (a new round), a new site or group
    moves open clocks to its calendar; targets snapshotted on apply (D-115 D7); the record
    stamps its policy and due moments, with history (source `sla`) and events
    `sla.record.applied` and `sla.target.*`;
  - due dates set by hand (REQ-SLA-028, D-115 D11): `PUT /incidents/{id}/due-dates/{kind}`,
    permission `incidents.edit_due_dates` (not for technicians by default; admins hold it; there
    is no built-in group-lead role, so leads get it through a role), a reason, a future moment,
    who and why on the target, kept through priority and policy changes until cleared;
  - the record's SLA panel (`GET /incidents/{id}/sla`, REQ-SLA-038): policy, why, each target's
    state, due, paused, met, overdue, calendar, and "set by hand" with who and why; live under
    the record's history query; a card beside the properties until #159 gives it its section;
  - Admin › SLA › Policies (ordered list, up/down reordering, editor with the shared filter
    builder and the target table) and Settings; "Respond by" as a list field; the views
    "overdue" and "without SLA" read the stamped columns;
  - REQ-SLA-010 AC3: the calendar editor says how many open incidents a change reaches;
  - tests: SLA clock and API 22 DB tests (RLS for every new table), console 269 in the incident
    and admin areas.
  - **Moved to session 3:** "about to breach" and "breached" views and filters, which need the
    warning and breach stamps the timers set; the countdown column.
- [x] **Session 3 — warnings, breaches, escalations, the Temporal waker** (#172; migration 0054,
  after 0047):
  - PostgreSQL holds the truth, Temporal wakes (ADR-037): `sla.fire` stamps a due warning
    (`warned_at`) and breach (at the due moment, `time_passed`; now with `target_changed` after
    a recalculation) and runs due escalation levels, each exactly once, under the record's lock
    (record row first, then its clocks: one lock order for saves and the waker);
    `sla.next_wake` gives the next moment; four concurrent wakers run each level once;
  - the `sla__safety_net` schedule (60 s) fires anything more than two minutes late (D-115 D5);
  - escalation levels (REQ-SLA-022..025) per policy and target kind, at a business-time offset
    from the due time or the warning point, up to 8 per target, snapshotted on the record (D7);
    one run per clock and level (`sla_escalation_runs`, unique); held while paused, moved by a
    resume or a due date set by hand, cancelled when met, resolved, closed or canceled;
    recipients: assignee, group head, assignee's manager, requester's manager, department head,
    support groups, named people (API), with a fallback list when a relative is not set
    (REQ-SLA-023 AC1); actions: reassign to a group or person, raise the priority one step, a
    private note, each in its own savepoint, history from source `sla`, outcome on the run;
  - notifications through the incident source (no engine change; rule 8 notice to lane B):
    `incident.sla_warning`, `sla_breached`, `sla_escalated`, urgent; escalations go to the
    level's recipients (a new recipient kind), access checked at send time (AC3);
  - incidents stamp each target's state (`warning` past its point) and a breached flag that
    stays: list fields, filters, report dimensions, and the built-in views "about to breach"
    (exactly the records in warning, REQ-SLA-019 AC2) and "breached"; a firing writes history
    from source `sla` and a change event, so every open screen turns live;
  - Temporal: one `SlaClock` workflow per record (`sla:<tenant>:<record>`, queue `sla`, no I/O,
    continue-as-new after 100 turns); activities in `workers/sla_timers` (`make worker-sla`);
    the `sla__scheduler` consumer signals or starts it from the outbox's clock events (off
    without Temporal); time-skipping workflow tests with a replay check; Compose's dev Temporal
    creates the `supportx` namespace; Helm runs the `sla-timers` worker when
    `temporal.address` names a Temporal; `temporalio` 1.35 added (D-115) with nexus-rpc,
    protobuf and types-protobuf;
  - Admin › SLA › Policies: an escalation levels editor; the record's SLA panel shows Warning
    and each level in words with its state, time, hold and failed actions; history shows SLA
    states, due times and runs as labels, and why an escalation changed the record;
  - auto-close counts business days on the record's own calendar (its resolution target's,
    else operating hours): WP-020f D4 moved onto the one business-time service;
  - tests: 11 timer DB tests (warning once, breach stamp and AC2, levels once and cancelled,
    pause hold, fallback recipients, views, concurrency, auto-close calendar, RLS), workflow
    and replay, scheduler and escalation-domain unit tests, console 305 in the incident,
    admin and report areas.
  - **Moved to session 4:** the bundled Temporal in Helm (official chart on the CloudNativePG
    cluster, schema by admin-tools, D-017) and its backup and upgrade notes; the countdown
    column; the chaos test with real processes; REQ-SLA-026 tenant switch (V1); named people
    as recipients in the editor (the API takes them).
  - **For the product owner:** REQ-SLA-024 AC2 says a priority raised by a level keeps the
    running targets "unless the policy says so"; today it follows the tenant's priority-change
    rule (recalculate by default). A per-policy option would be a new setting.
- [ ] Session 4 — live panel and list columns, e2e (en, ar, axe, 390 px), load test, docs, QA.

### [~] WP-036 — Home page and live dashboards (lane C; sessions 1-2 of 2 built 2026-10-28)
Built on WP-035's engine: every widget is a report definition run through `POST /reports/run`, so
its numbers equal the report's and each viewer sees their own scope (REQ-DSH-028).
- [x] **Session 1 — backend.** `dashboards` (one versioned document: widgets, places, filter
  defaults), `dashboard_preferences` (home, favourites), `dashboard_role_defaults` (by role key);
  RLS on all three. Built-in "Service desk" and "My work" in code (read-only, copyable); `@me` in
  widget filters is the viewer. Private until shared (`dashboards.share`); homes: own choice, the
  role's (`dashboards.manage_defaults`, audited), the built-in role home. Events saved, deleted,
  home changed; realtime to the owner, or everyone for shared and just un-shared dashboards.
- [x] **Session 2 — console.** `/dashboards` picker (search, favourites first, ready-made, shared,
  mine, private/shared tags, star); dashboard page (home, copy, share, delete, edit layout);
  12-column grid (CSS grid, mirrored in RTL, stacked on narrow screens); edit mode with drag to
  swap, keyboard buttons to move and resize, remove, add widget (search over every report, or a
  quick chart with a live preview), undo, Done saves with If-Match and the conflict dialog; KPI
  tiles with trend against the previous period (good/bad by the measure) and a sparkline; chart
  widgets reuse the report viewer's chart and table, switch type for the viewer only, expand,
  export, open as report; filter bar (site, group, time range) on every widget, "not filtered
  by" marker; drill-down in a side drawer; live via the scope-partitioned list channels (at most
  one refresh a second), connection indicator, polling fallback; the home page shows the home
  dashboard.
- [x] **Follow-up — free-form layout** (D-110): `react-grid-layout` 2.2.4 in edit mode only (lazy),
  drag by the title and resize from the end corner, keyboard buttons kept, RTL mirrored
  (x' = 12 - x - w) and checked by `dashboards-grid.spec.ts` in English and Arabic.
- Not yet: SLA widgets and the SLA dashboard (WP-025); approvals waiting (WP-030);
  tasks and reminders widgets (their features); embedded page, text, availability, MonetX (V1).

### [~] WP-035 — Reporting foundation and built-in reports (lane C; D-100; ADR-033, ADR-034; sessions 1-4 of 4 done 2026-10-28)
Plan: ~/Desktop/wp-035-plan.md (approved with D-100). Branches `feat/reporting-port` (PR #72, the
port alone, so lane A can write the incident provider) and `feat/wp-035-reporting`.
- [x] **Session 1 — engine.**
  - Reporting port `app/shared/reporting` (ADR-033): a module registers a provider whose source is
    its own scope-filtered list query, filter allowlist and groupable fields. Reports therefore
    count exactly what the viewer could list (REQ-RPT-002, D-052), and analytics never names
    another module's tables.
  - `analytics` module: report definition (versioned JSON), compiler (groupings, date buckets in
    the viewer's zone, ageing buckets, measures, drill-down filter per row), standard measures
    defined once (REQ-RPT-004), runner, 23 built-in incident reports (set A), saved reports,
    shared folders, favourites, permissions `reports.view` (moved from the reserved list),
    `reports.create`, `reports.manage_folders`.
  - Read-only reporting: role `supportx_report` (NOLOGIN, SELECT only, checked by the RLS guard),
    entered with `SET LOCAL ROLE`, read-only transaction and `statement_timeout`; its own pool and
    `reporting_database_url` for a replica; per-tenant concurrency cap (in-process).
  - Migration 0027: `report_folders`, `reports`, `report_favourites` (RLS, soft delete, events,
    field history) and SELECT for the reporting role on `work_items`, `work_item_followers`,
    `field_changes`.
  - Server-side labels (ADR-034): `make labels-json`, `app.shared.labels.label()`, checked on
    both sides. Labels for every new code in en, ar and ur.
  - Tests: 10 domain; 11 with Postgres (scope parity for five users incl. drill-down counts,
    tenant isolation, read-only role and timeout, ageing, custom-field grouping, time zones,
    built-ins run without set-up, copy/share/folders/permissions/outbox); labels checks.
- [x] **Session 2 — viewer** (2026-10-27, branch `feat/wp-035-viewer`).
  - Console `/reports`: favourites, built-in reports by module, "My reports", shared folders,
    search in the UI language, folder create/delete with "where do its reports go"
    (REQ-RPT-045), live.
  - Report viewer (REQ-RPT-050): title, description, filters in words, totals, "data as of" and
    time zone; filter builder, grouping (date buckets incl. ageing), second grouping, measures
    with their definitions, chart type, chart/table toggle; table with totals row; chart with a
    data-table alternative and keyboard drill-down on rows (REQ-DSH-047); drill-down drawer on
    the incident list with the row's filter (REQ-RPT-037); "save as my report", save changes,
    delete, star (REQ-RPT-019); live refresh on the counted list, at most once a second.
  - `packages/forms` FilterBuilder (D-100 D6): generic over the API's field allowlist; a
    condition without a value blocks running and saving, with the reason (REQ-RPT-029 AC2).
  - `packages/charts` kit (REQ-RPT-044): bar, stacked bar, line, area, doughnut, gauge, KPI and
    table; P1 has one colour everywhere (priority colours now in `incidents/priorityColours.ts`);
    LTTB sampling for large series.
  - Reports library live: a private report change reaches only its owner's channel, a shared
    one an ID-free tenant broadcast.
  - Tests: 5 filter builder, 3 chart kit, 3 console (home, viewer with drill-down, blocked run),
    2 realtime routes.
  - Carried to session 3: Sunday week start for Arabic tenants and tenant-editable query limits
    (both need the per-tenant report settings that export adds); e2e and axe in English and
    Arabic (needs the shared dev stack and the QA lock).
- [x] **Session 3 — export and settings** (2026-10-28, branch `feat/wp-035-export`).
  - Exports are background jobs (REQ-RPT-058): the API validates and records the request
    (`reports.export`, 503 without storage); the consumers worker rebuilds the requester's
    subject (`identity_access.subject_for`, lane B #82), runs the report read-only as
    supportx_report with the background time limit, streams rows into the file, uploads it and
    marks it ready or failed with a reason shown in "My exports" (REQ-RPT-056). Downloads only by
    the requester, signed in, until expiry; exported and downloaded are audited (AC3).
  - CSV with BOM, XLSX through openpyxl write-only (RTL sheets for ar/ur, typed numbers and dates,
    summary and records sheets), PDF with WeasyPrint: bundled Noto Sans and Noto Naskh Arabic
    (OFL), inline SVG chart, a URL fetcher that serves only the bundled fonts, with tests that
    nothing else is fetched (D-100 D8). Formula injection neutralised in every text cell (D-100).
  - Worker image: `worker` target with Pango and the `pdf` dependency group; the API image has no
    WeasyPrint (checked). Consumers Deployment, `make images`, k3d import, Trivy and SBOM use it;
    CI job `pdf (worker image)` runs the PDF tests in the `worker-test` target.
  - Per-tenant report settings (D-041): week start (Sunday when the default site speaks Arabic),
    interactive time limit, export link days, rows per file; migration 0029.
  - Server-side names: a resolver registry in the reporting port; resolvers in organization,
    work_items and metadata (written by lane C for lane A's review), registered at import so the
    consumers worker has them.
  - Console: Export dialog, live "My exports", report settings for admins.
  - Tests: 9 writers, 5 PDF (local with Pango and in the worker image), 5 database (scope-limited
    CSV with names and neutralised formulas, Arabic XLSX, permission and storage, PDF without the
    worker image fails visibly, settings and Sunday weeks), 1 console.
  - Volume (D-100 D5): `tests/db/test_reports_scale.py`, every built-in report and the widget
    totals at 1M incidents as an admin and a group-scoped technician, median ≤ 2 s, in the
    opt-in workflow `report-scale.yml` (nightly and on demand; never on a laptop, product owner
    2026-10-28). Results in the session log.
- [x] **Session 4 — scheduled reports** (2026-10-28, branch `feat/wp-035-schedules`; D-100 D3).
  - Schedules (REQ-RPT-052): daily (optionally on chosen weekdays), weekly, monthly (day 1-28),
    at a wall-clock time in the schedule's own time zone, from a start date to an optional end;
    the next run is computed on the wall clock, so it stays at 07:00 local across DST changes.
    Pure domain `analytics/domain/schedule.py`.
  - Recipients are people (up to 50) and groups (up to 200 people once expanded). Each gets
    their own file, built with their own scope and language (REQ-RPT-053): the worker rebuilds
    each recipient's subject, renders through the export path (`render_file`, formula
    neutralisation included), and queues one mail per person through lane B's
    `app.shared.mail.queue_mail` (D-089), branded, attachment ≤ the mail limit.
  - `identity_access.mail_recipients` (written by lane C for lane B's review): active users with
    an address, in their language.
  - Every run records its result (sent, failed and why); 3 failed runs in a row, a removed report
    or an owner who lost access pause the schedule with the reason (REQ-RPT-056); resume, pause
    and delete with If-Match. Without outgoing mail, schedules cannot be made (409) and the UI
    says why (REQ-RPT-055).
  - Minute sweep (`analytics__report_schedules`, every tenant) writes a `report_schedule.due`
    event per due schedule; the consumers worker runs it. Owner sees changes live (personal
    channel). Permission `reports.schedule` (admins by default).
  - Migration 0031 `report_schedules` (RLS, soft delete, partial due index).
  - Console: "Schedule" on a report, "Scheduled reports" drawer on the reports home with next
    run, last result and pause/resume/delete.
  - Tests: 5 domain (DST, monthly, weekdays, end date, validation); 6 database (no mail → 409,
    per-recipient scope and language with group expansion, removed report pauses and resume,
    validation codes, mail_recipients, RLS); 1 console.
- [ ] Report set B with lane A's WP-020e (worklogs), WP-020f (reopen, FCR, completion), WP-025
  (SLA), WP-030 (service requests, approvals); backlog over time and time in status (field
  history source).
- Lane A's incident provider `work_items/service/reporting.py` and the report indexes are on main
  (#74, migration 0025); the report DB tests run through it (2026-10-28, no test stand-in left).
- E2E (`reports.spec.ts`, 2026-10-28, under the QA lock): home and built-in report in English and
  Arabic with axe; schedules drawer live. Found and fixed: status tags below contrast (now
  `ToneTag`); a worker without a service it needs left exports "running" for ever, now they fail
  visibly ("report_failed"), schedule runs record the failure, and a minute sweep fails exports
  lost by a crashed worker. Found for lane B: `subject_for` needed the entitlement service the
  consumers worker never installed (lane B #91).
- CSV export journey added after lane B's #91 (2026-10-28): the file turns ready live and
  downloads with labels; `reports.spec.ts` 4/4 on the shared stack.
- 1M-row volume test: GitHub workflow `report-scale.yml` (see Session 3).

### [x] WP-027 — Search and record pickers (lane B; D-085; ADR-029; done 2026-10-26, 1 session)
Branch `feat/wp-027-search`. REQ-INC-085.
- Search port `app/shared/search`, with PostgreSQL full-text and pg_trgm as the MVP engine
  (D-085). Migration 0020 adds:
  - pg_trgm, `sx_search_normalize` and `sx_search_vector`;
  - generated search columns and GIN indexes on `work_items` and `users`, declared as
    `unmapped_column` so the ORM never loads or returns them.
- One normalisation for Arabic, Urdu and Latin text (diacritics, letter variants, digits), in
  SQL and Python; a test proves they agree.
- Matching: every word must match, by prefix, English or Arabic stem, or trigram typo tolerance
  (subjects and names). Urdu word forms match by prefix.
- `GET /incidents/search` (`q`, `ids`, `requester_id`, `status_category`). It starts from the
  list's own scope query (`staff_rows`), so results equal the list for every scope rule (D-052,
  D-068; tested for IDs too). It matches by display ID (Arabic and Urdu digits too, any status or
  assignee, ranked first), subject and description words, and requester or on-behalf-of name or
  email.
- People search: `GET /users?q=`, the user pickers, the admin Users page and the assignee picker
  (`policy.holders`). Half names, typos, Arabic hamza forms, Urdu letters typed as Arabic, email
  parts.
- Console:
  - Ctrl+K palette: incidents found by ID, words or person, with requester and status in words;
    recently viewed incidents while nothing is typed (kept per user in the browser); live while
    open.
  - `IncidentPicker` for link and merge dialogs: recent, same requester, search, status filter,
    never the record itself, live.
  - People pickers keep the email on the second line.
- Labels in en, ar and ur (including the palette's Urdu labels).
- Tests: 12 unit; 10 with Postgres (search), plus the users, incidents and migration suites;
  4 console; e2e `search.spec.ts` (Arabic word form, typo, recent, axe in light, dark, high contrast and
  Arabic).
- Follow-ups:
  - the link, merge and parent dialogs (WP-020e, V1) use `IncidentPicker`;
  - search in the incidents list (WP-020d, lane A) can switch from the `contains` filter to the
    port;
  - custom-field text joins the vector in WP-026 (lane A, migration 0021).

### [x] WP-022 — Files and safe attachments (lane B; D-082; ADR-028; done 2026-10-26, 3 sessions)
Plan: ~/Desktop/wp-022-plan.md (approved with D-082). Branch `feat/wp-022-files`.
- [x] **Session 1 (backend core, 2026-10-26):**
  - shared platform service `app/shared/files`, mounted by the `system` module;
  - migration 0018: `files`, `file_links`, `tenant_data_keys`, `tenant_storage_usage`,
    `file_settings`, all with RLS;
  - real-type sniffing and blocking (default list of executables and scripts, tenant-editable);
  - safe names; chunked AES-256-GCM with range reads; per-tenant data keys wrapped by the
    installation key ring (`SUPPORTX_FILES_KEYS`; rotation and re-wrap);
  - streaming upload through the API (size, quota, type checked before storing; S3 multipart);
  - scan consumer and sweep with clamd, no-scanner and fake adapters (retries, "could not be
    checked", rescan);
  - lossless EXIF/GPS/XMP stripping (orientation kept) and Pillow thumbnails under bomb limits;
  - links valid 5 minutes, bound to the user; ranged content route with nosniff and sandbox CSP;
  - inline images and thumbnails; delete with a 24 h grace; purge; purge with the record;
  - `storage_gb` licence limit; rules, usage and scanning status for administrators (warnings
    for no scanner, unreachable scanner, signatures older than 7 days, unscanned and failed
    files); hourly scanner check with a metric;
  - the work_items access port (private-note files for staff only);
  - audit actions; labels en/ar/ur; dev key ring and clamd address; chart env wiring;
  - `docs/architecture/files.md` (backup and restore of the key ring, rotation);
  - tests: 35 unit, 19 with Postgres and S3 storage.
- [x] **Session 2 (screens and editor, 2026-10-26):**
  - api-client `files.ts`: raw-body uploads with progress (XHR, same CSRF, client and idempotency
    headers), record files, links, delete, drafts attach, rules, usage, status, rescan;
  - `@supportx/ui` `files/`: `Attachments` (drag and drop, picker, paste; the tenant's size and
    type rules checked before sending; at most 3 uploads at once with progress; live state in
    words; preview, download, delete, rescan; "Staff only" for private notes), `FilePreview`
    (image in the dialog, PDF in the browser's viewer via a fresh link), `FileStateTag`;
  - incident page: the record's files under the description; each reply's or note's files on its
    card; the composer takes files and pasted images as drafts and attaches them to the saved
    entry; the description's pasted images too; live through `files.changed` on the record
    channel (drafts: the personal channel, `usePersonalChannel`);
  - editor: `@tiptap/extension-image` node holding only `data-file-id` (uploading, checking,
    blocked or image), paste and drop of image files; lane A's placeholder replaced; the
    server sanitiser keeps `<img data-file-id alt>` only (UUID-checked, no `src`, no remote or
    `data:` images); read-only view fills the address from the ID;
  - Admin > Files (rules with If-Match, usage against `storage_gb`, scanning status) and the
    administrators' banner (`files.manage`);
  - inline PDFs are served without CSP `sandbox` (browsers refuse their PDF viewer in a sandbox;
    still `default-src 'none'`), every other file with it;
  - labels en/ar/ur; tests: ui 10, console 4, API 21, sanitiser.
- [x] **Session 3 (platform and hardening, 2026-10-26):**
  - ClamAV chart component: clamd and freshclam as non-root, signatures init container, PVC,
    network policy, private mirror value; `deploy/scripts/clamav-signatures.sh` for air-gapped
    signature bundles; verified 2/2 Running on k3d, EICAR found by the real clamd;
  - operator commands `python -m tooling.files_keys check|rewrap|rotate` (tested);
  - uploads reworked for load: owner, size and quota in a short transaction of their own, the
    stream with no database connection held, at most 8 writing per process
    (`SUPPORTX_FILES_UPLOAD_CONCURRENCY`), 5 MiB S3 parts; load check 50 x 25 MB all stored,
    57 MB/s, peak 389 MB;
  - scans stream to clamd (no whole file in the worker); image processing only up to 50 MB;
    consumers memory limit 768Mi;
  - stack-smoke runs a real ClamAV (signatures cached weekly); Playwright journey
    `files.spec.ts`: checking then ready live, image preview, EICAR blocked, too-large refused,
    axe in light, dark, high contrast and Arabic, Admin › Files;
  - `docs/architecture/files.md`: memory and connections, ClamAV, offline signatures, key
    commands.
  - Not built: a per-tenant "rotate data key" button for administrators. D-082 D2 rotation is
    covered by the operator command; a tenant button adds little (data keys are wrapped by the
    installation key either way). **V1** (D-084).

### [x] BRAND — SupportX branding (lane B; product owner request; D-078; done 2026-10-26)
- **Goal:** The SupportX logo and colours everywhere SupportX shows its own brand, from one place
  that WP-017 replaces per tenant.
- **Done:** `make brand-assets` (`backend/tooling/brand_assets.py`, standard library only) makes
  every asset from `docs/brand/supportx-logo-dark-text.png`: logos with dark text, with white
  text and in one colour, icon, `favicon.ico` (16/32/48), 180/192/512 px icons, `site.webmanifest`,
  Keycloak login theme `supportx`, and `docs/brand/preview.png` (everything on white and
  #141414). Colours in `packages/ui/src/brand/palette.json`: primary #7e40d1, gradient
  #6060de → #951ab6, all pairs AA (high contrast AAA); `make lint` checks them. Logo in the
  console top bar and sidebars (icon when compact), portal header, portal welcome band in the
  gradient, header gradient accent, favicons, pre-load splash, session, sign-in-error and crash
  screens, a new About dialog (version from `/api/v1/health`), and the Keycloak login page
  (Compose mount, Helm ConfigMap, realm `loginTheme`). Links use the brand colour in every mode
  (Ant Design's default blue was 4.1:1). Product name label "SupportX". e2e `branding.spec.ts`
  (axe in light, dark, high contrast, Arabic RTL). `docs/architecture/branding.md`.
- **Upgrade step (2026-10-26, product owner request):** `tooling/keycloak_theme.py` gives a realm
  without a login theme the `supportx` theme and never replaces a chosen one; a chart Job per Helm
  revision (`keycloak.setLoginTheme`) and `make keycloak-theme` for Compose. Applied to the shared
  dev Keycloak (container recreated with the theme mount) and to k3d (Helm upgrade).
- **Not done:** e-mail templates (none exist yet; WP-023/WP-024 use the same files). Per-tenant
  branding is WP-017.

### [x] WP-018 — Tamper-evident audit log (D-034; MVP per D-058; D-076; ADR-027; done 2026-10-26)
Plan: ~/Desktop/wp-018-plan.md (approved with D-076). Three sessions.
- [x] Session 1 (backend core): module `audit`, migration 0014 (numbered 0013 until lane A's
  0013 merged first) (partitioned `audit_entries`,
  queue, chain, personal data, anchors, settings, verification runs; definer functions
  `audit_seal`, `audit_erase_subject`, `audit_tenant_ids`, `audit_ensure_partitions`),
  `audited` / `audit_read` route dependencies, refused-attempt observer and probing alert,
  sealing consumer, module schedules in the consumers worker (seal sweep, anchors, daily and
  weekly verification, partitions), Ed25519 anchors with key rotation, verification, erasure,
  Auditor system role, API (`/audit/entries`, `/audit/status`, `/audit/verification-runs`,
  `/audit/settings`), wiring of every existing privileged route and sign-in, labels en/ar/ur,
  ADR-027, D-076.
- [x] Session 2: shared storage component (`app/shared/storage`, aioboto3, S3 API only) and a
  minimal single-node SeaweedFS 4.48 in the Helm chart (dev and single-node profiles; smoke-
  tested on k3d in a throwaway namespace, auth enforced); exports (JSONL/CSV, signed manifest,
  standalone `verify_export.py`, 7-day expiry, visible failures), saved searches, realtime list
  channel, history link on incidents (REQ-AUD-006), console screens (Admin › Audit log: log with
  filters and the live "new entries" pill, entry drawer, integrity panel, exports, settings) and
  the console banner; signing key and storage keys in the chart and `deploy/scripts/secrets.sh`
  (missing keys are added to an existing Secret, existing values never changed); CI runs
  SeaweedFS for the export tests.
- [x] Session 3: retention (`audit__retention`, daily): whole months past retention archived to
  `audit/archive/<tenant>/<yyyy-mm>.zip`, read back and verified, then `audit_advance_cutoff()`
  hides them by RLS and deletes their personal rows; `audit_drop_expired_partitions()` drops a
  month once every tenant has passed it. Failures (no or failing storage, unsealed entries, out-
  of-order positions, unverifiable archive) leave a failed row, an audit entry, the
  `archive_failed` banner, a metric and an error log. Restore for investigation
  (`audit_restored`, 7 days, verified again), Admin › Audit log › Archives tab, labels en/ar/ur.
  Verification and exports start after the archived positions; entry lookups are bounded by
  time (18x faster verification). Volume test: 100k in CI, 10M nightly
  (`.github/workflows/audit-scale.yml`). `docs/architecture/audit.md`, e2e journey
  `audit.spec.ts`.
- **Not done in WP-018 (follow-ups):**
  - partitioning and retention of `field_changes` (the WP-012 field history). It is the work
    item engine's table, owned by lane A. Rule decided (D-077): kept while the record exists,
    purged with the record (audited); monthly partitioning later;
  - WI-020 AC3 (purge records after retention), which waited for this WP;
  - archives hold at most 1M entries per month (the export limit) and are built in memory. A
    month above that fails visibly (`audit_export_too_large`); a streaming archive is needed
    before a tenant reaches that volume.
  - **10M sealing throughput (fixed, migration 0017, branch `fix/audit-seal-volume`):** the
    first full 10M run on GitHub (run 40280703924) sealed all 10M entries but at 875/s. Measured
    on one batch of 5,000 at 10M (98 partitions): the batch query read the tenant's whole log
    (hash join or entry-driven nested loop, about 10 s) and was JIT-compiled on every call
    (677 functions, 2.1-2.5 s). Not the partition count as such: the test's 98 partitions are
    realistic for long retention, so the test spread stays. Fix: batch from the queue, entries by
    key (LATERAL), `jit = off` on `audit_seal`. After: one batch query 11.9 ms; sealing at 10M
    18,000-29,000/s locally (was about 1,100-2,000/s locally with the old function); 100k test
    44,572/s (was 8,415/s).
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

One file per session in `docs/progress-log/` (D-123); `make progress-log` renders them
newest first to `docs/_build/PROGRESS-log.md`. Add an entry as a new file, never here.
