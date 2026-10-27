# CLAUDE.md — SupportX v2 engineering rulebook

This file is the standing rulebook for every Claude Code session on this repo. Read it fully
before doing anything. When in doubt, the specs win over memory, and the user (product owner)
wins over the specs.

## 1. Sources of truth

| Document | Role |
|---|---|
| `docs/specs/architecture.md` (v0.2) | **Source of truth.** Wins on any conflict. |
| `docs/specs/product-plan.md` (v0.1) | Product context, pillars, packaging. Subordinate to architecture.md. |
| `docs/DECISIONS.md` | Product owner decision log (D-001...). Overrides the specs where they differ. |
| `docs/adr/` | Formal decisions (ADR-001..017 from architecture.md §19). New decisions get a new ADR. |
| `docs/PROGRESS.md` | Work-package plan, current status and session log. |

architecture.md wins over product-plan.md on every conflict, including roadmap timing:
architecture.md §17 replaces product-plan.md §10 (D-002).

Monitoring boundary (ADR-017, D-001): product-plan.md describes alert correlation, de-duplication
and an event-ingestion pipeline inside SupportX. **That is wrong for this build.** SupportX does no
monitoring, no device polling and no alert correlation. It has the MonetX connector plus a generic
alert webhook (architecture.md §2 intro, §2.14, §6.8). Through `monitoring_integrations` only, it
may **read** health, problems and topology from the MonetX API (read-only) to power pre/post change
health checks, live health on CMDB impact maps and wallboards with monitoring status.

## 2. Product summary

SupportX v2 is a greenfield enterprise ITSM/ESM platform built by Extravis. The functional
baseline is **full ManageEngine ServiceDesk Plus parity** (Enterprise edition, Cloud and On-Prem
features combined — architecture.md §2), delivered identically on SaaS, private cloud, on-prem and
air-gapped from one codebase. It then goes beyond SDP on real-time UX, deployment parity, sovereign
local AI, MonetX integration and AI agents. Core design levers: a modular monolith (§6.1), one
unified work-item engine for all ticket-like records (§6.2), metadata-driven customisation (§6.6),
event-driven everything via a transactional outbox (§6.5), and fingerprint-bound licensing (§13).

**Parity rule (architecture.md §2):** parity means the same *capabilities and outcomes*, never a
copy. Never reproduce ManageEngine screens, layouts, wording, help text, icons or artwork. All UI is
original, designed on Ant Design 5. Where SDP relies on another ManageEngine product, SupportX
delivers natively or via Extravis products (AgentX, PatchX, MonetX).

v2 is a first build: migration from SupportX v1 is out of scope (D-005). The ServiceDesk Plus
migration tool (architecture.md §18) remains in scope.

## 3. Tech stack (architecture.md §5) — closed list

**Backend:** Python 3.12+, FastAPI + Pydantic v2, SQLAlchemy 2.0 (async) + Alembic,
PostgreSQL 16 (RLS, JSONB, pgvector), NATS JetStream, Temporal (Python SDK), Centrifugo,
Keycloak, **Valkey** (replaces Redis everywhere — D-004), OpenSearch, S3-compatible
object storage (S3 API only; MinIO for local dev only — D-016), ClickHouse.
Package management: **uv**.

**Frontend:** React 18 + TypeScript (strict) + Vite, Ant Design 5, TanStack Query, Zustand,
React Hook Form + Zod, Apache ECharts, React Flow (xyflow), Monaco. Package management: **pnpm**
workspace.

**Platform:** Kubernetes + Helm (k3s for single-node on-prem; **k3d** for local clusters — D-003);
Docker Compose for local dev only; OpenTelemetry, Prometheus, Grafana, Loki, Tempo.

**Approved additions (D-004):** Rust toolchain + PyO3/maturin (licence core, §13.7), asyncpg,
pydantic-settings, Nuitka, OpenFeature SDK, pgvector, PgBouncer, Jinja2 (sandboxed environment
only), pre-commit, ClamAV, pgBackRest (superseded by CloudNativePG backups, D-038), React Native (mobile, later), Go (only if ADR-015 chooses a
new agent).

**Approved additions (D-012..D-014):** test/build helpers httpx, @testing-library/react,
@testing-library/dom, jsdom, @vitejs/plugin-react, @types/react, @types/react-dom, @eslint/js,
typescript-eslint, eslint-plugin-react-hooks, eslint-plugin-react-refresh, globals (D-012);
i18next + react-i18next for `packages/labels`, adopted in WP-010 (D-013); TypeScript pinned to the
latest version typescript-eslint supports, currently 5.9.x (D-014).

**Approved additions (D-019):** backend runtime libraries uvicorn (ASGI server), structlog
(structured logging), uuid-utils (UUIDv7 IDs), opentelemetry-api, opentelemetry-sdk and
opentelemetry-instrumentation-fastapi (no exporter configured yet).

**Approved additions (D-020):** official clients valkey-py (`valkey`) and nats-py (`nats-py`).

**Approved additions (D-021, D-022):** `cryptography` (PyCA; AES-256-GCM session encryption, later
Ed25519 licence signatures and field-level encryption); `openapi-typescript` (dev-only; generates
`packages/api-client/src/schema.ts` from the OpenAPI export).

**Approved additions (D-023):** `opentelemetry-exporter-prometheus` and `prometheus_client`
(Apache-2.0) for the Prometheus scrape endpoint of the API and workers (WP-014).

**Approved additions (D-026):** `react-router` (7.x while on React 18), `openapi-fetch` (typed API
client), `@axe-core/playwright` (test-only accessibility checks).

**Approved additions (D-028):** `@ant-design/icons` (5.x), `@hookform/resolvers`.

**Approved additions (D-030):** `centrifuge` (centrifuge-js, Centrifugo's official client).

**Approved additions (D-037, D-038 — deployment, WP-014):** CloudNativePG, cert-manager, the
official NATS and Valkey charts (+ prometheus-nats-exporter, redis_exporter), Gateway API CRDs,
Traefik (bundled with k3s), kubeconform (CI), External Secrets Operator (SaaS), Fluent Bit,
OpenTelemetry Collector, Zot, rclone, Kyverno or the Sigstore policy-controller; on-prem
monitoring VictoriaMetrics, VictoriaLogs, Jaeger, Perses (Grafana only inside SaaS); SeaweedFS for
on-prem object storage. Container images are INTERNAL/DEV until Nuitka builds exist and go only to
private registries (D-038).

**Approved additions (D-035, D-036, D-040):** `dayjs` (Ant Design 5's date library, used directly by
the shared `DateTimeField`); Tiptap (MIT) as the rich-text editor, with server-side HTML
sanitising, installed with the first incidents work package (D-040).

**Approved additions (D-051):** `nh3` (server-side HTML sanitiser, installed in WP-020) and
`@tiptap/react`, `@tiptap/pm`, `@tiptap/starter-kit` plus the link, table and placeholder
extensions (MIT, no Tiptap Pro; installed in WP-020, pinned 3.31.4, with their companions
`@tiptap/core` and `@tiptap/extensions`). Later: `aioboto3` for WP-022 (D-054).

**Approved additions (D-080):** `@tiptap/extension-mention` and `@tiptap/suggestion` (MIT, 3.31.4;
@mentions in the editor, WP-020b).

**Approved additions (D-082, WP-022):** `pillow` (HPND; image thumbnails and EXIF/GPS stripping,
in a worker with pixel and size limits) and `@tiptap/extension-image` (MIT, 3.31.4; inline images).

**Approved additions (D-092, WP-021):** `openpyxl` (MIT; people imports from Excel, read-only,
values only, with size, row, column and cell limits and a zip-bomb check) with its companion
`et-xmlfile` (MIT); dev-only `types-openpyxl` (Apache-2.0 typeshed stubs).

**Tooling named in the specs (§16.2, §11.4):** ruff, mypy, pytest (+ pytest-asyncio, coverage),
import-linter, Testcontainers, tsc, ESLint, Prettier, Vitest, Playwright, k6, Semgrep, Bandit,
Trivy, cosign.

**Dependency rule:** never add a runtime dependency outside this list without asking the
product owner first. Exception (D-012): small MIT/Apache/BSD-licensed dev or test helpers that an
approved tool needs may be added without asking, but must be listed in the task report. Other
small companion libraries a listed component needs (e.g. its official client SDK,
`@ant-design/icons`) still need to be named in the session report so they can be vetoed. Every dependency must have a licence that allows on-prem
redistribution (§5 licence box); AGPL / source-available needs explicit approval (ADR-012).

## 4. Repository layout (target)

```
backend/                     # architecture.md §6.4
  app/
    main.py                  # app factory, middleware, router registration
    core/                    # config, db session, RLS context, security, logging, errors
    shared/                  # base models, pagination, filtering DSL, outbox, events
    modules/<module>/        # one folder per §6.1 module, same shape for all:
      api/  service/  domain/  infra/  events.py  tests/
    modules/identity_access/bff/  # backend-for-frontend login layer (D-009): same deployable
                                  # and same origin as the UI
  workers/                   # NATS consumers, Temporal workers
  migrations/                # Alembic
  tests/                     # app-level tests (health, wiring); module tests live in modules
  tooling/                   # dev tooling code (custom import-linter contract), never imported by app
  pyproject.toml             # uv-managed; ruff, mypy strict, pytest, import-linter
frontend/                    # pnpm workspace root (lockfile, eslint.config.js), architecture.md §9.2
  apps/console/  apps/portal/
  packages/ui/ api-client/ realtime/ labels/ charts/ forms/ flow/
  e2e/                       # Playwright
deploy/                      # Helm chart + per-profile values, dev docker-compose, k3d config
licence-core/                # Rust licence library (PyO3) — §13.7
mobile/                      # React Native apps (later, §9.1)
docs/
  specs/  specs/media/  adr/  architecture/  DECISIONS.md  PROGRESS.md
Makefile                     # setup, lint, typecheck, test, format, check, build
tsconfig.base.json  .prettierrc.json  .nvmrc  .pre-commit-config.yaml   # shared, repo-wide
```

Run `make check` (lint + typecheck + test for backend and frontend) before reporting any task done.
Python always runs through `uv run` (Python 3.12). Never use the system `python3`, which is 3.9.

Modules (§6.1): identity_access, organization, work_items, service_catalog, knowledge, sla,
automation, assets, cmdb, procurement, projects, esm, monitoring_integrations, discovery,
notifications, analytics, ai, integrations, metadata, licensing, audit; plus announcements
(ADR-024, the walking skeleton and module template: docs/architecture/module-template.md). Do not
invent new modules without an ADR.

Layering inside each module (§6.3): `api → service → domain`, `infra` implements ports. Domain is
pure Python, no I/O. Routers hold no business logic. Services own the transaction, permission
checks, entitlement checks and event emission.

## 5. NON-NEGOTIABLE RULES

Breaking any of these is a failed task, even if tests pass.

**a) Tenant isolation (§7.2, P4).** Every business table has `tenant_id` (first column of every
composite index) and a PostgreSQL RLS policy. Each request/job runs `SET LOCAL app.tenant_id`
inside its transaction. The application DB role must not be a superuser or table owner and must
not have `BYPASSRLS`. Every new table ships with an RLS test proving tenant A cannot read or write
tenant B's rows.

**b) Transactional outbox (§6.5, P3).** Every state change writes its domain event to the outbox
in the *same* transaction as the business row. Never publish to NATS directly from a request.
Events carry an event ID; consumers are idempotent. Event contracts live in the module's
`events.py`.

**c) Real-time everywhere (§8).** Any data shown on screen updates live with no page refresh:
lists, records, dashboards, counters, approvals, portal. Frontend patches the TanStack Query cache
from realtime events and reconciles by refetch when ambiguous (§8.3). Channel names follow §8.1;
subscription tokens are permission-checked (§8.2). Payloads carry IDs, changed fields and version
only — never sensitive data.

**d) Labels, not enums (§9.5, P9).** No raw code, enum key, internal ID, exception name or stack
trace ever reaches the UI. Everything renders through `frontend/packages/labels`
(`incident_management` → "Incident Management"). Every backend enum code needs an English label
(CI-enforced) and an Arabic translation; Urdu becomes mandatory from Stage 2 (D-006). Every screen
must work in RTL. API errors are RFC 9457 problem details with a machine
code + params; the UI maps code → human message.

**e) Module boundaries (§6.1).** Modules never import each other's internals and never query each
other's tables. Cross-module access goes through the other module's public service interface or
through events. Enforced by import-linter contracts in CI — add the contract when you add a module.

**f) Deployment-neutral features (§1.2, §13.1).** Every feature must work on SaaS and on-prem.
Features are gated **only** through the entitlement interface (`has_feature`, `check_limit`,
`remaining`). Never branch on deployment mode (`if saas:` / `if on_prem:`) in domain or service
code. Never read the licence file outside the licensing module. Entitlement decisions are made on
the server, never in the browser. Release feature flags (OpenFeature, §16.1) are for hiding
unfinished work only — never for licensing.

**g) Optimistic concurrency (§6.5, §10).** Every editable record has an integer `version` column.
Updates require the version read (ETag / If-Match); mismatch → 409 Conflict with what changed.
Creates accept an `Idempotency-Key` header.

**h) Protect user data when testing.** Never delete, truncate, overwrite or migrate-down existing
user data or databases when testing or debugging. Create fresh test data (new tenant, new records,
Testcontainers, throwaway volumes) instead. Never run destructive commands (`DROP`, `docker volume
rm`, `git reset --hard`, `rm -rf` outside build output) against anything you did not create in the
current session without asking.

## 6. Data conventions (§7.1)

UUIDv7 primary keys; human display IDs (INC-1042) from a per-tenant sequence table; `timestamptz`
UTC; `created_at`, `updated_at`, `created_by`, `updated_by` on every table; soft delete via
`deleted_at` (hard delete only via GDPR erasure jobs); enums stored as stable lowercase codes;
snake_case, plural table names. Custom field values in typed JSONB with GIN indexes (§6.6).
Field-level history for every change with source (UI, API, rule, workflow, AI agent) (§7.4).
Migrations follow expand/contract (§14.3) and must be reversible.

## 7. API conventions (§10)

REST, `/api/v1/...`, resource-oriented. OpenAPI 3.1 generated from code; breaking changes only in a
new major version (OpenAPI diff in CI). Cursor pagination. Shared JSON filter DSL (§6.5). RFC 9457
errors. ETag/If-Match. Idempotency-Key on POST. Rate-limit headers. Bulk ≤ 1,000 items as background
jobs with streamed progress. Every UI action uses the same public API (P2).

## 8. Security baseline (§11)

Keycloak for all authentication; browser uses OIDC Code + PKCE via a backend-for-frontend with an
HttpOnly Secure SameSite cookie — tokens never in JS (§11.1). One policy layer for API, search,
realtime and AI (§11.2). Secrets never in code, images or logs. Sanitise rich text. PII redaction in
logs. Every privileged action is audited (§7.4). Custom functions never run inside the API process
(§6.7).

## 9. Coding standards

**Python:** ruff (lint + format), mypy `--strict`, pytest (+ Testcontainers for integration),
import-linter. Type everything; no `Any` without a comment explaining why. Async all the way in
request paths.

**TypeScript:** `strict: true` (plus `noUncheckedIndexedAccess`), ESLint (incl. the no-raw-enum
rule), Prettier, Vitest, Playwright for e2e. API types come from the generated `api-client`, never
hand-written duplicates.

**Tests:** domain layer unit-tested without I/O; services tested with real Postgres via
Testcontainers; RLS and outbox behaviour always covered by tests; e2e for critical journeys.

**Commits:** Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`,
`build:`, `ci:`), scope = module or package where useful (`feat(work_items): ...`). One logical
change per commit. Only commit when the user asks or the task explicitly includes it.

**Comments and docs:** explain *why*, not *what*. Reference spec sections (`# see architecture.md
§6.5`) where a rule comes from the spec.

## 10. Definition of done (architecture.md §16.3)

A task is done only when all apply (or the session report explains why one does not):

- Works in SaaS and on-prem profiles and respects licensing (entitlement interface only).
- Updates live in every place the data is shown, with no refresh.
- All visible text uses labels, translated into English and Arabic with RTL working (from day
  one); Urdu too from Stage 2 onward (D-006).
- API documented, permissions enforced, events emitted via outbox, audit recorded.
- Tests at the right layers pass; dashboards/alerts exist for new services; user docs updated.
- ruff, mypy, tsc, ESLint, Prettier, import-linter and tests are green locally.
- `docs/PROGRESS.md` updated.

## 11. How Claude works on this repo

1. **Start of session:** read this file, then `docs/PROGRESS.md` (current status + next WP), then
   the spec sections the WP references. Do not re-read whole specs if the WP is narrow.
2. **One work package per session.** Do only the WP's scope. If you find needed work outside
   scope, record it in PROGRESS.md instead of doing it.
3. **Small steps.** Make a change, run the relevant checks, then continue. Never batch a large
   untested change.
4. **Run tests before saying done.** Report actual results; if something fails or was skipped,
   say so plainly with the output.
5. **Ask before:** adding a dependency outside §3; changing an ADR's decision; changing a
   non-negotiable rule; anything destructive or outward-facing (pushing, publishing, deleting).
6. **New decision → new ADR** in `docs/adr/` (next free number, row in `docs/adr/README.md`) for
   architecture; a `docs/DECISIONS.md` entry for product owner decisions.
7. **Never fake it.** No placeholder implementations reported as finished, no skipped tests to get
   green, no `# type: ignore` / `eslint-disable` without a justification comment.
8. **End of session:** update `docs/PROGRESS.md` (status, WP checkboxes, newest-first session log
   entry) and finish with the report below.

### Working rules (D-024)

- **Never run a destructive git command without saving work first.** `git checkout -- .`,
  `git restore` on unstaged work, `git reset --hard`, `git clean -f` and any force push are only
  allowed after the work they could destroy is saved with `git stash` or a commit (and pushing
  with force still needs the product owner's OK, item 5). When in doubt, `git stash` first.
- **The same protection applies to data:** never delete or overwrite existing data (databases,
  volumes, files, streams, buckets) without the product owner's explicit confirmation; create
  fresh test data instead (rule 5h).

### Session report format

Every task ends with exactly these sections (from the bootstrap task), unless the task prompt
gives its own report format, which then wins. Write "No change" in a section that doesn't apply;
don't drop it.

```
## Files created                      — and files modified/deleted, one line each
## Environment check                  — table: tool | version | status (only tools this task used
                                         or found missing), plus checks run: command | result
## ADR summary                        — table: ADR | decision | status (ADRs added or changed)
## Stage 0 work packages              — table: WP | title | depends on | status (the WP worked on
                                         and anything it unblocked)
## Contradictions or gaps found in the specs
## Questions for the product owner    — include any new dependencies needing approval
```
