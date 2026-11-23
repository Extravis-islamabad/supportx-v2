"""The asset and CI owner lookups a request stage uses for its approvers (WP-047a S2a).

Lane B's notes on the ports (2026-11-23): an asset's owner is the person holding it, never a
department or another asset; a CI's owner is its owner person and owner group, never
`managed_by`; one query each; deleted rows never count; another tenant's IDs give nothing.
"""

import uuid

import pytest

from app.core.tenancy import TenantContext
from app.modules import assets, cmdb
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_holders_api import _asset, _hold
from tests.db.test_cmdb_api import _ci
from tests.db.test_incidents_api import World

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


async def test_asset_owners_are_the_people_holding_them(world: World) -> None:
    a, b = world.a, world.b
    tag = uuid.uuid4().hex[:6]
    held = await _asset(world, f"Owner laptop {tag}")
    assert (await _hold(world, held, "user", a.tech_a)).status_code == 200
    # Held by something other than a person (fitted into another asset): no owner.
    host = await _asset(world, f"Host workstation {tag}")
    by_group = await _asset(world, f"Fitted laptop {tag}")
    assert (await _hold(world, by_group, "asset", host["id"])).status_code == 200
    gone = await _asset(world, f"Gone laptop {tag}")
    assert (await _hold(world, gone, "user", a.tech_b)).status_code == 200
    await world.sql("UPDATE assets SET deleted_at = now() WHERE id = $1", uuid.UUID(gone["id"]))
    loose = await _asset(world, f"Loose laptop {tag}")
    ids = [uuid.UUID(x["id"]) for x in (held, by_group, gone, loose)]

    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await assets.owners_of(session, ids) == {ids[0]: a.tech_a}
        assert await assets.owners_of(session, []) == {}
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await assets.owners_of(session, ids) == {}  # tenant A's assets: nothing


async def test_ci_owners_are_the_owner_person_and_group(world: World) -> None:
    a, b = world.a, world.b
    tag = uuid.uuid4().hex[:6]
    person = (await _ci(world, a, f"Owned box {tag}", owner_user_id=str(a.tech_a))).json()
    group_only = (await _ci(world, a, f"Group box {tag}", owner_group_id=str(a.ga))).json()
    both = (
        await _ci(
            world, a, f"Both box {tag}", owner_user_id=str(a.tech_b), owner_group_id=str(a.gb)
        )
    ).json()
    nobody = (await _ci(world, a, f"Unowned box {tag}")).json()
    gone = (await _ci(world, a, f"Gone box {tag}", owner_user_id=str(a.tech_a))).json()
    await world.sql("UPDATE cmdb_cis SET deleted_at = now() WHERE id = $1", uuid.UUID(gone["id"]))
    ids = [uuid.UUID(x["id"]) for x in (person, group_only, both, nobody, gone)]

    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        found = await cmdb.owners_of(session, ids)
    assert found == {
        ids[0]: cmdb.Owner(user_id=a.tech_a, group_id=None),
        ids[1]: cmdb.Owner(user_id=None, group_id=a.ga),
        ids[2]: cmdb.Owner(user_id=a.tech_b, group_id=a.gb),
    }
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await cmdb.owners_of(session, ids) == {}
