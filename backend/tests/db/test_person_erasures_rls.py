"""Person erasures are isolated per tenant (D-171, migration 0161; rule 5a).

Real PostgreSQL as the application role: tenant A's erasure is invisible to tenant B, which can
neither change it nor write one for tenant A, nor point one at tenant A's people. The app may
not delete an erasure (it is the record that one happened).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

INSERT = text(
    "INSERT INTO person_erasures (tenant_id, id, person_id, reason_code, successor_id,"
    " requested_by, requested_at, expires_at)"
    " VALUES (:t, :i, :p, 'subject_request', :s, :r, :at, :until)"
)


def _values(tenant: uuid.UUID, org: Org) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "t": tenant,
        "i": uuid.uuid4(),
        "p": org.requester,
        "s": org.lead,
        "r": org.admin,
        "at": now,
        "until": now + timedelta(days=7),
    }


async def test_tenant_b_neither_sees_nor_changes_tenant_as_erasures(world: World) -> None:
    a, b = world.a, world.b
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await session.execute(INSERT, _values(a.tenant, a))
        assert (await session.execute(text("SELECT count(*) FROM person_erasures"))).scalar_one()
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text("SELECT count(*) FROM person_erasures WHERE tenant_id = :a"), {"a": a.tenant}
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text("UPDATE person_erasures SET state = 'rejected' WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    rows = await world.sql(
        "SELECT state FROM person_erasures WHERE tenant_id = $1 AND person_id = $2",
        a.tenant,
        a.requester,
    )
    assert [row["state"] for row in rows] == ["requested"]


async def test_tenant_b_cannot_write_an_erasure_for_tenant_a(world: World) -> None:
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(INSERT, _values(world.a.tenant, world.a))


async def test_an_erasure_cannot_name_another_tenants_person(world: World) -> None:
    """The composite keys keep the person, successor and requester inside the tenant."""
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(INSERT, _values(world.b.tenant, world.a))


async def test_the_app_cannot_delete_an_erasure(world: World) -> None:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await session.execute(INSERT, _values(a.tenant, a))
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            await session.execute(text("DELETE FROM person_erasures"))


async def test_one_open_erasure_per_person_and_four_eyes(world: World) -> None:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await session.execute(INSERT, _values(a.tenant, a))
    with pytest.raises(DBAPIError):  # a second open one for the same person
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            await session.execute(INSERT, _values(a.tenant, a))
    with pytest.raises(DBAPIError):  # the approver is never the requester
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            await session.execute(
                text("UPDATE person_erasures SET approved_by = requested_by, state = 'approved'")
            )
