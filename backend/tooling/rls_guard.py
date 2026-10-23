"""Tenant-isolation guard: inspects a real, migrated database and lists every violation (WP-005).

Run by the test suite after migrations (CI) and on demand: `make db-guard` (dev database).

For every table in the `public` schema:

  tenant-scoped (default)  - has `tenant_id uuid NOT NULL`
                           - RLS enabled AND forced
                           - policies cover SELECT, INSERT, UPDATE and DELETE, each comparing
                             with `app.tenant_id`, and no policy is unconditionally true
                           - every multi-column index starts with tenant_id
  platform (allowlisted)   - RLS enabled AND forced; app privileges exactly as listed
  any table                - supportx_app owns nothing and never has TRUNCATE, REFERENCES or
                             TRIGGER (TRUNCATE ignores RLS)
                           - supportx_relay has exactly the rights in RELAY_PRIVILEGES (table and
                             column level) and nothing on any other table
  cross-tenant policies    - a policy that is not tenant-restricted is allowed only if it is in
                             CROSS_TENANT_POLICIES and applies to exactly that role (never PUBLIC,
                             never supportx_app)

Also: supportx_app and supportx_relay are not superusers and have no BYPASSRLS.

Adding to PLATFORM_TABLES or CROSS_TENANT_POLICIES needs a reason and a reviewer: it removes a
table (or a role's view of it) from tenant isolation.
"""

import asyncio
import sys
from dataclasses import dataclass, field

import asyncpg

from app.core.config import Settings
from app.shared.db.rls import APP_ROLE, RELAY_ROLE

SCHEMA = "public"
# Tables that are deliberately not tenant-scoped, with what the app may do on them.
PLATFORM_TABLES: dict[str, tuple[frozenset[str], str]] = {
    "tenants": (
        frozenset({"SELECT"}),
        "The tenant registry itself: id IS the tenant. RLS lets the app read only its own row.",
    ),
    "tenant_subscriptions": (
        frozenset({"SELECT"}),
        (
            "Control-plane plan per tenant (WP-009): the app reads only its own row and can "
            "never change what a tenant is entitled to."
        ),
    ),
}
# Not application data at all: never reachable by supportx_app.
IGNORED_TABLES: dict[str, str] = {
    "alembic_version": "Alembic's migration bookkeeping; owned by the migrator, no app grants.",
}
# (table, policy) -> (the only role it may apply to, why it may see every tenant).
CROSS_TENANT_POLICIES: dict[tuple[str, str], tuple[str, str]] = {
    (
        "outbox_events",
        f"outbox_events_relay_{command}",
    ): (RELAY_ROLE, "The outbox relay publishes every tenant's events (WP-007, events.md).")
    for command in ("select", "update", "delete")
} | {
    (table, f"{table}_relay_{command}"): (
        RELAY_ROLE,
        "Housekeeping by the relay (WP-012, migration 0010): only rows past their retention.",
    )
    for table in ("idempotency_keys", "processed_events")
    for command in ("select", "delete")
}
# Everything supportx_relay may do, per table: (table privileges, columns it may UPDATE).
RELAY_PRIVILEGES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "outbox_events": (
        frozenset({"SELECT", "DELETE"}),
        frozenset({"published_at", "publish_attempts", "last_error", "updated_at"}),
    ),
    "idempotency_keys": (frozenset({"SELECT", "DELETE"}), frozenset()),
    "processed_events": (frozenset({"SELECT", "DELETE"}), frozenset()),
}
REQUIRED_COMMANDS = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
FORBIDDEN_APP_PRIVILEGES = frozenset({"TRUNCATE", "REFERENCES", "TRIGGER"})


@dataclass
class TableReport:
    """Isolation status of one table."""

    name: str
    kind: str
    has_tenant_id: bool = False
    rls_enabled: bool = False
    rls_forced: bool = False
    policies: list[str] = field(default_factory=list)
    app_privileges: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)


async def _tables(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT c.oid, c.relname, c.relrowsecurity, c.relforcerowsecurity,
               pg_get_userbyid(c.relowner) AS owner
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = $1 AND c.relkind IN ('r', 'p')
        ORDER BY c.relname
        """,
        SCHEMA,
    )


async def inspect(conn: asyncpg.Connection) -> list[TableReport]:
    """Report for every table in the schema, with problems filled in."""
    reports: list[TableReport] = []
    for table in await _tables(conn):
        name = table["relname"]
        if name in IGNORED_TABLES:
            continue
        kind = "platform" if name in PLATFORM_TABLES else "tenant"
        report = TableReport(
            name=name,
            kind=kind,
            rls_enabled=table["relrowsecurity"],
            rls_forced=table["relforcerowsecurity"],
        )
        await _check_common(conn, table, report)
        if kind == "tenant":
            await _check_tenant_table(conn, table["oid"], report)
        else:
            allowed, _reason = PLATFORM_TABLES[name]
            if report.app_privileges - allowed:
                report.problems.append(
                    f"{APP_ROLE} has {sorted(report.app_privileges - allowed)} beyond the allowlist"
                )
        reports.append(report)
    return reports


async def _check_common(
    conn: asyncpg.Connection, table: asyncpg.Record, report: TableReport
) -> None:
    if not report.rls_enabled:
        report.problems.append("RLS not enabled")
    if not report.rls_forced:
        report.problems.append("RLS not forced (the owner would bypass it)")
    if table["owner"] == APP_ROLE:
        report.problems.append(f"owned by {APP_ROLE}")
    privileges = await conn.fetch(
        """
        SELECT privilege_type FROM information_schema.role_table_grants
        WHERE grantee = $1 AND table_schema = $2 AND table_name = $3
        """,
        APP_ROLE,
        SCHEMA,
        report.name,
    )
    report.app_privileges = {row["privilege_type"] for row in privileges}
    forbidden = report.app_privileges & FORBIDDEN_APP_PRIVILEGES
    if forbidden:
        report.problems.append(f"{APP_ROLE} has forbidden privileges {sorted(forbidden)}")
    policies = await conn.fetch(
        "SELECT polname FROM pg_policy WHERE polrelid = $1 ORDER BY polname", table["oid"]
    )
    report.policies = [row["polname"] for row in policies]
    await _check_relay(conn, table["oid"], report)


async def _check_relay(conn: asyncpg.Connection, oid: int, report: TableReport) -> None:
    """supportx_relay: exactly RELAY_PRIVILEGES on its tables, nothing anywhere else."""
    allowed_table, allowed_columns = RELAY_PRIVILEGES.get(report.name, (frozenset(), frozenset()))
    table_privileges = {
        row["privilege_type"]
        for row in await conn.fetch(
            """
            SELECT privilege_type FROM information_schema.role_table_grants
            WHERE grantee = $1 AND table_schema = $2 AND table_name = $3
            """,
            RELAY_ROLE,
            SCHEMA,
            report.name,
        )
    }
    if table_privileges - allowed_table:
        report.problems.append(
            f"{RELAY_ROLE} has {sorted(table_privileges - allowed_table)} beyond RELAY_PRIVILEGES"
        )
    # Column-level grants live in pg_attribute.attacl (explicit grants only).
    column_grants = await conn.fetch(
        """
        SELECT a.attname, acl.privilege_type
        FROM pg_attribute a, aclexplode(a.attacl) acl
        WHERE a.attrelid = $1 AND acl.grantee = (SELECT oid FROM pg_roles WHERE rolname = $2)
        """,
        oid,
        RELAY_ROLE,
    )
    for grant in column_grants:
        if grant["privilege_type"] != "UPDATE" or grant["attname"] not in allowed_columns:
            report.problems.append(
                f"{RELAY_ROLE} has column {grant['privilege_type']} on {grant['attname']}"
            )


async def _check_tenant_table(conn: asyncpg.Connection, oid: int, report: TableReport) -> None:
    column = await conn.fetchrow(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull
        FROM pg_attribute a WHERE a.attrelid = $1 AND a.attname = 'tenant_id' AND NOT a.attisdropped
        """,
        oid,
    )
    report.has_tenant_id = column is not None
    if column is None:
        report.problems.append("no tenant_id column (add it, or allowlist as a platform table)")
    elif column["type"] != "uuid" or not column["attnotnull"]:
        report.problems.append("tenant_id must be uuid NOT NULL")
    await _check_tenant_policies(conn, oid, report)
    await _check_indexes(conn, oid, report)


async def _check_tenant_policies(conn: asyncpg.Connection, oid: int, report: TableReport) -> None:
    policies = await conn.fetch(
        """
        SELECT polname, polcmd::text AS polcmd,
               pg_get_expr(polqual, polrelid) AS using_expr,
               pg_get_expr(polwithcheck, polrelid) AS check_expr,
               0 = ANY(polroles) AS for_public,
               ARRAY(SELECT rolname FROM pg_roles WHERE oid = ANY(polroles)) AS roles
        FROM pg_policy WHERE polrelid = $1
        """,
        oid,
    )
    covered: set[str] = set()
    commands = {
        "r": {"SELECT"},
        "a": {"INSERT"},
        "w": {"UPDATE"},
        "d": {"DELETE"},
        "*": REQUIRED_COMMANDS,
    }
    for policy in policies:
        cross_tenant = CROSS_TENANT_POLICIES.get((report.name, policy["polname"]))
        if cross_tenant is not None:
            if policy["for_public"] or list(policy["roles"]) != [cross_tenant[0]]:
                report.problems.append(
                    f"policy {policy['polname']} must apply only TO {cross_tenant[0]}"
                )
            continue  # allowlisted; does not count towards the tenant policies below
        expressions = [e for e in (policy["using_expr"], policy["check_expr"]) if e]
        if not expressions or any(e.strip().lower() == "true" for e in expressions):
            report.problems.append(f"policy {policy['polname']} is not tenant-restricted")
            continue
        if not all(
            "app.tenant_id" in e and "tenant_id" in e.replace("app.tenant_id", "")
            for e in expressions
        ):
            report.problems.append(
                f"policy {policy['polname']} does not compare tenant_id with app.tenant_id"
            )
            continue
        covered |= commands[policy["polcmd"]]
    missing = REQUIRED_COMMANDS - covered
    if missing:
        report.problems.append(f"no tenant policy for {sorted(missing)}")


async def _check_indexes(conn: asyncpg.Connection, oid: int, report: TableReport) -> None:
    indexes = await conn.fetch(
        """
        SELECT ic.relname AS index_name,
               (SELECT a.attname FROM pg_attribute a
                 WHERE a.attrelid = i.indrelid AND a.attnum = i.indkey[0]) AS first_column,
               i.indnatts AS columns
        FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
        WHERE i.indrelid = $1
        """,
        oid,
    )
    for index in indexes:
        if index["columns"] > 1 and index["first_column"] != "tenant_id":
            report.problems.append(f"index {index['index_name']} does not start with tenant_id")


async def role_problems(conn: asyncpg.Connection) -> list[str]:
    """Problems with the runtime roles themselves (application and relay)."""
    problems = []
    for name in (APP_ROLE, RELAY_ROLE):
        role = await conn.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = $1", name
        )
        if role is None:
            problems.append(f"role {name} does not exist")
            continue
        if role["rolsuper"]:
            problems.append(f"{name} is a superuser")
        if role["rolbypassrls"]:
            problems.append(f"{name} has BYPASSRLS")
    return problems


def render(reports: list[TableReport], extra: list[str]) -> str:
    """Plain-text table for humans and CI logs."""
    lines = [f"{'table':28} {'kind':9} {'tenant_id':9} {'RLS':4} {'forced':6} policies"]
    lines.extend(
        f"{r.name:28} {r.kind:9} {'yes' if r.has_tenant_id else '-':9} "
        f"{'yes' if r.rls_enabled else 'NO':4} {'yes' if r.rls_forced else 'NO':6} "
        f"{', '.join(r.policies) or '-'}"
        for r in reports
    )
    problems = extra + [f"{r.name}: {p}" for r in reports for p in r.problems]
    lines.append("")
    lines.extend(f"FAIL {p}" for p in problems)
    lines.append("RLS guard: FAIL" if problems else "RLS guard: PASS")
    return "\n".join(lines) + "\n"


async def run(url: str) -> tuple[list[TableReport], list[str]]:
    """Inspect the database at `url` (any role that can read the catalogs)."""
    conn = await asyncpg.connect(url)
    try:
        return await inspect(conn), await role_problems(conn)
    finally:
        await conn.close()


def main() -> int:  # pragma: no cover - thin CLI over tested functions
    """`make db-guard`: check the dev database (SUPPORTX_MIGRATION_DATABASE_URL)."""
    url = Settings().migration_database_url
    if url is None:
        sys.stderr.write("SUPPORTX_MIGRATION_DATABASE_URL is not set (make backend-env)\n")
        return 2
    reports, extra = asyncio.run(run(url.get_secret_value()))
    sys.stdout.write(render(reports, extra))
    return 1 if extra or any(r.problems for r in reports) else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
