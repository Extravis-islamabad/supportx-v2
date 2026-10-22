# Tenant isolation: how it works

SupportX keeps every customer's data in one shared PostgreSQL database (architecture.md §7.2,
ADR-007). Isolation is enforced **by the database itself**, not by remembering to add
`WHERE tenant_id = ...` to every query. If application code has a bug, the database still refuses
to show or change another tenant's rows.

## The pieces, in plain English

1. **Every business table has a `tenant_id` column** saying which customer owns the row.
2. **Every business table has row-level security (RLS) switched on and forced.** PostgreSQL adds
   an invisible filter to every query on it: "only rows whose `tenant_id` equals the current
   tenant". *Forced* means even the table's owner is filtered.
3. **Every database transaction is told who the current tenant is.** At the start of each
   transaction the API runs `set_config('app.tenant_id', '<tenant>', true)` (the parameterised
   form of `SET LOCAL`). The setting lives only until the transaction ends.
4. **No tenant means nothing.** If no tenant is set, the filter compares with NULL, which matches
   no row: reads return zero rows and writes are rejected.
5. **The API's database login is powerless to switch this off.** It (`supportx_app`) is not a
   superuser, owns no table, has no `BYPASSRLS`, and is never granted `TRUNCATE` (which ignores
   RLS). Only the separate migration login (`supportx_migrator`) owns tables.

## Who sets the tenant

| Profile | Where the tenant comes from |
|---|---|
| dev, test | The `X-Tenant-ID` request header (a tenant UUID), so the API can be used before login exists. |
| production | **The header is ignored completely.** Until login arrives (WP-006), every tenant endpoint answers `401 tenant_required`. |

The resolved tenant is kept for the request (`TenantContext`), added to every log line, and handed
to the database session. A database session for tenant work refuses to run any SQL if it has no
tenant (`TenantContextMissingError`), before anything reaches PostgreSQL.

Each request is one *unit of work*: one transaction, committed after the endpoint finishes (and
before the response is sent), rolled back if anything fails.

## The exact policy

For a tenant table `t`, migrations call `enable_tenant_rls("t")`, which creates:

```sql
ALTER TABLE t ENABLE ROW LEVEL SECURITY;
ALTER TABLE t FORCE ROW LEVEL SECURITY;
CREATE POLICY t_tenant_select ON t FOR SELECT USING      (tenant_id = <current tenant>);
CREATE POLICY t_tenant_insert ON t FOR INSERT WITH CHECK (tenant_id = <current tenant>);
CREATE POLICY t_tenant_update ON t FOR UPDATE USING      (tenant_id = <current tenant>)
                                              WITH CHECK (tenant_id = <current tenant>);
CREATE POLICY t_tenant_delete ON t FOR DELETE USING      (tenant_id = <current tenant>);
-- <current tenant> = NULLIF(current_setting('app.tenant_id', true), '')::uuid
```

Why `NULLIF(..., '')`: connections are shared through PgBouncer. After a transaction that set a
tenant ends, PostgreSQL reports the setting as an empty string rather than "not set", and
`''::uuid` would be an error. `NULLIF` turns it into NULL, which simply matches nothing.

## Platform tables (the only exceptions)

A few tables are not owned by a single tenant. They are listed, with a reason, in
`backend/tooling/rls_guard.py` (`PLATFORM_TABLES`) and must still have RLS enabled and forced.

| Table | Why it is not tenant-scoped | What the API may do |
|---|---|---|
| `tenants` | The registry of tenants: a row's `id` *is* the tenant. | `SELECT` only, and RLS shows it only its own tenant's row. Creating or changing tenants is a provisioning job run as `supportx_migrator`. |

`alembic_version` (migration bookkeeping) is ignored: the API has no access to it.

## Adding a new tenant-scoped table

1. Model it on `TenantEntity` (UUIDv7 `id`, `tenant_id`, timestamps, `created_by`/`updated_by`,
   `version`, `deleted_at`):

   ```python
   class Ticket(TenantEntity):
       __tablename__ = "tickets"
       title: Mapped[str]
       __table_args__ = (Index(None, "tenant_id", "created_at"),)  # tenant_id first
   ```

2. `make db-revision m="add tickets"`, then in the generated migration, right after
   `op.create_table("tickets", ...)`:

   ```python
   from migrations.helpers import enable_tenant_rls, grant_app

   enable_tenant_rls("tickets")
   grant_app("tickets")            # SELECT, INSERT, UPDATE, DELETE (never TRUNCATE)
   ```

3. Every composite index and unique constraint starts with `tenant_id`.
4. Access it through a `Repository` subclass (optimistic concurrency, soft delete, audit columns
   handled for you), inside a `TenantSession` (the per-request unit of work).
5. Add an RLS test for the new table: tenant A cannot select, update, delete or insert tenant B's
   rows (copy `backend/tests/db/test_tenant_isolation.py`).
6. `make db-migrate db-guard` locally; CI runs the same guard on every pull request.

## What the guard checks (`make db-guard`, and in CI on every PR)

`backend/tooling/rls_guard.py` inspects the real, migrated database and fails if any table in the
`public` schema:

- is not on the platform allowlist and has no `tenant_id uuid NOT NULL` column;
- does not have RLS **enabled** and **forced**;
- lacks tenant policies covering SELECT, INSERT, UPDATE and DELETE, or has a policy that is
  unconditionally true or never compares `tenant_id` with `app.tenant_id`;
- has a multi-column index that does not start with `tenant_id`;
- is owned by `supportx_app`, or grants it `TRUNCATE`, `REFERENCES` or `TRIGGER`;
- (platform tables) grants `supportx_app` more than the allowlist says.

It also fails if `supportx_app` is a superuser or has `BYPASSRLS`.

## PgBouncer and prepared statements

The API connects as `supportx_app` through PgBouncer in **transaction** mode: a server connection
is lent to a client for one transaction only. Two consequences:

- Tenant context must be transaction-scoped (`SET LOCAL` / `set_config(..., true)`), never
  session-scoped, or it would leak to the next client. That is exactly what we do.
- asyncpg normally prepares each SQL statement once per connection and reuses it by name. With
  transaction pooling the next transaction may land on a different server connection, which fails
  with `prepared statement "__asyncpg_stmt_…" does not exist`. We turn off asyncpg's statement
  cache and SQLAlchemy's prepared-statement cache, and give any statement SQLAlchemy still prepares
  a unique name. This works with any transaction-mode pooler and any PgBouncer version, at the
  cost of one extra parse per statement. PgBouncer 1.21+ can track prepared statements itself
  (`max_prepared_statements`, on in the dev stack), but on-prem customers may bring a pooler that
  cannot, so we do not depend on it; CI runs PgBouncer with that feature **off** to prove it.

Migrations and tooling (`supportx_migrator`) connect to PostgreSQL directly, not through PgBouncer.

## Display IDs (INC-1042)

`next_display_id(session, "INC")` returns the next number for the session's tenant from
`display_id_sequences` with one atomic upsert. Concurrent callers never get duplicates; they queue
on the counter row until the caller's transaction ends. Because it runs in the caller's
transaction, a rollback returns the number (no gap); gaps are still allowed (e.g. after a hard
delete) and must not be relied on. Keep record-creating transactions short.
