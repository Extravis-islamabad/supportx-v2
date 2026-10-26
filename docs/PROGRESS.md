# SupportX v2 — Progress

## Current status

- **Stage:** 0 — Foundation (architecture.md §17). In progress: 14 of 16 work packages done
  (WP-014 = part 1 of 4; 014b-d are planned below).
- **Last completed:** WP-020b-FIX (all WP-020b QA findings: BUG-01..10, C1..C7, D-081), 2026-10-26.
  Before it: WP-020b (conversation, notes, followers, richer editor).
- **Next work package:** WP-020c (incident settings screens and templates), **when the product
  owner says so**; then the sequence below (WP-020d..020f, WP-021..028). Plan: ~/Desktop/wp-020-plan.md.
- **Other open packages:** WP-015 (clickable prototype), WP-013 (licence core), WP-014b.
- **Working mode:** two lanes (MVP build plan): lane A = the WP-020 chain (main folder), lane B =
  WP-018 audit log (done 2026-10-26), then branding (done 2026-10-26, branch `feat/branding`,
  D-078). Lane B's next WP follows the MVP build plan.
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

### Planned after WP-020 (sequence from the WP-020 plan)
WP-020b conversation, notes and followers · WP-020c incident settings screens and templates · WP-020d views
and bulk · WP-020e tasks, worklogs (time) and links · WP-020f resolution and closure · WP-021 people
and departments · WP-022 files (aioboto3, D-054) · WP-023 notifications · WP-024 email channel ·
WP-025 SLA v1 with Temporal (D-055; needs parity file 03) · WP-026 custom fields · WP-027 search ·
WP-028 portal incidents (needs parity file 02). Open item from D-052: the first-run setup must offer
"technicians see all incidents" vs the group default.

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
    installation key either way). Recorded as a follow-up.

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
