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
