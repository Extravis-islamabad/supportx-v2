"""Migration 0137 (D-156: monthly windows, the outside-maintenance block, the freeze's CAB).

Up fills `repeat` from the old weekly flag per tenant; down and up again while nothing uses the
new columns; once a window repeats monthly, the downgrade is refused and the data stays.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0133"  # 0137's down revision until it is re-pointed at its turn


async def _weekly_window(url: str) -> uuid.UUID:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Windows', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        window = uuid.uuid4()
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO change_windows (tenant_id, id, kind, mode, name, starts_at, ends_at,"
                " repeat_weekly) VALUES ($1, $2, 'maintenance', 'warn', 'Sundays', now(),"
                " now() + interval '4 hours', true)",
                tenant,
                window,
            )
        return tenant
    finally:
        await conn.close()


async def _repeat_of(url: str, tenant: uuid.UUID) -> str:
    conn = await asyncpg.connect(url)
    try:
        return str(
            await conn.fetchval("SELECT repeat FROM change_windows WHERE tenant_id = $1", tenant)
        )
    finally:
        await conn.close()


async def _make_monthly(url: str, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "UPDATE change_windows SET repeat = 'monthly', repeat_week = 1,"
                " repeat_weekday = 6, repeat_weekly = false WHERE tenant_id = $1",
                tenant,
            )
    finally:
        await conn.close()


def test_0137_fills_weekly_round_trips_and_refuses_while_a_window_is_monthly(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        tenant = asyncio.run(_weekly_window(database.admin_url))
        db_testing.migrate(database.migrator_url, "0137")
        assert asyncio.run(_repeat_of(database.admin_url, tenant)) == "weekly"  # per tenant
        db_testing.downgrade(database.migrator_url, BEFORE)
        db_testing.migrate(database.migrator_url, "0137")
        asyncio.run(_make_monthly(database.admin_url, tenant))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_repeat_of(database.admin_url, tenant)) == "monthly"
    finally:
        db_testing.destroy(db_config, database)
