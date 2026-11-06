"""Who holds an asset and its holding history (WP-049a s4; REQ-AST-018, 019, 020; 0111).

The incident world: org A's admin holds everything; technicians hold assets.manage at group
scope. Org A has sites s1 and s2.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets.service.ownership import move_with_owner
from tests.db import test_incidents_api
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import World, field_codes, problem
from tests.db.test_knowledge_api import _match

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


async def _asset(world: World, name: str) -> dict[str, Any]:
    a = world.a
    product = await _product(world, a, "laptop", f"Holder {name}")
    made = await _add(world, a, {"name": name, "product_id": product})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _hold(world: World, asset: dict[str, Any], kind: str, holder: uuid.UUID | str) -> Any:  # noqa: ANN401 - httpx response
    a = world.a
    return await world.call(
        "PUT",
        f"{BASE}/{asset['id']}/holder",
        a,
        a.admin,
        json={"kind": kind, "id": str(holder)},
        headers=_match(asset["version"]),
    )


async def test_holdings_are_kept_from_person_to_person(world: World) -> None:
    """019 AC1/AC2: assigned to A, then B, then back: every holding with its dates."""
    a = world.a
    asset = await _asset(world, "Shared laptop")
    first = await _hold(world, asset, "user", a.tech_a)
    assert first.status_code == 200, first.text
    assert first.json()["owner_user_id"] == str(a.tech_a)
    second = await _hold(world, first.json(), "user", a.requester)
    assert second.json()["owner_user_id"] == str(a.requester)
    back = await world.call(
        "DELETE",
        f"{BASE}/{asset['id']}/holder",
        a,
        a.admin,
        headers=_match(second.json()["version"]),
    )
    assert back.status_code == 200, back.text
    assert back.json()["owner_user_id"] is None
    held = (await world.call("GET", f"{BASE}/{asset['id']}/holdings", a, a.admin)).json()
    assert [(h["holder_id"], h["ended_at"] is None) for h in held] == [
        (str(a.requester), False),
        (str(a.tech_a), False),
    ]
    # The person's page: what they held, and only now-held with `current`.
    past = await world.call(
        "GET", f"{BASE}/held-by", a, a.admin, params={"kind": "user", "id": str(a.tech_a)}
    )
    assert [h["asset"]["id"] for h in past.json()] == [asset["id"]]
    now = await world.call(
        "GET", f"{BASE}/held-by", a, a.admin,
        params={"kind": "user", "id": str(a.tech_a), "current": "true"},
    )  # fmt: skip
    assert now.json() == []
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action IN ('asset.assigned', 'asset.unassigned') AND outcome = 'done'",
        a.tenant,
    )
    assert audit[0]["n"] == 3
    stale = await _hold(world, asset, "user", a.tech_b)  # the first version read, long gone
    assert problem(stale) == (409, "version_conflict")


async def test_an_asset_is_never_fitted_inside_itself(world: World) -> None:
    """018 AC1/AC3: a monitor on a workstation; never the workstation on its own monitor."""
    workstation = await _asset(world, "Workstation")
    monitor = await _asset(world, "Monitor")
    fitted = await _hold(world, monitor, "asset", workstation["id"])
    assert fitted.status_code == 200, fitted.text
    assert fitted.json()["parent_asset_id"] == workstation["id"]
    inside = await _hold(world, workstation, "asset", monitor["id"])
    assert field_codes(inside) == {"holder_id": "asset_nested_in_itself"}
    itself = await _hold(world, workstation, "asset", workstation["id"])
    assert field_codes(itself) == {"holder_id": "asset_nested_in_itself"}


async def test_holders_must_exist_in_this_organisation(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, "Checked holder")
    assert field_codes(await _hold(world, asset, "user", uuid.uuid4())) == {
        "holder_id": "asset_holder_not_found"
    }
    # Another tenant's person is no one here.
    assert field_codes(await _hold(world, asset, "user", b.tech_a)) == {
        "holder_id": "asset_holder_not_found"
    }
    assert field_codes(await _hold(world, asset, "department", uuid.uuid4())) == {
        "holder_id": "asset_holder_not_found"
    }
    assert (await world.call("GET", f"{BASE}/{asset['id']}", a, a.admin)).json()["version"] == (
        asset["version"]
    )


async def test_assets_follow_their_owner_to_another_site(world: World) -> None:
    """018 AC2: with "follow owner's site" on, a person's move moves their assets, with history."""
    a = world.a
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    on = await world.call(
        "PATCH", f"{BASE}/settings", a, a.admin, json={"site_follows_owner": True},
        headers=_match(settings["version"]),
    )  # fmt: skip
    assert on.status_code == 200, on.text
    asset = await _asset(world, "Follows Rana")
    # The person's own site (their profile's), not the sites they have access to.
    await world.sql(
        "UPDATE users SET site_id = $1 WHERE tenant_id = $2 AND id = $3",
        a.s1,
        a.tenant,
        a.requester,
    )
    held = await _hold(world, asset, "user", a.requester)
    assert held.json()["site_id"] == str(a.s1)  # the person's own site, taken on assignment
    await world.sql(
        "UPDATE users SET site_id = $1 WHERE tenant_id = $2 AND id = $3",
        a.s2,
        a.tenant,
        a.requester,
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await move_with_owner(session, a.requester) == 1
        assert await move_with_owner(session, a.requester) == 0  # a second delivery: nothing left
    now = (await world.call("GET", f"{BASE}/{asset['id']}", a, a.admin)).json()
    assert now["site_id"] == str(a.s2)
    history = (await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.admin)).json()
    latest = history["items"][0]
    assert [c["field"] for c in latest["changes"]] == ["site_id"]


async def test_holdings_and_relationships_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, "Only A holds")
    assert (await _hold(world, asset, "user", a.tech_a)).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("asset_assignments", "asset_relationships"):
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        assert (
            await session.execute(text("UPDATE asset_assignments SET source = 'x'"))
        ).rowcount == 0
    assert problem(await world.call("GET", f"{BASE}/{asset['id']}/holdings", b, b.admin)) == (
        404,
        "asset_not_found",
    )
