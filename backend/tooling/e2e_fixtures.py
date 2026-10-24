"""`python -m tooling.e2e_fixtures create|delete`: test records for the Playwright suite (WP-010).

Creates 40 requester rows in Demo Company (`e2e-scroll-NN@demo.test`) so the users list has
more than one page to scroll through; `delete` removes exactly those rows again. Only rows this
tool creates are ever touched (CLAUDE.md rule h): they are matched by their reserved e-mail
pattern. They are requesters, so they never take a technician seat. Refuses production.

`delete` also removes what the suite itself created through the UI and API (WP-012, WP-020),
matched by the reserved "E2E " name prefix: announcements (with their field history and audience
rows), incidents (with their history), support groups and sites, in the two dev tenants; plus
the field history of the suite's own users (`e2e.*@demo.test`, profile and layout saves). The API
only soft-deletes, and history is append-only for the application; the suite must leave nothing.

Custom roles named "E2E …" are hard-deleted only once the suite has soft-deleted them (WP-012b):
a live role, a system role or any other name is never touched. Their permission rows cascade.
"""

import asyncio
import sys
import uuid

import asyncpg

from app.core.config import Settings
from tooling.seed_dev import DEMO_TENANT_ID, OTHER_TENANT_ID

COUNT = 40
PATTERN = "e2e-scroll-%@demo.test"
SUITE_PREFIX = "E2E %"
SUITE_USERS = "e2e.%@demo.test"  # the suite's own Keycloak users (frontend/e2e/stack.ts)
# Children first: history and memberships, then the records. ($1: the matching pattern.)
SUITE_RECORDS = (
    (
        "field_changes",
        (
            "DELETE FROM field_changes WHERE record_type = 'announcement' AND record_id IN"
            " (SELECT id FROM announcements WHERE title LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
    (
        # Profile and layout saves of the suite's users (their own records' history).
        "field_changes",
        (
            "DELETE FROM field_changes WHERE record_type = 'user' AND record_id IN"
            " (SELECT id FROM users WHERE email LIKE $1)"
        ),
        SUITE_USERS,
    ),
    ("announcements", "DELETE FROM announcements WHERE title LIKE $1", SUITE_PREFIX),
    (
        # Incidents the suite logged (WP-020), with their history.
        "field_changes",
        (
            "DELETE FROM field_changes WHERE record_type = 'work_item' AND record_id IN"
            " (SELECT id FROM work_items WHERE subject LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
    ("work_items", "DELETE FROM work_items WHERE subject LIKE $1", SUITE_PREFIX),
    (
        "group_members",
        (
            "DELETE FROM group_members WHERE group_id IN"
            " (SELECT id FROM support_groups WHERE name LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
    ("support_groups", "DELETE FROM support_groups WHERE name LIKE $1", SUITE_PREFIX),
    (
        "site_members",
        "DELETE FROM site_members WHERE site_id IN (SELECT id FROM sites WHERE name LIKE $1)",
        SUITE_PREFIX,
    ),
    ("sites", "DELETE FROM sites WHERE name LIKE $1", SUITE_PREFIX),
    (
        # Normally none: deleting a role through the API moves its holders first.
        "user_roles",
        (
            "DELETE FROM user_roles WHERE role_id IN (SELECT id FROM roles"
            " WHERE name LIKE $1 AND deleted_at IS NOT NULL AND NOT is_system)"
        ),
        SUITE_PREFIX,
    ),
    (
        "roles",
        "DELETE FROM roles WHERE name LIKE $1 AND deleted_at IS NOT NULL AND NOT is_system",
        SUITE_PREFIX,
    ),
)


async def _in_tenant(conn: asyncpg.Connection, tenant: uuid.UUID = DEMO_TENANT_ID) -> None:
    # Business tables have FORCED RLS: even the migrator works inside the tenant's context.
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))


async def create(url: str) -> int:
    """Insert the fixture users that are missing; returns how many were created."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await _in_tenant(conn)
            created = 0
            for n in range(COUNT):
                status = await conn.execute(
                    "INSERT INTO users (id, tenant_id, external_subject, email, display_name,"
                    " user_type, status, locale) VALUES ($1, $2, $3, $4, $5, 'requester',"
                    " 'active', 'en') ON CONFLICT DO NOTHING",
                    uuid.uuid4(),
                    DEMO_TENANT_ID,
                    f"e2e-scroll-{n:02d}",
                    f"e2e-scroll-{n:02d}@demo.test",
                    f"E2E Scroll {n:02d}",
                )
                created += status.endswith(" 1")
            return created
    finally:
        await conn.close()


async def delete(url: str) -> int:
    """Remove the fixture users (and nothing else); returns how many were removed."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await _in_tenant(conn)
            status = await conn.execute("DELETE FROM users WHERE email LIKE $1", PATTERN)
            return int(status.split()[-1])
    finally:
        await conn.close()


async def delete_suite_records(url: str) -> dict[str, int]:
    """Remove the "E2E …" records the suite created (deleted roles too); returns rows per table."""
    removed = {table: 0 for table, _, _ in SUITE_RECORDS}
    conn = await asyncpg.connect(url)
    try:
        for tenant in (DEMO_TENANT_ID, OTHER_TENANT_ID):
            async with conn.transaction():
                await _in_tenant(conn, tenant)
                for table, statement, pattern in SUITE_RECORDS:
                    status = await conn.execute(statement, pattern)
                    removed[table] += int(status.split()[-1])
    finally:
        await conn.close()
    return removed


def main() -> int:  # pragma: no cover - thin CLI over the tested functions
    """CLI entry point."""
    settings = Settings()
    if settings.profile == "production" or settings.migration_database_url is None:
        sys.stderr.write(
            "e2e fixtures need a dev/test profile and SUPPORTX_MIGRATION_DATABASE_URL\n"
        )
        return 2
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    url = settings.migration_database_url.get_secret_value()
    done = asyncio.run(create(url) if action == "create" else delete(url))
    sys.stdout.write(f"e2e fixtures {action}: {done} rows\n")
    if action == "delete":
        suite = asyncio.run(delete_suite_records(url))
        sys.stdout.write(f"e2e suite records deleted: {suite}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
