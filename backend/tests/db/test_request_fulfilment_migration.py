"""Migration 0204 (service request fulfilment; WP-047a S5).

Expand only: six task columns with their checks, the item's workflow, and `catalog_item` in the
workflow instances' `started_how` check. Up, down and up again; the downgrade drops only what
0204 added and narrows the check back (rule 5h).
"""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0201"  # 0204's down revision (main's head at its queue turn)
TASK_COLUMNS = {"plan_key", "fields", "field_values", "kind", "task_only", "needs_review"}
TASK_CHECKS = {
    "ck_work_item_tasks_kind_code",
    "ck_work_item_tasks_field_values_object",
    "ck_work_item_tasks_fields_array",
}
HOW = "ck_workflow_instances_started_how_code"


async def _state(url: str) -> tuple[set[str], set[str], bool, str]:
    """(task columns, task checks, the item's workflow column present, started_how's rule)."""
    conn = await asyncpg.connect(url)
    try:
        columns = await conn.fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'work_item_tasks' AND column_name = ANY($1::text[])",
            sorted(TASK_COLUMNS),
        )
        checks = await conn.fetch(
            "SELECT conname FROM pg_constraint WHERE conname = ANY($1::text[])", sorted(TASK_CHECKS)
        )
        workflow = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'catalog_items' AND column_name = 'workflow_id'"
        )
        how = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1", HOW
        )
        return (
            {r["column_name"] for r in columns},
            {r["conname"] for r in checks},
            bool(workflow),
            str(how),
        )
    finally:
        await conn.close()


def test_0204_adds_the_fulfilment_parts_and_its_downgrade_drops_only_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        columns, checks, workflow, how = asyncio.run(_state(database.admin_url))
        assert (columns, checks, workflow) == (set(), set(), False)
        assert "catalog_item" not in how
        db_testing.migrate(database.migrator_url, "0204")
        columns, checks, workflow, how = asyncio.run(_state(database.admin_url))
        assert (columns, checks, workflow) == (TASK_COLUMNS, TASK_CHECKS, True)
        assert "catalog_item" in how
        db_testing.downgrade(database.migrator_url, BEFORE)
        columns, checks, workflow, how = asyncio.run(_state(database.admin_url))
        assert (columns, checks, workflow) == (set(), set(), False)
        assert "catalog_item" not in how
        assert "sub_flow" in how  # narrowed back, never dropped
        db_testing.migrate(database.migrator_url, "0204")
        assert asyncio.run(_state(database.admin_url))[0] == TASK_COLUMNS
    finally:
        db_testing.destroy(db_config, database)
