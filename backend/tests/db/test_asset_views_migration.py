"""Migration 0140 (asset views and the shared list-settings store; WP-049b s4a) never loses data.

Up, down and up again while no tenant keeps a list setting; once one does, the downgrade is
refused and the table and the index stay (rule 5h).
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0135"  # 0140's down revision (re-pointed with it)


async def _shape(url: str) -> tuple[int, int]:
    """(the list_settings table, the asset list's product-type index)."""
    conn = await asyncpg.connect(url)
    try:
        table = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'list_settings'"
        )
        index = await conn.fetchval(
            "SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_assets_type_updated'"
        )
        return int(table), int(index)
    finally:
        await conn.close()


async def _tenant_with_a_setting(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant, user = uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Lists', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO users (id, tenant_id, display_name, first_name, user_type)"
                " VALUES ($1, $2, 'Lister', 'Lister', 'requester')",
                user,
                tenant,
            )
            await conn.execute(
                "INSERT INTO list_settings (tenant_id, id, user_id, list_key, view_key)"
                " VALUES ($1, $2, $3, 'assets', 'all')",
                tenant,
                uuid.uuid4(),
                user,
            )
    finally:
        await conn.close()


def test_0140_upgrades_downgrades_and_refuses_while_a_tenant_keeps_settings(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_shape(database.admin_url)) == (0, 0)
        db_testing.migrate(database.migrator_url, "0140")
        assert asyncio.run(_shape(database.admin_url)) == (1, 1)
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url)) == (0, 0)
        db_testing.migrate(database.migrator_url, "0140")
        asyncio.run(_tenant_with_a_setting(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url)) == (1, 1)
    finally:
        db_testing.destroy(db_config, database)
