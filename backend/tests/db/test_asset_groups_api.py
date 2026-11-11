"""Static and dynamic asset groups (WP-049a s4; REQ-AST-028; migration 0113)."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db import test_incidents_api
from tests.db.test_asset_holders_api import _asset
from tests.db.test_incidents_api import World, problem
from tests.db.test_knowledge_api import _match

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

GROUPS = "/assets/groups"


async def _group(world: World, body: dict[str, Any]) -> Any:  # noqa: ANN401 - httpx response
    a = world.a
    return await world.call(
        "POST", GROUPS, a, a.admin, json=body, headers={"Idempotency-Key": str(uuid.uuid4())}
    )


async def test_a_dynamic_group_gains_an_asset_when_it_comes_to_match(world: World) -> None:
    """AC1/AC3: membership follows the filter; the count matches the list."""
    a = world.a
    asset = await _asset(world, "Warranty laptop")
    made = await _group(
        world,
        {
            "name": "Warranty ends 2027",
            "kind": "dynamic",
            "filter": {"field": "warranty_expires_on", "op": "eq", "value": "2027-03-31"},
        },
    )
    assert made.status_code == 201, made.text
    group = made.json()
    assert group["count"] == 0
    changed = await world.call(
        "PATCH", f"/assets/{asset['id']}", a, a.admin,
        json={"warranty_expires_on": "2027-03-31"}, headers=_match(asset["version"]),
    )  # fmt: skip
    assert changed.status_code == 200, changed.text
    listed = (await world.call("GET", GROUPS, a, a.tech_a)).json()
    mine = next(g for g in listed if g["id"] == group["id"])
    members = (await world.call("GET", f"{GROUPS}/{group['id']}/assets", a, a.tech_a)).json()
    assert mine["count"] == len(members) == 1
    assert members[0]["id"] == asset["id"]
    # A bad filter is refused when saved, with its path.
    bad = await _group(
        world,
        {"name": "Broken", "kind": "dynamic", "filter": {"field": "nope", "op": "eq", "value": 1}},
    )
    assert problem(bad)[0] == 422


async def test_a_static_group_is_filled_from_a_selection_in_one_step(world: World) -> None:
    """AC2: one call adds the selection; adding again changes nothing; one leaves."""
    a = world.a
    one, two = await _asset(world, "Static one"), await _asset(world, "Static two")
    group = (await _group(world, {"name": "Floor 3", "kind": "static"})).json()
    added = await world.call(
        "POST", f"{GROUPS}/{group['id']}/members", a, a.admin,
        json={"asset_ids": [one["id"], two["id"], one["id"]]},
    )  # fmt: skip
    assert added.json() == {"added": 2}
    again = await world.call(
        "POST", f"{GROUPS}/{group['id']}/members", a, a.admin, json={"asset_ids": [one["id"]]}
    )
    assert again.json() == {"added": 0}
    gone = await world.call("DELETE", f"{GROUPS}/{group['id']}/members/{two['id']}", a, a.admin)
    assert gone.status_code == 204
    members = (await world.call("GET", f"{GROUPS}/{group['id']}/assets", a, a.admin)).json()
    assert [m["id"] for m in members] == [one["id"]]
    assert problem(await _group(world, {"name": "floor 3", "kind": "static"})) == (
        409,
        "asset_group_name_taken",
    )
    # Without assets.view (a requester): no groups at all.
    assert problem(await world.call("GET", GROUPS, a, a.requester))[0] == 403


async def test_asset_groups_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, "RLS member")
    group = (await _group(world, {"name": "Only A", "kind": "static"})).json()
    await world.call(
        "POST", f"{GROUPS}/{group['id']}/members", a, a.admin, json={"asset_ids": [asset["id"]]}
    )
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("asset_groups", "asset_group_members"):
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        assert (await session.execute(text("UPDATE asset_groups SET name = 'x'"))).rowcount == 0
    assert (await world.call("GET", GROUPS, b, b.admin)).json() == []
    assert problem(await world.call("GET", f"{GROUPS}/{group['id']}/assets", b, b.admin)) == (
        404,
        "asset_group_not_found",
    )
