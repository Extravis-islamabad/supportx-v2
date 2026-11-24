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
from tests.db.test_cmdb_merge_import import _fresh, _made, _merge
from tests.db.test_incidents_api import World
from tests.db.test_knowledge_api import _match

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


async def test_asset_owners_are_the_people_holding_them(world: World) -> None:
    a, b = world.a, world.b
    tag = uuid.uuid4().hex[:6]
    held = await _asset(world, f"Owner laptop {tag}")
    assert (await _hold(world, held, "user", a.tech_a)).status_code == 200
    # Held by something other than a person: fitted into another asset, or a department.
    host = await _asset(world, f"Host workstation {tag}")
    fitted = await _asset(world, f"Fitted laptop {tag}")
    assert (await _hold(world, fitted, "asset", host["id"])).status_code == 200
    department = await world.call(
        "POST", "/organization/departments", a, a.admin, json={"name": f"Owners {tag}"}
    )
    assert department.status_code == 201, department.text
    shared = await _asset(world, f"Department printer {tag}")
    assert (await _hold(world, shared, "department", department.json()["id"])).status_code == 200
    # A disposed asset still held by a person: its holder is still its owner (lane B's review).
    disposed = await _asset(world, f"Disposed laptop {tag}")
    assert (await _hold(world, disposed, "user", a.tech_c)).status_code == 200
    await world.sql(  # superuser: the tenant filtered by hand
        "UPDATE assets SET state_id = (SELECT id FROM asset_states"
        " WHERE tenant_id = $1 AND category = 'disposed' LIMIT 1)"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(disposed["id"]),
    )
    gone = await _asset(world, f"Gone laptop {tag}")
    assert (await _hold(world, gone, "user", a.tech_b)).status_code == 200
    await world.sql("UPDATE assets SET deleted_at = now() WHERE id = $1", uuid.UUID(gone["id"]))
    loose = await _asset(world, f"Loose laptop {tag}")
    ids = [uuid.UUID(x["id"]) for x in (held, fitted, shared, disposed, gone, loose)]

    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await assets.owners_of(session, ids) == {ids[0]: a.tech_a, ids[3]: a.tech_c}
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
    # Only managed by a group: never an owner (the negative control for "never managed_by").
    managed = (await _ci(world, a, f"Managed box {tag}", managed_by_group_id=str(a.ga))).json()
    gone = (await _ci(world, a, f"Gone box {tag}", owner_user_id=str(a.tech_a))).json()
    await world.sql("UPDATE cmdb_cis SET deleted_at = now() WHERE id = $1", uuid.UUID(gone["id"]))
    ids = [uuid.UUID(x["id"]) for x in (person, group_only, both, nobody, gone, managed)]

    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        found = await cmdb.owners_of(session, ids)
    assert found == {
        ids[0]: cmdb.Owner(user_id=a.tech_a, group_id=None),
        ids[1]: cmdb.Owner(user_id=None, group_id=a.ga),
        ids[2]: cmdb.Owner(user_id=a.tech_b, group_id=a.gb),
    }
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await cmdb.owners_of(session, ids) == {}


async def test_a_merged_ci_answers_with_its_survivors_owner(world: World) -> None:
    """Lane B's follow-up to S4b: a merged CI's ID gets the owner its survivor has now.

    Keyed by the ID asked for, following a chain of merges. A survivor with no owner gives
    nothing (the caller's fallback), and a merge undone by restoring the merged CI ends the
    alias: the restored CI answers with its own owner again.
    """
    a, b = world.a, world.b
    tag = uuid.uuid4().hex[:6]
    keep = await _made(
        world, a, f"Keep {tag}", owner_user_id=str(a.tech_b), owner_group_id=str(a.gb)
    )
    dupe = await _made(world, a, f"Dupe {tag}", owner_user_id=str(a.tech_a))
    middle = await _made(world, a, f"Middle {tag}", owner_group_id=str(a.ga))
    first = await _made(world, a, f"First {tag}", owner_user_id=str(a.tech_a))
    bare = await _made(world, a, f"Bare {tag}")
    owned = await _made(world, a, f"Owned {tag}", owner_user_id=str(a.tech_a))
    # The negative control: before any merge, each answers with its own owner.
    ids = {
        name: uuid.UUID(ci["id"])
        for name, ci in {
            "keep": keep,
            "dupe": dupe,
            "middle": middle,
            "first": first,
            "owned": owned,
        }.items()
    }
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        before = await cmdb.owners_of(session, [ids["dupe"], ids["first"]])
    assert before == {
        ids["dupe"]: cmdb.Owner(user_id=a.tech_a, group_id=None),
        ids["first"]: cmdb.Owner(user_id=a.tech_a, group_id=None),
    }

    assert (await _merge(world, a, keep, dupe)).status_code == 201
    # A chain: first into middle, then middle into keep.
    assert (await _merge(world, a, middle, first)).status_code == 201
    assert (
        await _merge(world, a, await _fresh(world, a, keep), await _fresh(world, a, middle))
    ).status_code == 201
    # A survivor kept without an owner (the merger chose its empty fields): the merged CI's
    # old owner never comes back through the alias.
    keep_empty = {"owner_user_id": "survivor", "owner_group_id": "survivor"}
    assert (await _merge(world, a, bare, owned, choices=keep_empty)).status_code == 201

    asked = [ids["dupe"], ids["first"], ids["middle"], ids["owned"], ids["keep"]]
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        after = await cmdb.owners_of(session, asked)
    now = cmdb.Owner(user_id=a.tech_b, group_id=a.gb)  # keep's own owner
    assert after == {ids["dupe"]: now, ids["first"]: now, ids["middle"]: now, ids["keep"]: now}
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await cmdb.owners_of(session, asked) == {}  # another tenant: nothing

    # Undo dupe's merge by restoring it: the alias ends and dupe answers for itself again.
    binned = await world.call("GET", "/cmdb/cis/trash", a, a.admin)
    version = next(c["version"] for c in binned.json()["items"] if c["id"] == dupe["id"])
    back = await world.call(
        "POST", f"/cmdb/cis/{dupe['id']}/restore", a, a.admin,
        params={"confirm_merged": "true"}, headers=_match(version),
    )  # fmt: skip
    assert back.status_code == 200, back.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        restored = await cmdb.owners_of(session, [ids["dupe"]])
    assert restored == {ids["dupe"]: cmdb.Owner(user_id=a.tech_a, group_id=None)}
