"""The site map and known devices are isolated per tenant (WP-057 S2b-1, migration 0157; rule 5a).

Real PostgreSQL as the application role: tenant A's rows are invisible to tenant B, which can
neither change nor delete them, nor write rows for tenant A.
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

TABLES = ("site_networks", "known_devices")


async def _seed(world: World) -> None:
    """One mapped range and one known device in tenant A."""
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await session.execute(
            text(
                "INSERT INTO site_networks (tenant_id, id, network, site_id) "
                "VALUES (:t, :i, CAST(:n AS cidr), :s) ON CONFLICT DO NOTHING"
            ),
            {"t": world.a.tenant, "i": uuid.uuid4(), "n": "10.1.0.0/16", "s": world.a.s1},
        )
        await session.execute(
            text(
                "INSERT INTO known_devices (tenant_id, id, user_id, fingerprint, last_seen_at) "
                "VALUES (:t, :i, :u, :f, now())"
            ),
            {"t": world.a.tenant, "i": uuid.uuid4(), "u": world.a.tech_a, "f": os.urandom(32)},
        )


@pytest.mark.parametrize("table", TABLES)
async def test_tenant_b_neither_sees_nor_changes_tenant_as_rows(world: World, table: str) -> None:
    a, b = world.a, world.b
    await _seed(world)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() > 0  # noqa: S608 - fixed table names
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text(f"UPDATE {table} SET updated_at = now() WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
        deleted = await session.execute(
            text(f"DELETE FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert deleted.rowcount == 0


async def test_tenant_b_cannot_write_rows_for_tenant_a(world: World) -> None:
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO site_networks (tenant_id, id, network, site_id) "
                    "VALUES (:t, :i, CAST('10.9.0.0/16' AS cidr), :s)"
                ),
                {"t": world.a.tenant, "i": uuid.uuid4(), "s": world.a.s1},
            )
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO known_devices (tenant_id, id, user_id, fingerprint, last_seen_at) "
                    "VALUES (:t, :i, :u, :f, now())"
                ),
                {"t": world.a.tenant, "i": uuid.uuid4(), "u": world.a.tech_a, "f": os.urandom(32)},
            )


async def test_a_range_cannot_point_at_another_tenants_site(world: World) -> None:
    """The composite key keeps a mapping inside its tenant, whatever the caller sends."""
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO site_networks (tenant_id, id, network, site_id) "
                    "VALUES (:t, :i, CAST('10.8.0.0/16' AS cidr), :s)"
                ),
                {"t": world.b.tenant, "i": uuid.uuid4(), "s": world.a.s1},
            )


async def test_a_fingerprint_is_exactly_32_bytes(world: World) -> None:
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO known_devices (tenant_id, id, user_id, fingerprint, last_seen_at) "
                    "VALUES (:t, :i, :u, :f, now())"
                ),
                {"t": world.a.tenant, "i": uuid.uuid4(), "u": world.a.tech_a, "f": b"short"},
            )
