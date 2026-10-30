# SupportX v2 — Progress

## Current status

- **Stage:** 0 — Foundation (architecture.md §17). In progress: 14 of 16 work packages done
  (WP-014 = part 1 of 4; 014b-d are planned below).
- **Last completed:** WP-020f (resolution, closure, reopen and cancel; D-107), 2026-10-28.
  Before it WP-029-FIX (D-105) and WP-029 parts 1 and 2 (D-097, D-102, ADR-035); WP-021-FIX
  (D-096); WP-021 (D-092, ADR-032); WP-026 (custom fields). Lane B: WP-039 sessions 1-3,
  WP-023 notifications (D-106, in review).
- **Next work package:** WP-020d e2e and QA round (built, draft #114), then WP-020e (tasks,
  worklogs and links, which also register open-work checks) and WP-025 (lane A). Lanes: see docs/LANES.md.
  The shared dev stack runs from `../supportx-v2-stack` (main).
- **Other open packages:** WP-015 (clickable prototype), WP-013 (licence core), WP-014b.
- **Lane C (reports, dashboards and knowledge):** WP-035 sessions 1-4 done (engine #73, viewer
  #77, export #84, scheduled reports #88), on lane A's incident source, e2e in English and Arabic;
  the 1M-row volume test runs in GitHub (`report-scale.yml`; slowest median 0.73 s at 1M). QA
  round done (~/Desktop/qa-wp035, 8 bugs), all fixed in WP-035-FIX (#103). WP-036 dashboards
  merged (#106), free-form layout follow-up (D-110, #115). WP-033 knowledge (plan D-108, moved
  from lane B): session 1 (backend core) built, PR open; sessions 2-4 next. Lanes and claimed
  numbers: docs/LANES.md.
- **Working mode:** two lanes (MVP build plan): lane A = the WP-020 chain (main folder), lane B =
  WP-018 audit log (done 2026-10-26), then branding (done 2026-10-26, branch `feat/branding`,
  D-078). Lane B's next WP follows the MVP build plan.
- **Blockers:** None. Homebrew, k3d 5.9.0, kubectl 1.37.1, Helm 4.3.1 and Rust 1.99.1 are installed
  on the dev Mac; Docker Desktop has 12 GB (D-038).
- **Repository:** https://github.com/devhat-pm/supportx-v2, **temporarily PUBLIC** (D-018) until
  the account billing problem is fixed; then set back to private (D-015).

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

### [ ] WP-020d — Views, columns, bulk and export (D-111, approved; built 2026-10-28, QA next)
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

### Planned after WP-020 (sequence from the WP-020 plan)
WP-020b conversation, notes and followers · WP-020c incident settings screens and templates · WP-020d views
and bulk · WP-020e tasks, worklogs (time) and links · WP-020f resolution and closure · WP-021 people
and departments · WP-022 files (aioboto3, D-054) · WP-023 notifications · WP-024 email channel ·
WP-025 SLA v1 with Temporal (D-055; needs parity file 03) · WP-026 custom fields · WP-027 search ·
WP-028 portal incidents (needs parity file 02). Open item from D-052: the first-run setup must offer
"technicians see all incidents" vs the group default.

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

### 2026-10-28 — WP-020d: views, columns, bulk and export (lane A)

- Built to the approved plan; defaults D-111 (approved with group sharing). Backend: new
  built-in views, saved views, list settings, list fields, view filters, bulk jobs (migration
  0038, renumbered after 0035 dashboards, 0036 knowledge and 0037 mailboxes). Console: column chooser, view editor with the shared
  filter builder, time range, search chips, page size, selection across pages, bulk dialog and
  progress, export. Draft PR #114; e2e and the QA round next, then WP-020e.
- Lane C found that migration 0034's data step changed no rows under FORCE RLS; confirmed with a
  test and fixed in #116 (loop per tenant).
- Merges now go through `gh pr merge` without `--admin` (branch protection: 8 required checks,
  no bypass, product owner 2026-10-28). Cross-lane reviews are posted as PR comments.

### 2026-10-29 — WP-024 email channel, session 1 (lane B)
Plan: ~/Desktop/wp-024-plan.md. Defaults: D-109, approved with customer-registered OAuth apps
and the held-mail review queue as MVP.
- **Mailboxes** (`integrations` module, migration 0037 after main's 0036): IMAP with TLS by
  default and plain only when allowed (audited), passwords sealed with the installation key
  ring. Admin › Mail shows each mailbox's state and reason and how much mail waits, with
  add/change/test/remove, refusals at the form, the shared conflict dialog and live updates on
  the tenant channel (Arabic counts in six forms).
- **Fetching** every 2 minutes. A message is changed on the server only after it is stored, and
  the `mail_fetched` ledger makes each message count once. Loops (our own addresses), floods,
  too-large mail and automatic mail (out-of-office, bounces, lists) create nothing. Strangers
  follow the mailbox's policy and get a polite answer.
- **Incidents** (work_items implements the inbound port; lane A reviews):
  - new mail becomes an incident in the requester's name, with channel e-mail and the
    mailbox's group as entry group (#110);
  - the requester's reply lands on its incident through `add_requester_reply` (#105). It
    resumes or reopens the incident; a late reply starts a follow-up whose ID is answered to
    the sender in their language;
  - an out-of-office is recorded, moves nothing and notifies nobody;
  - a technician's mail on a record is held ("not the requester");
  - a refused create is held with the fields a template or rule needs.
- **Threading:** notification e-mail subjects carry "[INC-12]". A reply without the token is
  matched by In-Reply-To/References against the delivery log (`notifications.records_for_mail`).
  The quoted history is dropped.
- **Review queue** (D-109 (9)): held and too-large mail per mailbox, each with its reason. An
  admin hands it in again (no flood check) or discards it; both are audited. Held mail keeps its
  copy until then.
- **Docs:** `docs/guides/mail-oauth-apps.md`, a step-by-step guide to the customer's own
  Microsoft Graph and Gmail apps (session 2 uses them).
- **Tests:**
  - parser and routing units;
  - ledger, policy, RLS, fetch state, queue and follow-up answer on PostgreSQL;
  - the real incident services;
  - the mailbox API;
  - the IMAP reader against a private GreenMail (test-only image);
  - console tests.
  Full `make check` green: 1732 passed, 7 skipped, all opt-in (volume and load variables,
  WeasyPrint).
- **Session 2:** Microsoft Graph and Gmail, attachments from mail. Next for lane B: the
  dev-profile Mailpit on k3d (product owner), which turns the skipped cluster mail tests back on
  (#125's `SUPPORTX_E2E_MAIL_URL`).

### 2026-10-28 — Worker resilience: PostgreSQL and NATS restarts (lane B; must-fix before the pilot)
- **Cause:** at 14:37 the shared stack's relay and fan-out died when PostgreSQL and NATS
  restarted, and nothing brought them back.
  - The relay counted only connection errors as outages; "the database system is shutting
    down" (`CannotConnectNowError`) crashed it.
  - Monitoring calls ended the process on a NATS error.
  - Consumers charged database outages to events as attempts, so a long outage dead-lettered
    them.
  - Readiness said "started", not "connected".
- **Fix:** see events.md, "When PostgreSQL or NATS restarts".
  - Settings: `SUPPORTX_WORKER_GIVE_UP_SECONDS` (300) and
    `SUPPORTX_EVENT_BACKLOG_STALLED_SECONDS` (120).
  - `/ready` gains `event_delivery: ok|stalled` and the reasons `disconnected` and `backlog`.
  - Administrators see a banner.
- **Tests:**
  - `tests/resilience/test_worker_restarts.py` restarts real containers: every event is
    published and claimed once, nothing is dead-lettered, the relay is unready during the outage
    and both workers survive; a worker exits 1 past its give-up time. CI job "worker
    resilience".
  - The same test against main fails: ready while PostgreSQL was down; never exits.
  - Plus 14 unit tests, probe tests and a `/ready` test.
- Also: `GET /notifications/status` reads the app's settings, never a fresh `backend/.env`
  (found by lane A).
### 2026-10-28 — Dashboard widget library (D-114, lane C)

- Product owner request after using the dashboards: "Add widget" opens a searchable catalogue
  by module and section (43 curated widgets plus every built-in report); SLA and approval widgets
  appear under "coming later" with the package that brings them.
- Engine: flow report (created, resolved, backlog per day/week/month), `@my_groups` and `@me`
  resolved on the server for every run, records widgets (short lists through the entity's own
  list API), four new measures (overdue, due today, awaiting first response, reopened).
- Built-in Service desk (17 widgets) and My work (9) are placed from the catalogue.
- Tests: 8 DB tests (flow numbers per day and per viewer, `@my_groups`, records checks, every
  catalogue widget runs in a technician's scope), 5 Vitest, one e2e journey; label tests cover
  every widget, section and measure in en/ar/ur.
- Backlog per bucket uses each record's own timestamps (no history replay); a cancellation
  counts from its last status change. Recorded in D-114.

### 2026-10-28 — WP-039-FIX: the five WP-039 QA findings (lane B)
One test per finding, named after it (~/Desktop/qa-wp039/QA-REPORT.md):
- **BUG-03 (high):** at the idle limit the screen did not sign out. The server had already ended
  the session, logout answered 401, and the 401 was swallowed. `useLogout` now treats 401 as
  "already signed out" and clears the session (`api-client/src/qa-wp039.test.tsx`).
- **BUG-01:** after "Send again" the first link still worked. Keycloak cannot withdraw one link,
  so resending makes an unused invitation account afresh, and the earlier link names an account
  that no longer exists (`test_bug_01_sending_again_stops_the_earlier_link`). Not covered: an
  account that existed before the invitation (no password yet) keeps its earlier links until
  they expire; it is not ours to delete.
- **BUG-02:** a dead link showed the sign-in failure text. The theme's `error.ftl` now shows
  "This link no longer works…" (en/ar/ur), because a sign-in failure never renders on the
  error page.
- **BUG-04:** Urdu for all 100+ texts of Keycloak's pages that SupportX shows. The test pins the
  key list from Keycloak 26.8.1's templates and refuses English left in the Urdu file.
- **BUG-05:** the Arabic update-password title is now "تحديث كلمة المرور", not "Password
  updated".
- **Systemic lessons checked:** the WP-039 screens use the shared conflict dialog and show
  refusals at the form (#98); no counted labels were added.

### 2026-10-28 — WP-033 session 1: knowledge backend core (lane C)

- Knowledge module (D-108): settings, article types (file 08 Appendix A defaults on first use),
  topic tree (six levels, move with subtree, delete moves the articles first), articles with a
  first draft, autosave with If-Match, one open draft per language, new version from the
  published one, translations. Migration 0036 with RLS on all five tables; a trigger keeps
  published and superseded versions unchanged (REQ-KB-020 AC2).
- Permissions: the 11 D-108 (7) permissions, declared by the module with role defaults
  (technician: view/create at group, edit own and submit at own; requester: view at own). The
  reserved `knowledge.view`/`knowledge.manage` left identity's list (lane B told); custom roles'
  `knowledge.manage` becomes create + edit own + submit. That data step runs once per tenant
  with app.tenant_id set, because FORCE RLS hides every row from a migration without it. The
  same issue was found in 0034 and lane A fixed it (#116).
- Who reads what: staff by technician audience (all or their groups); drafts only for the
  author, owners and approvers; requesters get nothing from staff paths (their portal reading
  is session 2). Lists, single reads and search share one predicate (REQ-KB-048).
- Rich text: `div[data-callout]` with the four callout kinds is kept by the sanitiser.
- Bug found by the tests: changing only the expiry date skipped the review/expiry check, so
  the database constraint answered with a 500. Fixed in the service.
- Not in this session (sessions 2-4 per D-108): review and approval, publish/withdraw,
  requester portal reading, attachments (files owner type with lane B), console and portal
  screens, knowledge-manager role seed, department audiences for requesters.

### 2026-10-28 — WP-020f: resolution, closure, reopen and cancel (lane A)

- Built to the approved plan (~/Desktop/wp-020f-plan.md) with the product owner's change:
  auto-close counts only from when the requester was told, is off by default and cannot be
  switched on while no channel reaches requesters. Defaults in D-107 (pending review).
- Ports for later packages: `register_open_work` (WP-020e, WP-030), `register_requester_channel`
  and `resolution_notified` (WP-023/024/028; lane B has the follow-up on its WP-023 list).
- Also: ToneTag falls back to the neutral tone for an unknown tone instead of taking the page
  down (the load-dependent "reading 'color'" Vitest failures); `docs/specs/parity/mvp-build-plan.md`
  WP-043 gets the database-level `updated_at` stamp (product owner).

### 2026-10-28 — WP-039 QA round and WP-023 session 1 (lane B)
- **WP-039 QA** on the shared stack (~/Desktop/qa-wp039/QA-REPORT.md):
  - the e2e journeys pass 10/10;
  - the lock-out message is identical for a wrong password, an unknown address and a locked
    account in en, ar and ur;
  - deactivation ends sessions at once.
  - **5 bugs for WP-039-FIX:** an old invitation link still works after a resend; a withdrawn
    link shows the lock-out text; **at the idle limit the screen does not sign out**
    (`IdleWatcher`); Urdu Keycloak pages are mostly English; the Arabic update-password
    title says "Password updated".
- **WP-023 session 1:** see the WP entry. D-106 is pending review.
- **CI follow-ups (#96, merged):**
  - the shard weights now come from CI's own timings, and the shards are even;
  - 2 workers per shard were 10–25% slower than 4, so CI keeps 4.
### 2026-10-28 — WP-029-FIX: the WP-029 QA findings, fixed at their cause (lane A)

- Every finding of ~/Desktop/qa-wp029/QA-REPORT.md fixed with a test named after its ID (see
  WP-029-FIX above), plus the availability follow-up; systemic rules in D-105: refusals at the
  form and never as error toasts, error labels always get their params (two CI checks), every
  counted label has its plural forms (CI check), one shared conflict dialog naming who, when and
  what in every editor, availability set by leads and admins with history, refused moves name
  who may run them.
- Small additive edits in lane B and C modules (409 details via `stale_version`; identity's
  `role_names` and people-name resolver); both lanes told.
- The shared dev stack now runs from `../supportx-v2-stack` (detached origin/main), never from a
  lane's working branch (LANES.md), after the stack picked up this branch mid-QA.
- C4: the 12 leftover QA custom fields of 2026-10-27 in Demo Company (11 "QA …" fields and
  "!!!") retired through the API under the QA lock (reversible; nothing deleted).
- `make check`: lint, typecheck, import contracts green; backend 1552 passed after fixing three
  tests (two expected the old 409 params; the files settings test read a developer's
  backend/.env, now `Settings.load(env_file=None)`); frontend all suites green.
- Noted by lane B's WP-039 QA: Urdu is about 380 label keys short (e.g. the portal header);
  Urdu becomes mandatory from Stage 2 (D-006), recorded here as a Stage 2 item.

### 2026-10-28 — CI follow-ups: shard weights from CI, 2 vs 4 workers (lane B, #96)
- Each backend shard now keeps its file timings as an artifact; `make backend-shard-weights`
  rebuilds `tests/shard_weights.json` from a CI run (the old weights, from a laptop, summed to
  ~300 s against 4,309 worker-seconds on CI; shard 3 carried 2,047, shard 2 736).
- Test step per shard before (6 main runs): slowest 370–581 s, spread up to 2.3x (214 vs 491).
  After (3 runs): 488/480/444, 494/486/420, 483/351/406 s: even shards; the slowest shard is
  within the runners' own noise of before (~8 minutes).
- 2 workers per shard (same commit, side by side, twice): 617/590/453 and 546/500/407 s against
  4 workers' 494/486/420 and 483/351/406; one 2-worker shard failed (an order-dependent
  assertion in `test_auth_bff.py`, fixed). **Kept 4 workers.**
- Two strict timings left in `test_filters.py` (50 ms, 10 ms) now use `tooling/timing.py`
  (10x in PRs, the target nightly).

### 2026-10-28 — WP-039 session 3: lock-out, MFA, my account, idle warning (lane B)

- Built on `feat/wp-039-session3`: see the WP-039 checklist; decision D-104 (pending review).
- Also merged today: #82 `subject_for` (lane C's workers decide like the API), #85 and #86 (the
  timing-test rule: 10x the target in PRs, the target in the nightly perf.yml), #87 kept drafts.
- Tests: identity, auth and access DB 97; console 217, ui 81, portal 7, forms 12. e2e under the
  QA lock (handed over by lane A), on a throwaway database: the full suite 55/55, including
  `sign-in-security.spec.ts` (4). Two e2e fixes: in `incidents.spec.ts` a Select option is
  clicked only after its list has finished opening (the MFA reminder exposed a race with the
  virtual list); in `sign-in-security.spec.ts` one card waits for the previous card's save.
- Outside scope, recorded: the record page's in-place edits and the composer keep no draft yet
  (lane A, WP-020d/e); REQ-SEC-030 (active sessions list) and REQ-SEC-027 (step-up) are V1.

### 2026-10-28 — WP-035: reports at 1 million incidents (lane C)
- `report-scale.yml` (nightly 03:41 UTC and manual, rows as input) runs
  `tests/db/test_reports_scale.py`: 1M incidents generated inside PostgreSQL, every built-in
  report plus widget totals, admin and group-scoped technician, strict 2 s target; the
  technician never sees another group's numbers. Timings in the job summary and a 90-day artifact.
- First run (40644943080, 1,000,000 incidents, strict 2 s): all 49 timed queries pass. Slowest
  median 0.73 s (admin, received per month), "open by" reports 0.33-0.37 s, widget totals 0.23 s,
  30-day reports 0.02-0.07 s, drill-down list page 0.008 s; load 118 s.

### 2026-10-28 — WP-036: live dashboards, sessions 1-2 (lane C)
- See WP-036 above. Tests: backend `tests/db/test_dashboards_api.py` (10, incl. RLS of three
  tables, built-ins run for every viewer, homes per role, sharing, copy, If-Match, events);
  console `pages/dashboards/dashboards.test.tsx` (9: rules, home, picker, filter bar, edit mode,
  un-shared, Arabic); e2e `dashboards.spec.ts` (live in two browsers within 2 s, technician home,
  shared dashboard reaches the picker, Arabic, axe). Shared: the report viewer's result view and
  live refresh are reused (`Results`, `useLiveReportRefresh`); `reports.view` now also shows the
  Dashboards entry (admin.test expectation updated).

### 2026-10-28 — WP-035-FIX: the reports QA findings (lane C)
- Every finding of ~/Desktop/qa-wp035/QA-REPORT.md fixed at its cause, each with a test named
  after its ID (`backend/tests/test_qa_wp035.py`, `packages/charts/src/qa-wp035.test.ts`,
  `reports.test.tsx` "QA WP-035", `test_report_exports.py::test_bug_01_...`):
  - BUG-01: one rule names every field (the record's own label, else the report's), 12 report
    field labels added, custom field headers from metadata in the reader's language; a test
    proves no export header reads "Unknown value".
  - BUG-02, BUG-04, BUG-05 (direction, systemic): WeasyPrint draws SVG text unshaped, so PDF
    charts keep shapes and digits in SVG and every name in HTML with an explicit direction;
    the server's `label()` isolates (FSI/PDI) every filled value in Arabic and Urdu (exports,
    report mails, notifications); PDF titles, headers and cells isolated; the console's chart
    states `dir`; `useIsolate`, `useJoinParts` and `useListFormat` (Intl.ListFormat, "أو" for
    "is one of") on the report screens; filter words name groups, sites and people, never ids.
  - BUG-03: RTL mirroring no longer adds a legend (one measure has none); doughnut slices clear
    of the legend. BUG-06: names shortened in the middle (graphemes), whole in tooltips and
    tables. BUG-07: every option shows its whole label (one global rule; lists keep the box's
    width so long lists stay virtual and accessible). BUG-08: "Changed from <built-in>" with
    Reset and Save as my report.
  - ENV-01: `make worker-consumers-pdf` (the dev worker with PDFs), the glib path for
    WeasyPrint on macOS, a dev-setup note.
- WP-029-FIX lessons (D-105) on the report screens: refusals once at the form (FormProblem),
  failures as the error toast with the reference; a refused report run is a notice, a failed
  one the toast; the folder dialog no longer calls every failure a taken name.
- Checks: backend 1600 passed (+ the 4 logging tests separately), ruff, mypy, import contracts;
  frontend eslint, typecheck, prettier, every package's tests (console 273).

### 2026-10-28 — WP-035 QA round (lane C)
- Under the QA lock, Playwright (admin plus a group-scoped technician) and Chrome; report
  ~/Desktop/qa-wp035/QA-REPORT.md. Permissions hold everywhere (reports, drill-down, exports,
  scheduled mails, live totals). 8 bugs listed, not fixed: BUG-01 records exports head the ID and
  subject columns "Unknown value"; BUG-02 Arabic PDF chart labels drawn in reversed letter order;
  BUG-03..08 low (Arabic legend overlap, PDF header date order, Latin comma in Arabic filter
  words, PDF label cut-off, "Stacked ..." cut, built-in title kept after changes). The dev stack
  cannot make PDFs (worker without the `pdf` group; checked with the renderer instead).
  Dashboards are WP-036.

### 2026-10-28 — WP-035: reports e2e in English and Arabic (lane C)
- QA lock from lane B/A; `reports.spec.ts` on the shared stack. Fixed: status tag contrast,
  exports and schedule runs failing visibly when the worker lacks a service, a stalled-export
  sweep. Reported to lane B: the consumers worker had no entitlement service (#91).

### 2026-10-28 — WP-029 merged and QA'd (lane A)

- Merged #71 (WP-021-FIX), #75 (private Keycloak for tests), #74 and #78 (WP-029 parts 1 and 2);
  #81 (layout tests wait for fonts) landed through #78. Migration chain …0029 → 0031 → 0025 → 0028.
- The automation e2e journey found and fixed: unlabelled editor inputs, banner links, faint empty
  tables, field lists sorted by internal name; test data leaking between journeys.
- QA round on main with the lock: shared DB got lane C's skipped 0029/0031 (additive, db-guard
  PASS); backend/.env regenerated (old copy kept as backend/.env.before-wp029-qa); Keycloak
  recreated from the main folder. Report: ~/Desktop/qa-wp029/QA-REPORT.md.

### 2026-10-28 — WP-035: report tests on the real incident source (lane C)
- Lane A's #74 merged: the report, export and schedule DB tests now run through
  `work_items/service/reporting.py`; the test-only provider is gone. 28 tests pass.

### 2026-10-27 — WP-029 part 2: triggers, loop guard, transition settings (lane A)

- Product owner approved part 1 (D-097, ADR-035). Built part 2 on `feat/wp-029b-triggers`:
  trigger consumer, loop guard, transition settings, record Automation tab, admins' loop
  banner, confirmation before a move; defaults D-102; migration 0028.
- Found while testing: within one event a later trigger re-read the record after an earlier
  trigger changed it and fired on a change it never saw; conditions now use the record as the
  event left it.
- Keycloak sign-in tests moved to a private Keycloak per test process (PR #75, with lane B):
  two lanes' runs no longer race on the shared dev Keycloak.

### 2026-10-27 — WP-021-FIX merged path, WP-029 part 1 (lane A)

- WP-021-FIX (PR #71): BUG-01..08 and C1..C5 each with a failing test first; main (#72) merged in.
- WP-029 part 1: automation module, business rules, routing, auto-assignment, screens, history
  "why" lines, in-use refusals, availability switch, live updates; the work item reporting
  provider for lane C. Plan defaults recorded as D-097 (no fallback group by default); ADR-035.
- Split: triggers, loop guard and transition hooks moved to WP-029 part 2 (business rules run
  once per save and cannot trigger each other, so part 1 cannot loop).
### 2026-10-28 — WP-035 session 4: scheduled reports (lane C)
- Built in `../supportx-v2-lanec` (branch `feat/wp-035-schedules`, on #84): schedules, per-recipient
  files and mails on lane B's mail foundation, live schedule list; see WP-035 above.
- Added `identity_access.mail_recipients` in lane B's module (lane B to review).

### 2026-10-28 — WP-035 session 3: exports and report settings (lane C)
- Built in `../supportx-v2-lanec2` (branch `feat/wp-035-export`): background CSV/XLSX/PDF
  exports, worker image with Pango, per-tenant report settings, server-side names; see above.
- Pango installed on the dev Mac with Homebrew (product owner, 2026-10-28) for the PDF tests.
- Lane B added `subject_for` (#82); lane A moved its reporting provider to import time (#74).

### 2026-10-28 — Backend CI in parallel shards, PR #76 (lane B; product owner priority)

- The backend gate is three jobs: `backend checks` (lint, schema checks, mypy, migrate + RLS
  guard), `backend tests 1/3..3/3` (each with its own services, `pytest -n 4 --dist loadgroup`;
  files balanced by `tests/shard_weights.json` through `tooling/pytest_shards.py`), and the
  required `backend` (every job passed, coverage of all shards combined, 90 % enforced).
- Timings: before, 27.7 min (#72) and 38.3 min (#70) in one job; after, checks 1.1 min, shards
  4.1 / 3.5 / 5.8 min, gate done 6.8 min after the run starts.
- Found on the way: parallel database bootstraps failed with "tuple concurrently updated"
  (cluster-wide roles); `db_bootstrap` holds an advisory lock. A CPU-bound timing test measured
  wall-clock time under parallel load; it measures its own CPU time now.
- The 100k-row audit volume test runs nightly only (audit-scale.yml, 10M). New test-only
  dependencies: pytest-xdist, execnet (MIT, D-012). Lanes A and C told to merge main.

### 2026-10-27 — WP-039 session 2: mail, invitations, reset, password policy (lane B)

- Built on `feat/wp-039-session2` (stacked on PR #70): see the WP-039 checklist. Decisions
  D-099 (Keycloak's e-mails, done properly) and D-103 (session 2 defaults; reviewed 2026-10-28).
- Proved on a throwaway Keycloak 26.8.1 (`wp039-kc`): the breached list loads (46,941) and
  refuses a listed password that meets every other rule; a short one gets the length message;
  `supportx-realm` sets the policy and `supportx-identity` gets 403; Urdu users see the rules'
  messages in Urdu, right to left; invitation and reset e-mails branded, single use, expiring.
- Tests: backend unit and DB (identity API 29, mail 17, Keycloak set-up 8, theme 12, labels);
  console Vitest (admin 87), portal (reset page). E2E on the shared stack under the QA lock
  (Keycloak recreated, a throwaway database agreed with lane A): `invitations.spec.ts` passes,
  the full suite 51/51. PR #80.
- CI: PR #70's backend job was cancelled at the 30-minute limit (the suite reached 31% of
  tests in 28 minutes; lane A's #71 too); the limit is now 45 (agreed with lane A).
- Found outside scope: the realm's brute-force settings do not match Appendix A (15 minutes,
  doubling) and Keycloak says "invalid username or password" while locked: session 3.

### 2026-10-27 — WP-035 session 2: reports home and viewer (lane C)
- Built in `../supportx-v2-lanec2` (branch `feat/wp-035-viewer`, on top of #73): reports home,
  report viewer, shared filter builder, chart kit, live library; see WP-035 above.
- Not yet: e2e and axe (QA lock), Sunday week start and tenant query limits (session 3).

### 2026-10-27 — WP-035 session 1: reporting engine (lane C)
- Lane C started (coordination rules, three lanes). Plan approved as D-100; ADR-033 (reporting
  engine) and ADR-034 (server-side labels) accepted.
- PR #72 ships the reporting port alone so lane A can write the incident provider in WP-029.
- Session 1 built the engine, the read-only reporting role, migration 0027, 23 built-in incident
  reports, saved reports, folders, favourites and server-side labels; see WP-035 above.
- DB tests ran on a lane C PostgreSQL container (not the shared dev stack), Valkey shared with
  per-test key prefixes.
- Lane B told: WP-039 mail templates and WP-023 notifications use `app.shared.labels.label()`;
  scheduled reports need attachments, per-message language and `mail_configured()`.
### 2026-10-27 — WP-039 session 1: service account, sessions, single sign-on (lane B)

- Built in `../supportx-v2-wp039` (branch `feat/wp-039-identity`), migration 0024 after lane
  A's 0023, D-094 and ADR-036 (numbers agreed with lane A).
- Proved on a throwaway Keycloak 26.8.1 before building: the least-privileged roles; that
  organization domain routing moved onto the organization's domains in 26.8 (the old
  `kc.org.*` provider settings are dropped); that Keycloak refuses a second person in a browser
  signed in as someone else (`different_user_authenticated`, after creating their account), so the
  test runs in a private window; that a SAML signature failure leaves no login event; that
  Keycloak answers `unauthorized_client` for both a right and a wrong secret, telling them apart
  only in its description; that undeclared user attributes are dropped (user profile).
- Checked end to end against that Keycloak with a second realm as the customer's provider, both
  OIDC and SAML, through the screens: wrong secret refused at the field, draft, test in a private
  window, switch on, a person of the domain sent straight to the provider and created in Demo
  Company with their department; a wrong SAML certificate fails and the set-up stays off.
- Pre-existing, not changed: the audit-integrity banner's link fails axe `link-in-text-block`
  when that banner shows (WP-018 banner); noted here for a fix.

### 2026-10-27 — WP-017-FIX and ADR-031 (lane B)

- The product owner approved WP-017 and accepted ADR-031 (D-093): a separate domain worker
  provisions certificates; never from an air-gapped install.
- Fixed BUG-01..09 in `../supportx-v2-wp017fix` (branch `fix/wp-017-qa`), each with a failing
  test first. Checked in a real browser too: the fix branch's console on a second dev server
  (port 5183) against the shared API, axe clean in light, dark and high contrast; BUG-08 on a
  throwaway Keycloak 26.8.1 (name shown, markup escaped, axe clean in four variants).
- Housekeeping with lane A's OK: the 8 QA uploads purged (files service purge, audited
  `file.purged`), the shared Keycloak container recreated (`--no-deps keycloak`). Numbers agreed:
  D-093/D-094, ADR-036 and migration 0024 for lane B; D-095 for lane A.

### 2026-10-27 — WP-026-FIX merged; WP-021 people and organisation (lane A)

- PR #67 (WP-026-FIX, D-091) merged under standing approval with every check green.
- Built WP-021 on `feat/wp-021-people-org` (plan approved: D-092, ADR-032). Coordinated numbers
  with lane B: D-089/D-090 and ADR-031 and migration 0022 are lane B's (WP-039, WP-017); this WP
  takes D-092, ADR-032 and migration 0023.
- Sign-in behaviour changed on purpose (D-092): two auth tests that expected Keycloak profile
  changes to reach SupportX now prove the opposite; new tests cover linking by email and
  refused contacts. The entitlement test for promotion now promotes in SupportX.
- Raw-SQL test fixtures and the dev seed set `first_name` and the IT desk.
- The first-run question is a banner, not a blocking dialog, so work (and the e2e suite) goes
  on until an admin answers.

### 2026-10-27 — WP-017 tenant branding and domains (lane B)

- Planned and built in `../supportx-v2-wp017` (branch `feat/wp-017-branding`). Migration 0022
  after lane A's 0021; decisions D-089 (the product owner's WP-039 answers) and D-090 (WP-017
  defaults); ADR-031 (proposed). The dev addresses' callbacks are registered by the e2e setup
  (realm files never carry UI origins). Lane A told: the mail foundation (D-089 D3), numbering (lane A
  takes D-091, D-092, migration 0023), the SSO attribute lookup shape for WP-021.
- A throwaway Keycloak 26.8.1 confirmed `org` in login templates, the `organization:<alias>`
  scope (only that organization in the token; none for non-members; not combinable with
  `organization:*`) and the theme property's environment substitution.
- The colour rules moved from `tooling/brand_assets.py` into the organization domain, so the
  default brand, tenants and the sign-in stylesheet share one implementation.

### 2026-10-27 — WP-026: custom fields (lane A)

- Built WP-026 (D-087 defaults; the product owner's answers are D-088): metadata module,
  values on incidents, filters, search text, history, templates, admin screen, form, record,
  list filter, index worker. Merged main with lane B's WP-027; migration 0021 follows 0020 and
  rebuilds the search vector with the custom field text.
- The 2 skipped backend tests are the opt-in volume and load checks (audit scale, file
  uploads); nothing to fix.
- Tests: 14 backend database tests for custom fields, 1 in search, 46 metadata domain tests, 9
  index-failure unit tests, 9 Vitest tests, one two-user Playwright journey (green in CI).
- Local Vitest timed out on first renders while containers outside SupportX loaded the Docker
  VM (load average 47); the same tests pass alone and in CI.

### 2026-10-26 — WP-027 search and record pickers (lane B)

- Planned and built in one session in `../supportx-v2-wp027`. The product owner confirmed
  PostgreSQL full-text search for MVP (D-085) and asked for typo tolerance (pg_trgm) and a port
  ready for pgvector (ADR-029).
- Coordinated with lane A (WP-026). This WP keeps migration 0020 and ADR-029; WP-026 takes 0021,
  D-086 and ADR-030, and feeds custom-field text into the same vector.
- Found and fixed while building: an INSERT returned the generated tsvector with every new
  incident. The search columns are now `unmapped_column`s.
- Shared `useDebounced` (`apps/console/src/useDebounced.ts`) replaces two copies.
### 2026-10-26 — WP-022 review follow-ups (lane B)

- D-084 recorded: the admin "rotate data key" action is V1; new enum values are additive, and
  API clients must tolerate unknown enum values (`docs/architecture/api-conventions.md` §8).
- Urdu labels for every licence limit (`limit.*`), with a test that every limit has Arabic and
  Urdu.
- Flaky console announcements test, cause found: `pnpm test` ran four packages at once, each
  Vitest with a worker per CPU core, so about four jsdom workers per core. A file's first full
  render (about 1.5 s of CPU, measured with a CPU profile: Ant Design styles parsed by jsdom
  and React's first render) then sometimes ran past the 5 s test limit, about one run in five.
  Fix: `pnpm test` runs the packages one after another (`--workspace-concurrency=1`): 6 of 6 runs
  green, and faster (about 35 s against 40–70 s). Preloading the lazy routes was tried and did
  not help (the time was not module loading).
- D-085 recorded: PostgreSQL full-text search with pg_trgm for MVP, behind a search port
  (ADR-029 comes with WP-027).

### 2026-10-26 — WP-020c: incident settings screens and templates

- **Built:** see the WP-020c entry. Decision D-083 (defaults per D-074; renumbered from D-082 when merging main, lane B took
  it). Migration 0019 on top of lane B's 0018 (renumbered when merging main) (applied to the dev database). PR #56.
- **No new dependencies.** Shared changes: `users.form_density` (identity_access, BFF `/auth/me`),
  `display_ids.last_number` / `set_next_number`, the console frame listens to
  `work_items.settings_changed`, `@supportx/api-client` `incidentSettings.ts`, e2e cleanup of
  "E2E" templates and pick-list values.
- **Tests:** backend 1015 passed, 1 skipped (coverage 94.3 %); Vitest console 109 (13 new);
  Playwright `incident-settings.spec.ts` 3/3. Full e2e run: 38/40 locally; `qa-fixes` BUG-04
  passed on two reruns (flaky under load); `branding` login logo fails on the dev Keycloak (realm
  theme state, not this branch).
- **Slow tests (over 5 s, measured while the e2e suite ran in parallel):** event relay throughput
  10k (26 s), audit jobs seal/anchor/verify (24 s), 100k list p95 (19 s), commit→consumer latency
  (14 s), filtered list 100k (12 s), brand assets generation (9 s), audit retention archive
  (7.5 s), OpenAPI export (6.7 s), two parallel relays (6.4 s), and the incidents API tests whose
  *setup* (two orgs with roles, sites and groups) takes 6-22 s under load. Timeouts unchanged.

### 2026-10-26 — WP-022 files and safe attachments (lane B, sessions 1–3)

- Built WP-022 in `../supportx-v2-wp022` (branch `feat/wp-022-files`) as planned and approved
  (D-082, ADR-028); see the WP entry for what each session delivered.
- Decision renumbered from D-081 to D-082 when merging main (lane A recorded D-081 meanwhile).
  Migration 0018 follows lane A's 0017: one head.
- Found: the console announcements test is flaky under full parallel load (passes alone,
  pre-existing, not touched here). Real clamd flags EICAR only at the start of a file; the fake
  scanner in tests now matches that.
- Follow-ups: an administrators' per-tenant data-key rotate action (optional); Urdu
  `limit.storage_gb` (limits have en/ar only, like the other limit labels).

### 2026-10-26 — WP-020b-FIX: the WP-020b QA findings

- **Fixed:** BUG-01..10 and C1..C7 (see the WP-020b-FIX entry), plus the D-081 changes. Shared
  changes: `@supportx/realtime` acquire/release, `limited` status, channel and connection retries,
  `@supportx/realtime/testing` (scripted client for app tests); `@supportx/ui` `ToneTag`, `tones.ts`,
  `richtext/direction.ts`, the `connectivity.limited` banner.
- **Not changed:** no new dependencies; no migration; the remembered tab is per browser (D-081).
- **Data:** Tariq (tech@demo.test) removed from QA-Desk A and QA-Site through the admin API (as
  before the QA run); INC-68..71 moved to the trash.

### 2026-10-26 — WP-020b: conversation, notes, followers, richer editor

- **Built:** see the WP-020b entry. Decisions D-079 (defaults) and D-080 (Tiptap mention and
  suggestion, MIT). ADR-026 amended (followers and shared reach). Migration 0016 on top of 0015.
- **New dependencies:** `@tiptap/extension-mention`, `@tiptap/suggestion` (MIT, 3.31.4; D-080).
- **Shared changes:** `ResourceType.shared_scope`/`shared_actions` in the policy layer;
  `EmptyText` in `@supportx/ui`; sanitiser allow-list (span/mark with palette codes, alignment and
  indent codes, mentions); e2e teardown also removes the suite's conversation rows.
- **Tests:** backend 972 passed, 1 skipped, 94.57 %; new `test_conversation_api.py` (18, incl.
  RLS for the three tables) and domain tests; console 83, ui 45 (editor and Word paste); e2e
  incident journeys 3/3 locally (hand-over now keeps following, then unfollow removes access).
- **Chrome check before the PR** found and fixed four UI bugs: the text-style picker stretched the
  toolbar onto three lines in forms; mention list unreadable in dark mode (mounted outside the
  theme); the record page left a quarter of the screen empty (fixed 1200 px cap, also on the create
  form); the disabled Reply button's arrow looked active; the empty editor's placeholder sat on the
  left in Arabic. Known, not fixed: the first pasted paragraph takes the alignment of the empty line
  it lands in (ProseMirror merges them).
- **Dev environment:** dev database migrated 0013 → 0016 (forward only); fan-out, consumer workers
  and the console dev server restarted to load the new code and dependency.
### 2026-10-26 — Branding (lane B) and WP-018 wrap-up

- **Branding** (D-078, branch `feat/branding`): see the BRAND entry above. Colours sampled from the
  logo, #6666ec → #951ab6; #6666ec alone fails AA with white (4.49:1), so the primary is the
  gradient midpoint #7e40d1 (5.93:1) and the gradient starts at #6060de (4.97:1). Hover and press
  darken (7.16:1, 8.12:1) instead of Ant Design's lighter hover. Keycloak login page checked with
  axe in light, dark, high contrast and Arabic in a throwaway Keycloak 26.8.1 container (removed
  afterwards).
- **D-077** recorded (field history retention).
- **Dev environment:** the Compose dev stack and the k3d cluster, stopped from outside the session
  on 2026-10-25, were started again (`make dev-up`, `k3d cluster start`): `make dev-check` 19
  passed, 0 failed; all k3d pods ready. The leftover throwaway database from the interrupted
  local 10M run (`supportx_test_21eb95e23b46`, 7.7 GB) was dropped, with the product owner's OK;
  nothing else was touched.

### 2026-10-26 — WP-018 session 3 (retention, restore, volume, demo)

- **Built:** see the WP-018 entry. No new dependencies.
- **Merged main:** lane A's migration 0013 came first, so the audit migration is now 0014, and
  lane A's D-075 kept its number, so the WP-018 decisions are now **D-076** (every reference in
  the WP-018 files was renamed). Conflicts in `DECISIONS.md` and `test_auth_bff.py` were
  resolved by keeping both sides.
- **Shared changes:** `useDateTime().formatMonth` (a UTC month); CI sets
  `SUPPORTX_AUDIT_SCALE_ROWS=100000`; new pytest marker `scale`.
- **Tests:** backend 949 passed, 1 skipped (the opt-in volume test), 94.53 % coverage; 7 new
  retention tests on PostgreSQL and SeaweedFS; console 75, ui 38, labels 25. Volume test at 100k
  (in CI on every run): seal, full verification, retention (24 archives, partitions dropped),
  search 13-47 ms, tamper detected at the changed position. The e2e journey `audit.spec.ts` passes
  in CI after three accessibility fixes it found (tag and link contrast, an inline link without
  underline, the empty-table text). Verification is 18x faster after bounding entry lookups by
  time (about 1,000 to about 18,000 entries/s at 100k).
- **Update 2026-10-26:** the 10M workflow ran to the end. Sealing finished but at 875/s (below
  the 1,000/s floor); see the WP-018 follow-ups. The leftover throwaway database was dropped.
- **Not finished here:** the local 10M run stopped after 66 minutes because the whole dev stack
  was shut down by a normal stop request (not by this session, not out of memory). The first 10M
  result comes from the `audit-scale` workflow on GitHub, which can only be started by hand once
  it is on main. The stopped dev PostgreSQL still holds that run's throwaway
  `supportx_test_*` database; drop it when the stack is up again.
- **Seen, not changed (lane A screens):** the incidents and announcements tables show their
  empty-table text in Ant Design's faint placeholder colour, the same contrast problem axe found
  on the Archives tab.

### 2026-10-24 — WP-018 session 2 (storage, exports, screens)

- **Built:** see the WP-018 entry. New dependencies: `aioboto3` (approved D-054/D-076; pulls
  aiobotocore, Apache-2.0) and the dev type stubs `types-aioboto3[s3]` (MIT, D-012 helper).
- **Shared changes:** `useDateTime().formatExact` (to the second), `audit.view` opens the Admin
  area, admins' fake permissions include the audit permissions, `/audit/status` in the console
  test API.
- **Tests:** backend 937 passed (94.68 %), including 6 export tests on SeaweedFS and MinIO;
  console 55 (6 new audit screen tests); chart lint for all five profiles.

### 2026-10-24 — WP-018 session 1 (backend core of the audit log)

- **Built:** see the WP-018 entry above. Decisions D-076 (product owner answers to the plan),
  ADR-027. The chain is written by the migrator-owned definer function `audit_seal()` instead of
  a separate `supportx_audit` login role (stronger, one less credential).
- **Core changes:** `app/core/errors.py` error observers (`register_error_observer`),
  `ModuleSpec.schedules` + `app/shared/schedules.py`, `recorded_change_ids()` in field history,
  `SUPPORTX_AUDIT_*` and `SUPPORTX_WORKER_SCHEDULES_ENABLED` settings, Auditor system role
  (`identity_access`), `migrations/env.py` skips audit partitions.
- **Not audited yet, with reason:** edits of closed incidents (closed records are read-only, 409
  `record_closed`) and due-date overrides (come with SLA, WP-025); their actions are catalogued.
- **Tests:** backend 876 → all green plus 25 domain, 20 API, 5 job, 4 route-table and 1 BFF audit
  tests. Lane A has not merged a migration since 0012, so ours stays 0013 for now.

### 2026-10-24 — MVP build plan v0.2: decisions D-070 to D-074, two lanes (docs only)

- Recorded D-070 (on-prem single node for the internal go-live and the design partner;
  WP-014c on the MVP path, WP-014d after MVP), D-071 (AD/LDAP direct on-prem, Entra ID only on
  SaaS at MVP), D-072 (local model rules; WP-037 proposes), D-073 (first-run visibility
  question, "group" preselected), D-074 (other defaults decided in each WP plan).
- `mvp-build-plan.md` v0.2: WP-020 marked done; 68 sessions to MVP with one lane; two lanes
  (lane A the WP-020 chain, lane B audit, files, search, licence, deployment, AI, branding,
  identity, API, knowledge, reports, admin) take about 34 session-days. Critical path 14
  sessions (WP-020c → 026 → 029 → 030 → 031 → 032).
- No code changed.

### 2026-10-24 — Parity: MVP build plan (docs only)

- Added `docs/specs/parity/mvp-build-plan.md`: all 397 MVP requirements mapped to 31 work
  packages (WP-020 to WP-020f, WP-021 to WP-043, plus WP-017 and WP-018), 63 sessions, plus
  WP-013 and WP-014b (4 sessions): 67 sessions to MVP, up to 4 more depending on where the
  design partner runs. Critical path 15 sessions (WP-020 → 020c → 026 → 029 → 030 → 031 →
  032). 14 decisions flagged for the product owner.
- No code changed.

### 2026-10-24 — Parity: product owner answers D-057 to D-068 (docs only)

- Recorded D-057 (MVP AI slice: summary, reply drafts, similar incidents on the local model
  through a minimal gateway), D-058 (audit log MVP), D-059 (single sign-on Essentials MVP),
  D-060 (MFA defaults), D-061 (desks), D-062 (directory sync MVP, Teams V1), D-063 (MSP LATER),
  D-064 (AI access and fallback), D-065 (mobile app V1), D-066 (REQ-INC-021 MVP, REQ-INC-117
  V1), D-067 (vendors and products with assets in Stage 2), D-068 (escalating technician keeps
  following; amends D-053).
- Applied them to parity files 01–12 (priorities, sources, answered open questions), notes for
  D-055 (file 03) and D-056 (narrows D-041 at MVP). architecture.md §11.2 Redis → Valkey; §17
  updated for D-067.
- MVP now holds 397 requirements across the twelve files. No code changed.

### 2026-10-24 — Parity: Area 15 saved and applied (docs only)

- Saved `docs/specs/reference/sdp-area-15-roles-workflow.md` (PR #38) with the product owner's
  sign-in, invitation and MFA observations.
- Parity updates from Area 15: REQ-WI-027 (people can be told apart in pickers), REQ-INC-151
  (the escalating technician can keep following; changes the D-053 default), REQ-INC-152
  (default views never hide records silently), REQ-SR-063 (one approver model for requests and
  changes); auto-assignment picks the group first (REQ-INC-053, REQ-ASG-002); approvals never
  depend on email (REQ-SR-025); the change manager role can run a change end to end and every
  role is viewable (REQ-CHG-038, REQ-ADM-017); site admins create requesters (REQ-ADM-020).
- No code changed.
### 2026-10-24 — WP-020-FIX: the WP-020 QA findings

- **Scope:** every finding of the exploratory QA report (Desktop/qa-wp020/QA-REPORT.md):
  BUG-01..18, C1..C7 and the product owner's review of the create form. Each has a test named
  after its ID that failed first: backend `tests/db/test_incidents_api.py` (BUG-03, BUG-05,
  form defaults), `tests/db/test_auth_bff.py` (BUG-04), `tests/test_richtext.py` (C4); Vitest
  `apps/console/src/pages/incidents/qa-fixes.test.tsx`, `packages/ui/src/qa-fixes.test.tsx`,
  `packages/ui/src/units.test.ts` (C2), `packages/realtime/src/realtime.test.tsx` (BUG-13);
  Playwright `e2e/tests/qa-fixes.spec.ts` (BUG-04, BUG-07, BUG-13, BUG-16, C1, C2, C3, C5).
- **Server:** history pages name people in changed values; `users.ui_locale` (BUG-04);
  start work takes an unassigned incident first, disabled with `cannot_take` when the user
  may not take it; refused links keep their text; incident settings `default_impact` /
  `default_urgency`. Migration 0013 (expand only). D-075.
- **Screens:** Assign dialog built on open, re-reads the record, follows live changes for
  untouched fields; one request per write (single flight); clear Cancel wording; errors under
  their field; text in its own direction (`bdi`, `dir=auto`); subject 500 with a counter;
  inline edit focus, Enter, Escape; "Keep my changes" saves on top; header collapses below md;
  no body margin and a stable scrollbar gutter; fonts per language (Arabic Naskh, Urdu Nastaliq
  with taller lines); option names are labels (C7 check); required marks; tenant defaults in the
  form; scroll to top on navigation; presence initials and disconnect on page hide.
- **Tests:** backend 881 passed; frontend unit tests all green (console 68, ui 38, realtime 13,
  others); Playwright full suite 33/33 (incl. the QA spec, 6). `make check` green.
- **Not reproduced automatically:** the BUG-13 ghost does not appear in headless Chromium even
  without the fix (its WebSocket closes cleanly on reload); the unit tests prove the fix
  (explicit disconnect on page hide; initials from the name).
- **Dev data:** dev database migrated 0012 → 0013 (adds columns; existing incident settings got
  the defaults team / medium). QA data as listed under Open.

### 2026-10-24 — WP-020 session 2: incident screens, editor, two fixes

- **Screens:** `apps/console/src/pages/incidents` (IncidentsPage, IncidentPage, NewIncidentPage,
  StatusActions, assign/take/hand-over dialogs, IncidentHistory, pickers, tags, labels helpers);
  routes `/incidents`, `/incidents/new`, `/incidents/:id`; nav item Incidents.
- **Shared UI:** `packages/ui` RichTextField (Tiptap 3.31.4, lazy chunk), RichTextView,
  `useDateTime`; high-contrast `colorError` darkened for danger buttons (axe). Tags use a coloured
  dot plus normal text (coloured fills failed contrast).
- **Backend:** people and assignees carry the email (`user_contacts`, Area 15 lesson);
  e2e fixtures also remove the suite's incidents and groups.
- **Fixes:** Appearance popover keeps its state across layout/language re-renders (store in
  AppHeader; Vitest + e2e without retry). `helm test` excludes the upstream Valkey auth pod; our
  smoke pod asserts NOAUTH without a password and PONG with it (verified on k3d, revision 7).
- **Labels:** about 105 new keys in en/ar/ur; `requests.*` and `nav.requests` now say "service
  requests".
- **Tests:** backend 876 passed (94.8 %); frontend unit tests all green (incl. 10 incident tests,
  3 popover tests); Playwright 27/27 on the Compose stack; chart lint OK; `make check` green.
- **Dev data:** dev database migrated 0010 → 0012 (expand-only; no existing row changed). The demo
  tenant's incident configuration was seeded on first use (Appendix A defaults). The e2e suite's
  incidents and groups were removed by its teardown (0 left). Dev workers `worker-fanout` and
  `worker-consumers` were restarted so they load the new module. k3d release upgraded to revision
  7 (test template only, same images).
- **Deviations:** following a handed-over incident (D-068) moves to WP-020b with followers
  (D-069); the language choice is a per-browser setting, so the Arabic e2e checks navigate inside
  the app.

### 2026-10-24 — WP-020 session 1 (backend): work item engine + incidents API

- **Stopped at:** backend complete and committed on `feat/wp-020-work-items-incidents` (pushed, no
  PR yet). Next: session 2 (frontend + the two fixes), then the PR. Nothing in the frontend uses the
  new API yet; no screen changed.
- **Built:** `backend/app/modules/work_items` (domain: lifecycle, classification, types; infra:
  tables; service: catalogue seeding, access/D-052, work items, settings, realtime; api: router
  factory), `app/shared/richtext.py` (nh3), shared changes (history sources/kinds/automation_ref and
  time-ordered paging; type-keyed display counters; `ResourceType.group_scope_extra`;
  `LiveList(unassigned_by_site=…)`; `list_query(extra_parameters=…)`; `ModuleSpec.router_features`),
  migrations 0011 (history, counters) and 0012 (work items), import-linter layers contract.
- **Tests:** 876 passed, coverage 94.8 %; `tests/db/test_incidents_api.py` (30 tests incl. D-052
  three rules + 404, D-053, realtime audiences, 100k-row perf), `work_items/tests/test_domain.py`
  (24), `tests/test_richtext.py` (4). ruff, mypy strict, import-linter, OpenAPI diff (no breaking
  change), event schema check green. Frontend lint/typecheck/unit tests green (no UI changes).
- **Decisions:** D-051..D-056 recorded; ADR-026; CLAUDE.md §3 (nh3, Tiptap, aioboto3 later).
- **Deviations from the plan:** no separate `work_item_lifecycles` table (one life cycle per type
  until the designer); the record channel is `t:{tenant}:wi:{id}` as planned; the reserved
  `requests.*` permissions stay (relabelled in session 2) because many policy tests use them;
  WI-020 AC3 (purge after retention) deferred until the audit log (WP-018).
- **Decision IDs:** main already held D-039..D-050 (parity answers, PR #34), so this session's
  rows were renumbered D-051..D-056 and main was merged in; overlapping points cite main's D-040
  (Tiptap timing), D-041 (editable defaults) and D-045 (per-type counters).
- **Dev data:** none touched. Migrations ran only on throwaway `supportx_test_*` databases; the dev
  database is still at 0010 (run `make db-migrate` to apply 0011–0012; expand-only).

### 2026-10-24 — Parity spec phase 2, batch 4 (docs only)

- Added `10-ai.md` (108: 0 MVP / 79 V1 / 29 LATER), `11-admin-users-security-audit.md`
  (179: 62 / 101 / 16; includes the login, invitation and MFA findings: tenant-branded sign-in
  and invitations, no inviter address exposed, MFA through Keycloak with standard authenticator
  apps, no third-party account) and `12-integrations-esm.md` (141: 17 / 47 / 77).
- Cross-file references added between finished files (AI, knowledge, assets, mail ownership).
- Parity phase 2 complete: 12 files, 1,580 requirements. Each file ends with open questions
  for the product owner. Decision IDs: WP-020 renumbered its rows to D-051..D-056 after this
  phase's D-039..D-050 (next free D-057).
- No code changed.

### 2026-10-24 — Parity spec phase 2, batch 3 (docs only)

- Added `07-assets-cmdb-software-purchase-contracts.md` (183: 0 MVP / 145 V1 / 38 LATER),
  `08-knowledge.md` (93: 38 / 50 / 5) and `09-reports-dashboards.md` (116: 40 / 61 / 15).
- File 05 now cites the CMDB downtime and impact requirements (REQ-CMDB-020, REQ-CMDB-010).
- Spec gap found: architecture.md §6.1 puts products and vendors in `procurement` (Stage 3),
  but assets need them at Stage 2 (file 07 open question 2). §11.2 still says "Redis"
  (should be Valkey, D-004).
- No code changed. Next: batch 4 (10 AI, 11 admin and security, 12 integrations and ESM).

### 2026-10-24 — Parity spec phase 2, batch 2 (docs only)

- Added `04-problems.md` (81: 0 MVP / 74 V1 / 7 LATER), `05-changes.md` (118: 0 / 100 / 18)
  and `06-releases-projects.md` (112: 0 / 54 / 58). All Professional; Stage 2 and 3 modules
  have no MVP items.
- File 01: new REQ-WI-026 (stages that group statuses, one engine model for changes and
  releases). Change and release approvals are built on the shared approval engine in file 02.
- No code changed. Next: batch 3 (07 assets/CMDB, 08 knowledge, 09 reports).

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
  it); D-025 records it and that D-030..D-051 are released. WP-008 session-log entry moved to its
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
