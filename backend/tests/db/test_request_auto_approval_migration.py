"""Migration 0195 (automatic approval, adjusting a running approval; WP-047a S2b).

Expand only: two approval columns and their checks, the widened state, channel and purpose
checks, and the tenant's "approved earlier" switch. Up, down and up again; the downgrade drops
only what it added and refuses while a tenant has a row using the new codes (rule 5h).
"""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0192"  # 0195's down revision (main's head at its queue turn)
STATE, CHANNEL, PURPOSE = (
    "ck_work_item_approvals_state_code",
    "ck_work_item_approvals_channel_code",
    "ck_work_item_approvals_purpose_code",
)
NEW_CHECKS = (
    "ck_work_item_approvals_auto_reason_code",
    "ck_work_item_approvals_auto_reason_set",
    "ck_work_item_approvals_auto_ref_positive",
)


async def _shape(url: str) -> tuple[set[str], dict[str, str]]:
    conn = await asyncpg.connect(url)
    try:
        columns = await conn.fetch(
            "SELECT table_name || '.' || column_name AS c FROM information_schema.columns"
            " WHERE (table_name, column_name) IN"
            " (('work_item_approvals', 'auto_reason'), ('work_item_approvals', 'auto_ref'),"
            " ('work_item_type_settings', 'auto_approve_earlier'))"
        )
        checks = await conn.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint"
            " WHERE conname = ANY($1::text[])",
            [STATE, CHANNEL, PURPOSE, *NEW_CHECKS],
        )
        return {r["c"] for r in columns}, {r["conname"]: r["d"] for r in checks}
    finally:
        await conn.close()


def test_0195_adds_its_parts_and_its_downgrade_drops_only_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        columns, checks = asyncio.run(_shape(database.admin_url))
        assert columns == set()
        assert not set(NEW_CHECKS) & set(checks)
        before = (checks[STATE], checks[CHANNEL], checks[PURPOSE])
        assert "replaced" not in checks[STATE]

        db_testing.migrate(database.migrator_url, "0195")
        columns, checks = asyncio.run(_shape(database.admin_url))
        assert columns == {
            "work_item_approvals.auto_reason",
            "work_item_approvals.auto_ref",
            "work_item_type_settings.auto_approve_earlier",
        }
        assert "'replaced'" in checks[STATE]
        assert "'skipped'" in checks[STATE]
        assert "'automatic'" in checks[CHANNEL]
        assert "'email_link'" in checks[CHANNEL]
        assert "'ad_hoc'" in checks[PURPOSE]
        assert "'workflow'" in checks[PURPOSE]
        assert set(NEW_CHECKS) <= set(checks)

        db_testing.downgrade(database.migrator_url, BEFORE)
        columns, checks = asyncio.run(_shape(database.admin_url))
        assert columns == set()
        assert not set(NEW_CHECKS) & set(checks)
        assert (checks[STATE], checks[CHANNEL], checks[PURPOSE]) == before

        db_testing.migrate(database.migrator_url, "0195")
        assert len(asyncio.run(_shape(database.admin_url))[0]) == 3
    finally:
        db_testing.destroy(db_config, database)
