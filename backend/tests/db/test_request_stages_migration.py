"""Migration 0194 (a request's approval stages; WP-047a S2a).

Expand only: the snapshot column, the branch and skip reason, and the widened state and route
reason checks. Up, down and up again; the downgrade drops only what it added (rule 5h).
"""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0191"  # 0194's down revision (main's head at its queue turn)
CHECKS = (
    "ck_work_item_approvals_state_code",
    "ck_work_item_approvals_reason_code",
    "ck_work_item_approvals_skip_reason_code",
)


async def _shape(url: str) -> tuple[set[str], dict[str, str]]:
    """(the three new columns present, each approval check's definition)."""
    conn = await asyncpg.connect(url)
    try:
        columns = await conn.fetch(
            "SELECT table_name || '.' || column_name AS c FROM information_schema.columns"
            " WHERE (table_name, column_name) IN"
            " (('work_items', 'approval_stages'), ('work_item_approvals', 'branch'),"
            " ('work_item_approvals', 'skip_reason'))"
        )
        checks = await conn.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint"
            " WHERE conname = ANY($1::text[])",
            list(CHECKS),
        )
        return {r["c"] for r in columns}, {r["conname"]: r["d"] for r in checks}
    finally:
        await conn.close()


def test_0194_adds_the_stages_and_its_downgrade_drops_only_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        columns, checks = asyncio.run(_shape(database.admin_url))
        assert columns == set()
        assert "skipped" not in checks[CHECKS[0]]
        assert "no_approver" not in checks[CHECKS[1]]
        before_states, before_reasons = checks[CHECKS[0]], checks[CHECKS[1]]

        db_testing.migrate(database.migrator_url, "0194")
        columns, checks = asyncio.run(_shape(database.admin_url))
        assert columns == {
            "work_items.approval_stages",
            "work_item_approvals.branch",
            "work_item_approvals.skip_reason",
        }
        assert "'skipped'" in checks[CHECKS[0]]
        assert "'no_approver'" in checks[CHECKS[1]]
        assert "'approver_erased'" in checks[CHECKS[1]]  # the earlier codes are kept
        assert "condition_not_met" in checks[CHECKS[2]]

        db_testing.downgrade(database.migrator_url, BEFORE)
        columns, checks = asyncio.run(_shape(database.admin_url))
        assert columns == set()
        assert CHECKS[2] not in checks
        assert (checks[CHECKS[0]], checks[CHECKS[1]]) == (before_states, before_reasons)

        db_testing.migrate(database.migrator_url, "0194")
        assert len(asyncio.run(_shape(database.admin_url))[0]) == 3
    finally:
        db_testing.destroy(db_config, database)
