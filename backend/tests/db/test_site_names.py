"""`organization.site_names` (polish 8; lane C's new-device notice names a mapped site).

Read only and tenant-scoped (RLS): another tenant's site is never named, an unknown ID is absent,
and a removed site keeps its name for what happened there before.
"""

import uuid

from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.organization import site_names
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


async def test_site_names_are_the_tenants_own_and_survive_removal(world: World) -> None:
    a, b = world.a, world.b
    unknown = uuid.uuid4()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        mine = await site_names(session, [a.s1, unknown])
        assert set(mine) == {a.s1}
        assert mine[a.s1]
        assert await site_names(session, []) == {}
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await site_names(session, [a.s1]) == {}  # another tenant's site: never named
    removed = uuid.uuid4()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await session.execute(
            text("INSERT INTO sites (tenant_id, id, name, deleted_at) VALUES (:t, :i, :n, now())"),
            {"t": a.tenant, "i": removed, "n": f"Closed office {removed.hex[:6]}"},
        )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await site_names(session, [removed]))[removed].startswith("Closed office")
