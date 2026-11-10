"""An asset's state moves along its life cycle (WP-049a s3; REQ-AST-002 AC2, 012, 013).

The incident world: org A's admin holds everything; technicians hold assets.manage at group
scope (unsited assets are within it) but not assets.reinstate.
"""

import uuid
from typing import Any

import pytest

from tests.db import test_incidents_api
from tests.db.test_assets_api import _add, _product, asset_manager
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


async def _states(world: World, org: Org) -> dict[str, str]:
    found = await world.call("GET", f"{BASE}/states", org, org.admin)
    return {s["code"]: s["id"] for s in found.json()}


async def _move(
    world: World,
    org: Org,
    asset: dict[str, Any],
    to: str,
    reason: str | None = None,
    user: uuid.UUID | None = None,
) -> Any:  # noqa: ANN401 - httpx response
    body: dict[str, Any] = {"to_state_id": to}
    if reason is not None:
        body["reason"] = reason
    return await world.call(
        "POST",
        f"{BASE}/{asset['id']}/move",
        org,
        user or org.admin,
        json=body,
        headers=_match(asset["version"]),
    )


async def test_moves_follow_the_life_cycle_and_ask_for_reasons(world: World) -> None:
    a = world.a
    states = await _states(world, a)
    laptop = await _product(world, a, "laptop", "T14")
    asset = (await _add(world, a, {"name": "Moving", "product_id": laptop})).json()
    options = await world.call("GET", f"{BASE}/{asset['id']}/moves", a, a.admin)
    assert options.status_code == 200, options.text
    targets = {o["to_state_id"] for o in options.json()}
    assert targets == {states[c] for c in ("in_use", "on_loan", "in_repair", "missing", "retired")}
    # Not on the life cycle: refused, nothing changes.
    refused = await _move(world, a, asset, states["disposed"])
    assert problem(refused) == (409, "asset_move_not_allowed")
    # The repair state asks for a reason.
    no_reason = await _move(world, a, asset, states["in_repair"])
    assert field_codes(no_reason) == {"reason": "required"}
    moved = await _move(world, a, asset, states["in_repair"], "Screen cracked")
    assert moved.status_code == 200, moved.text
    assert moved.json()["state_id"] == states["in_repair"]
    stale = await _move(world, a, asset, states["in_stock"])
    assert problem(stale) == (409, "version_conflict")
    history = await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.tech_a)
    latest = history.json()["items"][0]
    assert latest["reason"] == "Screen cracked"
    assert [c["field"] for c in latest["changes"]] == ["state_id"]
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = 'asset.moved'"
        " AND outcome = 'done'",
        a.tenant,
    )
    assert audit[0]["n"] == 1


async def test_bringing_back_a_retired_asset_needs_its_permission(world: World) -> None:
    a = world.a
    await asset_manager(world, a, a.tech_a)  # manages assets, never assets.reinstate (D-153)
    states = await _states(world, a)
    laptop = await _product(world, a, "laptop", "Retiring")
    asset = (await _add(world, a, {"name": "Old one", "product_id": laptop}, a.tech_a)).json()
    asset = (await _move(world, a, asset, states["retired"], "End of life", a.tech_a)).json()
    options = await world.call("GET", f"{BASE}/{asset['id']}/moves", a, a.tech_a)
    back = next(o for o in options.json() if o["to_state_id"] == states["in_stock"])
    assert back["allowed"] is False  # shown, not offered: the asset manager lacks reinstate
    refused = await _move(world, a, asset, states["in_stock"], user=a.tech_a)
    assert problem(refused)[0] == 403
    assert (await _move(world, a, asset, states["in_stock"])).status_code == 200


async def test_disposing_frees_the_slot_of_an_it_asset(world: World) -> None:
    a = world.a
    await world.sql(
        "UPDATE tenant_subscriptions SET limits = '{\"assets\": 1}'::jsonb WHERE tenant_id = $1",
        a.tenant,
    )
    await world.app.state.entitlements.invalidate(a.tenant)  # the plan changed under it
    states = await _states(world, a)
    laptop = await _product(world, a, "laptop", "Slot")
    asset = (await _add(world, a, {"name": "Only slot", "product_id": laptop})).json()
    assert problem(await _add(world, a, {"name": "Second", "product_id": laptop})) == (
        403,
        "asset_limit_reached",
    )
    asset = (await _move(world, a, asset, states["retired"], "Worn out")).json()
    asset = (await _move(world, a, asset, states["disposed"], "Recycled")).json()
    assert asset["state_id"] == states["disposed"]
    assert (await _add(world, a, {"name": "Second", "product_id": laptop})).status_code == 201


async def test_copies_get_new_tags_no_serials_and_start_in_stock(world: World) -> None:
    a = world.a
    states = await _states(world, a)
    laptop = await _product(world, a, "laptop", "Copied")
    original = (
        await _add(
            world,
            a,
            {
                "name": "Golden image",
                "product_id": laptop,
                "serial_number": "SN-COPY",
                "barcode": "B1",
            },
        )
    ).json()
    original = (await _move(world, a, original, states["in_use"])).json()
    made = await world.call(
        "POST", f"{BASE}/{original['id']}/copy", a, a.admin, json={"count": 5}, headers=_new()
    )
    assert made.status_code == 201, made.text
    copies = made.json()["items"]
    assert len(copies) == 5
    assert len({c["tag"] for c in copies} | {original["tag"]}) == 6
    for copy in copies:
        assert copy["name"] == "Golden image"
        assert copy["serial_number"] is None
        assert copy["barcode"] is None
        assert copy["state_id"] == states["in_stock"]
    history = await world.call("GET", f"{BASE}/{copies[0]['id']}/history", a, a.admin)
    fields = {c["field"]: c["new"] for c in history.json()["items"][-1]["changes"]}
    assert fields["copied_from"] == original["id"]
    too_many = await world.call(
        "POST", f"{BASE}/{original['id']}/copy", a, a.admin, json={"count": 51}, headers=_new()
    )
    assert problem(too_many) == (409, "asset_copy_limit")
    assert too_many.json()["params"] == {"max": 50}


async def test_a_bulk_move_reports_each_asset(world: World) -> None:
    a = world.a
    states = await _states(world, a)
    laptop = await _product(world, a, "laptop", "Bulk")
    one = (await _add(world, a, {"name": "One", "product_id": laptop})).json()
    two = (await _add(world, a, {"name": "Two", "product_id": laptop})).json()
    stale = (await _add(world, a, {"name": "Stale", "product_id": laptop})).json()
    await _move(world, a, stale, states["in_use"])  # its version moved on
    moved = await world.call(
        "POST",
        f"{BASE}/bulk-moves",
        a,
        a.admin,
        json={
            "items": [
                {"asset_id": one["id"], "version": one["version"]},
                {"asset_id": two["id"], "version": two["version"]},
                {"asset_id": stale["id"], "version": stale["version"]},
            ],
            "to_state_id": states["in_repair"],
            "reason": "Batch fault",
        },
    )
    assert moved.status_code == 200, moved.text
    results = {r["asset_id"]: r for r in moved.json()}
    assert results[one["id"]]["moved"] is True
    assert results[two["id"]]["moved"] is True
    assert results[stale["id"]] == {
        "asset_id": stale["id"], "moved": False, "code": "version_conflict", "version": None
    }  # fmt: skip
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = 'asset.moved'",
        a.tenant,
    )
    assert audit[0]["n"] >= 3  # the earlier single move, plus one per moved asset
