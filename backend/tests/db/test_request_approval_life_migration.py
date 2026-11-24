"""Migration 0196 (approval reminders, escalation and clarification; WP-047a S3a).

Expand only: the tenant's reminder schedule, the approval's escalation and pause columns, the
widened origin and route reason checks, and `approval_clarifications` with RLS. Up, down and up
again; the downgrade drops only what it added.
"""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0195"
ORIGIN, REASON = "ck_work_item_approvals_origin_code", "ck_work_item_approvals_reason_code"
COLUMNS = {
    "work_item_type_settings.approval_reminder_after_days",
    "work_item_type_settings.approval_reminder_count",
    "work_item_type_settings.approval_reminder_minute",
    "work_item_approvals.escalated_from_id",
    "work_item_approvals.paused_seconds",
}
NEW_CONSTRAINTS = (
    "uq_work_item_approvals_tenant_id_id",
    "fk_wia_escalated_from",
    "ck_work_item_approvals_paused_seconds_positive",
    "ck_work_item_approvals_escalated_origin",
    "ck_work_item_type_settings_approval_reminder_after_days",
    "ck_work_item_type_settings_approval_reminder_count",
    "ck_work_item_type_settings_approval_reminder_minute",
)


async def _shape(url: str) -> tuple[set[str], dict[str, str], tuple[bool, bool] | None]:
    conn = await asyncpg.connect(url)
    try:
        columns = await conn.fetch(
            "SELECT table_name || '.' || column_name AS c FROM information_schema.columns"
            " WHERE table_name || '.' || column_name = ANY($1::text[])",
            sorted(COLUMNS),
        )
        checks = await conn.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint"
            " WHERE conname = ANY($1::text[])",
            [ORIGIN, REASON, *NEW_CONSTRAINTS],
        )
        rls = await conn.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = 'approval_clarifications'"
        )
        return (
            {r["c"] for r in columns},
            {r["conname"]: r["d"] for r in checks},
            None if rls is None else (rls["relrowsecurity"], rls["relforcerowsecurity"]),
        )
    finally:
        await conn.close()


def test_0196_adds_its_parts_and_its_downgrade_drops_only_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        columns, checks, table = asyncio.run(_shape(database.admin_url))
        assert columns == set()
        assert table is None
        assert not set(NEW_CONSTRAINTS) & set(checks)
        before = (checks[ORIGIN], checks[REASON])
        assert "escalated" not in checks[ORIGIN]

        db_testing.migrate(database.migrator_url, "0196")
        columns, checks, table = asyncio.run(_shape(database.admin_url))
        assert columns == COLUMNS
        assert table == (True, True)  # RLS enabled and forced (rule 5a)
        assert "'escalated'" in checks[ORIGIN]
        assert "'administrators'" in checks[ORIGIN]
        assert "'no_escalation_target'" in checks[REASON]
        assert "'no_approver'" in checks[REASON]
        assert set(NEW_CONSTRAINTS) <= set(checks)

        db_testing.downgrade(database.migrator_url, BEFORE)
        columns, checks, table = asyncio.run(_shape(database.admin_url))
        assert columns == set()
        assert table is None
        assert not set(NEW_CONSTRAINTS) & set(checks)
        assert (checks[ORIGIN], checks[REASON]) == before

        db_testing.migrate(database.migrator_url, "0196")
        assert asyncio.run(_shape(database.admin_url))[0] == COLUMNS
    finally:
        db_testing.destroy(db_config, database)
