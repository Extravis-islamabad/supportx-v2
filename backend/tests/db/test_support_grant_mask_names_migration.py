"""Migration 0188 (D-180: a grant's "Mask names too" tick) never unmasks names on a downgrade.

Up, down and up again while no grant has the tick; once a grant in any tenant has it, the
downgrade is refused and the column stays: dropping it would show that engineer the names the
admin chose to hide. Existing grants come out of the upgrade with names visible (D-180's default).
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0195"  # 0188's down revision (re-pointed with it at the lane's queue turn)


async def _has_column(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'support_grants' AND column_name = 'mask_names'"
            )
        )
    finally:
        await conn.close()


async def _three_tenants_with_grants(url: str) -> list[uuid.UUID]:
    """A grant in each of three tenants (made before 0188); returns the tenants."""
    conn = await asyncpg.connect(url)
    tenants = [uuid.uuid4() for _ in range(3)]
    try:
        for tenant in tenants:
            await conn.execute(
                "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Mask names', $2)",
                tenant,
                f"t-{tenant.hex[:12]}",
            )
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
                await conn.execute(
                    "INSERT INTO support_grants (id, tenant_id, engineer_name, engineer_email,"
                    " reason, starts_at, ends_at, verification)"
                    " VALUES ($1, $2, 'Sam Engineer', $3, 'Upgrade help', now(),"
                    " now() + interval '1 hour', 'email')",
                    uuid.uuid4(),
                    tenant,
                    f"sam-{tenant.hex[:8]}@vendor.test",
                )
    finally:
        await conn.close()
    return tenants


async def _mask_names_of(url: str, tenant: uuid.UUID) -> list[bool]:
    conn = await asyncpg.connect(url)
    try:
        # Superuser: the tenant is filtered by hand.
        rows = await conn.fetch(
            "SELECT mask_names FROM support_grants WHERE tenant_id = $1", tenant
        )
    finally:
        await conn.close()
    return [r["mask_names"] for r in rows]


async def _tick(url: str, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "UPDATE support_grants SET mask_names = true WHERE tenant_id = $1", tenant
        )
    finally:
        await conn.close()


def test_0188_keeps_names_visible_by_default_and_refuses_a_downgrade_that_would_unmask(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        tenants = asyncio.run(_three_tenants_with_grants(database.admin_url))
        assert not asyncio.run(_has_column(database.admin_url))
        db_testing.migrate(database.migrator_url, "0188")
        for tenant in tenants:  # D-180's default: names visible on every existing grant
            assert asyncio.run(_mask_names_of(database.admin_url, tenant)) == [False]
        db_testing.downgrade(database.migrator_url, BEFORE)  # no tick anywhere: allowed
        assert not asyncio.run(_has_column(database.admin_url))
        db_testing.migrate(database.migrator_url, "0188")
        # The middle tenant only: the refusal must find it in any tenant, not only the first.
        asyncio.run(_tick(database.admin_url, tenants[1]))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_column(database.admin_url))
        assert asyncio.run(_mask_names_of(database.admin_url, tenants[1])) == [True]
    finally:
        db_testing.destroy(db_config, database)
