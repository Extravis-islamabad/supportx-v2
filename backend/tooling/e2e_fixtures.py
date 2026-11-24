"""`python -m tooling.e2e_fixtures create|delete`: test records for the Playwright suite (WP-010).

Creates 40 requester rows in Demo Company (`e2e-scroll-NN@demo.test`) so the users list has
more than one page to scroll through; `delete` removes exactly those rows again. Only rows this
tool creates are ever touched (CLAUDE.md rule h): they are matched by their reserved e-mail
pattern. They are requesters, so they never take a technician seat. Refuses production.

`delete` also removes what the suite itself created through the UI and API (WP-012, WP-020),
matched by the reserved "E2E " name prefix: announcements (with their field history and audience
rows), incidents and service requests (with their history, approvals and approval links), catalog
items and their emptied categories (WP-030/031), incident templates and admin-added pick-list values
(WP-020c), support groups, sites and departments, and people added in Admin > People that never
signed in (WP-021), in the two dev tenants; plus
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
# People the suite adds through Admin > People (WP-021), never signed in: $1 is SUITE_PREFIX.
SUITE_PEOPLE = (
    "external_subject IS NULL AND display_name LIKE $1"
    " AND (email IS NULL OR email LIKE 'e2e-person-%@demo.test')"
)
# The step that removes whatever else references the suite's work items (see _dependents).
WORK_ITEM_DEPENDENTS = "work_item_dependents"
# The suite's own work items, in the tenant this transaction is set to (and RLS agrees).
SUITE_WORK_ITEMS = (
    "SELECT id FROM work_items WHERE subject LIKE $1"
    " AND tenant_id = current_setting('app.tenant_id')::uuid"
)
# Foreign keys onto a table's `id` that block a delete (NO ACTION or RESTRICT): CASCADE and SET
# NULL ones Postgres handles itself. Composite keys (tenant_id, x) -> (tenant_id, id) match on the
# column paired with `id`; the tenant's own context (RLS) keeps the rest in this tenant.
_BLOCKING_FKS = """
SELECT DISTINCT c.conrelid::regclass::text AS child, a.attname AS col,
       EXISTS (SELECT 1 FROM pg_attribute i WHERE i.attrelid = c.conrelid
               AND i.attname = 'id' AND NOT i.attisdropped) AS has_id
FROM pg_constraint c
CROSS JOIN LATERAL unnest(c.conkey, c.confkey) AS k(child_col, parent_col)
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.child_col
JOIN pg_attribute r ON r.attrelid = c.confrelid AND r.attnum = k.parent_col
WHERE c.contype = 'f' AND c.confrelid = $1::regclass AND r.attname = 'id'
  AND c.confdeltype IN ('a', 'r') AND c.conrelid <> c.confrelid
ORDER BY 1, 2
"""
_MAX_DEPTH = 4
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
    *(
        # Their conversation, followers (WP-020b), tasks and worklogs (WP-020e), which reference
        # the incident.
        (
            table,
            (
                f"DELETE FROM {table} WHERE work_item_id IN"  # noqa: S608 - fixed table names
                " (SELECT id FROM work_items WHERE subject LIKE $1)"
            ),
            SUITE_PREFIX,
        )
        for table in (
            "work_item_conversations",
            "work_item_followers",
            "work_item_tasks",
            "work_item_worklogs",
        )
    ),
    (
        # Links (WP-020e) reference an incident from either side.
        "work_item_links",
        (
            "DELETE FROM work_item_links WHERE"
            " source_id IN (SELECT id FROM work_items WHERE subject LIKE $1)"
            " OR target_id IN (SELECT id FROM work_items WHERE subject LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
    (
        # Service requests (WP-030): the e-mailed links of their approvals (no foreign key: the
        # link names its object by type and ID), then the approvals, which reference the record.
        "action_links",
        (
            "DELETE FROM action_links WHERE object_type = 'work_item_approval' AND object_id IN"
            " (SELECT a.id FROM work_item_approvals a JOIN work_items w ON w.id = a.work_item_id"
            " WHERE w.subject LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
    (
        "work_item_approvals",
        (
            "DELETE FROM work_item_approvals WHERE work_item_id IN"
            " (SELECT id FROM work_items WHERE subject LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
    # Every other table that references the suite's records, found in the catalogue at run time
    # (children before parents), so a new child table can never leave the teardown failing on a
    # foreign key again (work_item_reads, the nightly k3d run; lane A's #-notes on the fix).
    (WORK_ITEM_DEPENDENTS, "", SUITE_PREFIX),
    ("work_items", "DELETE FROM work_items WHERE subject LIKE $1", SUITE_PREFIX),
    (
        # Catalog items the suite made (WP-030/031), after the requests raised from them; one a
        # remaining request still names stays. Then the suite's categories left empty.
        "field_changes",
        (
            "DELETE FROM field_changes WHERE record_type = 'catalog_item' AND record_id IN"
            " (SELECT id FROM catalog_items WHERE names->>'en' LIKE $1"
            " AND id NOT IN (SELECT catalog_item_id FROM work_items"
            " WHERE catalog_item_id IS NOT NULL))"
        ),
        SUITE_PREFIX,
    ),
    (
        "catalog_items",
        (
            "DELETE FROM catalog_items WHERE names->>'en' LIKE $1 AND id NOT IN"
            " (SELECT catalog_item_id FROM work_items WHERE catalog_item_id IS NOT NULL)"
        ),
        SUITE_PREFIX,
    ),
    (
        "field_changes",
        (
            "DELETE FROM field_changes WHERE record_type = 'service_category' AND record_id IN"
            " (SELECT id FROM service_categories WHERE names->>'en' LIKE $1"
            " AND id NOT IN (SELECT category_id FROM catalog_items"
            " WHERE category_id IS NOT NULL))"
        ),
        SUITE_PREFIX,
    ),
    (
        "service_categories",
        (
            "DELETE FROM service_categories WHERE names->>'en' LIKE $1 AND id NOT IN"
            " (SELECT category_id FROM catalog_items WHERE category_id IS NOT NULL)"
        ),
        SUITE_PREFIX,
    ),
    (
        # Templates the suite made (WP-020c), after the incidents that name them.
        "field_changes",
        (
            "DELETE FROM field_changes WHERE record_type = 'work_item_template' AND record_id IN"
            " (SELECT id FROM work_item_templates WHERE labels->>'en' LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
    (
        "work_item_templates",
        "DELETE FROM work_item_templates WHERE labels->>'en' LIKE $1 AND NOT is_default",
        SUITE_PREFIX,
    ),
    (
        # Custom fields the suite added (WP-026), with their history and change log entries.
        "field_changes",
        (
            "DELETE FROM field_changes WHERE record_type = 'custom_field' AND record_id IN"
            " (SELECT id FROM custom_fields WHERE labels->>'en' LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
    ("custom_fields", "DELETE FROM custom_fields WHERE labels->>'en' LIKE $1", SUITE_PREFIX),
    (
        # Pick-list values the suite added (admin values only, never a shipped one).
        "work_item_reasons",
        "DELETE FROM work_item_reasons WHERE labels->>'en' LIKE $1 AND code LIKE 'v\\_%'",
        SUITE_PREFIX,
    ),
    # People the suite added (WP-021): reserved address, or a contact with an "E2E" name.
    (
        "field_changes",
        (
            "DELETE FROM field_changes WHERE record_type = 'user' AND record_id IN"  # noqa: S608 - fixed text
            f" (SELECT id FROM users WHERE {SUITE_PEOPLE})"
        ),
        SUITE_PREFIX,
    ),
    *(
        (
            table,
            f"DELETE FROM {table} WHERE user_id IN (SELECT id FROM users WHERE {SUITE_PEOPLE})",  # noqa: S608 - fixed table names
            SUITE_PREFIX,
        )
        for table in ("user_roles", "group_members", "site_members")
    ),
    ("users", f"DELETE FROM users WHERE {SUITE_PEOPLE}", SUITE_PREFIX),  # noqa: S608 - fixed text
    ("departments", "DELETE FROM departments WHERE name LIKE $1", SUITE_PREFIX),
    (
        "group_sites",
        (
            "DELETE FROM group_sites WHERE group_id IN"
            " (SELECT id FROM support_groups WHERE name LIKE $1)"
        ),
        SUITE_PREFIX,
    ),
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
                    " first_name, user_type, status, locale) VALUES ($1, $2, $3, $4, $5, $6,"
                    " 'requester', 'active', 'en') ON CONFLICT DO NOTHING",
                    uuid.uuid4(),
                    DEMO_TENANT_ID,
                    f"e2e-scroll-{n:02d}",
                    f"e2e-scroll-{n:02d}@demo.test",
                    f"E2E Scroll {n:02d}",
                    f"E2E Scroll {n:02d}",
                )
                created += status.endswith(" 1")
            # Every run starts on the defaults (WP-042): the suite's own users' theme and text
            # size, which one spec's browser may have copied to the server in the last run.
            await conn.execute(
                "UPDATE users SET theme_mode = NULL, text_scale = NULL, updated_at = now()"
                " WHERE email LIKE $1",
                SUITE_USERS,
            )
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


async def _dependents(
    conn: asyncpg.Connection, table: str, ids: str, pattern: str, depth: int = 0
) -> int:
    """Delete every row that references `table`'s rows in `ids` (a subquery on $1), deepest first.

    Read from pg_constraint each run: whatever table a later work package adds is covered.
    """
    if depth >= _MAX_DEPTH:
        return 0
    if depth == 0 and not await conn.fetchval(
        "SELECT current_setting('app.tenant_id', true) <> ''"
    ):
        msg = "the suite's dependents are removed inside one tenant's context only (rule 5h)"
        raise RuntimeError(msg)
    removed = 0
    for row in await conn.fetch(_BLOCKING_FKS, table):
        child, col = row["child"], row["col"]
        rows = f'SELECT id FROM {child} WHERE "{col}" IN ({ids})'  # noqa: S608 - catalogue names
        if row["has_id"]:
            removed += await _dependents(conn, child, rows, pattern, depth + 1)
        status = await conn.execute(
            f'DELETE FROM {child} WHERE "{col}" IN ({ids})',  # noqa: S608 - catalogue names
            pattern,
        )
        removed += int(status.split()[-1])
    return removed


DEV_TENANTS = (DEMO_TENANT_ID, OTHER_TENANT_ID)


async def delete_suite_records(
    url: str, tenants: tuple[uuid.UUID, ...] = DEV_TENANTS, *, test_tenants: bool = False
) -> dict[str, int]:
    """Remove the "E2E …" records the suite created (deleted roles too); returns rows per table.

    `tenants`: the two dev tenants. Any other tenant is refused (rule 5h: this runs against dev
    databases) unless a test passes its own throwaway tenants with `test_tenants=True`.
    """
    if not test_tenants and not set(tenants) <= set(DEV_TENANTS):
        msg = "the e2e teardown only touches the two dev tenants"
        raise ValueError(msg)
    removed = {table: 0 for table, _, _ in SUITE_RECORDS}
    conn = await asyncpg.connect(url)
    try:
        for tenant in tenants:
            async with conn.transaction():
                await _in_tenant(conn, tenant)
                for table, statement, pattern in SUITE_RECORDS:
                    if table == WORK_ITEM_DEPENDENTS:
                        removed[table] += await _dependents(
                            conn, "work_items", SUITE_WORK_ITEMS, pattern
                        )
                        continue
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
