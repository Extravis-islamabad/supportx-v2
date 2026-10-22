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

Also: supportx_app is not superuser and has no BYPASSRLS.

Adding to PLATFORM_TABLES needs a reason and a reviewer: it removes a table from tenant isolation.
"""

import asyncio
import sys
from dataclasses import dataclass, field

import asyncpg

from app.core.config import Settings
from app.shared.db.rls import APP_ROLE

SCHEMA = "public"
# Tables that are deliberately not tenant-scoped, with what the app may do on them.
PLATFORM_TABLES: dict[str, tuple[frozenset[str], str]] = {
    "tenants": (
        frozenset({"SELECT"}),
        "The tenant registry itself: id IS the tenant. RLS lets the app read only its own row.",
    ),
}
# Not application data at all: never reachable by supportx_app.
IGNORED_TABLES: dict[str, str] = {
    "alembic_version": "Alembic's migration bookkeeping; owned by the migrator, no app grants.",
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

    policies = await conn.fetch(
        """
        SELECT polname, polcmd::text AS polcmd,
               pg_get_expr(polqual, polrelid) AS using_expr,
               pg_get_expr(polwithcheck, polrelid) AS check_expr
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
    """Problems with the application role itself."""
    role = await conn.fetchrow(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = $1", APP_ROLE
    )
    if role is None:
        return [f"role {APP_ROLE} does not exist"]
    problems = []
    if role["rolsuper"]:
        problems.append(f"{APP_ROLE} is a superuser")
    if role["rolbypassrls"]:
        problems.append(f"{APP_ROLE} has BYPASSRLS")
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
