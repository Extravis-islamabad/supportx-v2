"""Migration 0167 (signed history redaction; ADR-046 addendum) never loses data (rule 5h).

Up, down and up again while no tenant has a redaction row; refused once one does. The behaviour:
tests/db/test_signed_history_redaction.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0164"  # 0167's down revision


async def _has_table(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval("SELECT to_regclass('field_change_redactions') IS NOT NULL")
        )
    finally:
        await conn.close()


async def _with_a_row(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Redactions', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            # A stand-in row: the mention it points at is not the point here (superuser only).
            await conn.execute("SET LOCAL session_replication_role = replica")
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO field_change_redactions (tenant_id, id, field_change_id, change_id,"
                " record_type, record_id, field, mention_id, old_digest, new_digest, salted,"
                " redacted_at) VALUES ($1, $2, $3, $4, 'work_item', $5, 'subject', $6, 'a', 'b',"
                " true, now())",
                tenant,
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
            )
    finally:
        await conn.close()


def test_0167_upgrades_downgrades_and_refuses_while_a_redaction_exists(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0167")
        assert asyncio.run(_has_table(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_table(database.admin_url))
        db_testing.migrate(database.migrator_url, "0167")
        asyncio.run(_with_a_row(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_table(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
