"""Migration 0132 (change windows; WP-045c) never loses data (rule 5h).

Up, down and up again while no tenant uses it; once one tenant keeps a window, the downgrade is
refused and the table stays. The windows themselves: tests/db/test_change_windows_api.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0130"  # 0132's down revision


async def _has_table(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'change_windows'"
            )
        )
    finally:
        await conn.close()


async def _tenant_with_a_window(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Windows', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO change_windows (tenant_id, id, kind, mode, name, starts_at, ends_at)"
                " VALUES ($1, $2, 'freeze', 'block', 'Kept', now(), now() + interval '1 day')",
                tenant,
                uuid.uuid4(),
            )
    finally:
        await conn.close()


def test_0132_upgrades_downgrades_and_refuses_while_a_tenant_keeps_a_window(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0132")
        assert asyncio.run(_has_table(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_table(database.admin_url))
        db_testing.migrate(database.migrator_url, "0132")
        asyncio.run(_tenant_with_a_window(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_table(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
