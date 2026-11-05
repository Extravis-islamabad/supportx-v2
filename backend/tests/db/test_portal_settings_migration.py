"""Migrations 0096 and 0097: going back never drops tenants' data (rule 5h, lane B's review).

0096's downgrade refuses while any tenant has saved portal settings. It checks per tenant
with app.tenant_id set, as the table forces RLS. 0097's dismissals and follows are guarded the
same way (the same DO block); the API tests fill those tables. Here 0097 goes down on an empty
database and back up.
"""

import asyncio

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db


async def _settings_row(admin_url: str, tenant: object) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(
            "INSERT INTO work_item_portal_settings (tenant_id, profile_editing) VALUES ($1, false)",
            tenant,
        )
    finally:
        await conn.close()


async def _clear(admin_url: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute("DELETE FROM work_item_portal_settings")
    finally:
        await conn.close()


def test_going_back_refuses_while_a_tenant_has_portal_settings(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0097")
    try:
        # 0097 has no rows: it goes down and up again.
        db_testing.downgrade(database.migrator_url, "0096")
        db_testing.migrate(database.migrator_url, "0097")
        tenant = asyncio.run(create_tenant(database.migrator_url))
        asyncio.run(_settings_row(database.admin_url, tenant))
        db_testing.downgrade(database.migrator_url, "0096")
        with pytest.raises(Exception, match="has portal settings"):
            db_testing.downgrade(database.migrator_url, "0092")
        asyncio.run(_clear(database.admin_url))  # a throwaway database (rule 5h)
        db_testing.downgrade(database.migrator_url, "0092")
        db_testing.migrate(database.migrator_url, "0097")  # and up again
    finally:
        db_testing.destroy(db_config, database)
