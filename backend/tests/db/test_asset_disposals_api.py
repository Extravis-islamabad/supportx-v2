"""Disposing of an asset with a record (WP-049a s3; REQ-AST-017, migration 0108).

The incident world: org A's admin holds everything; technicians hold assets.manage at group
scope, not assets.edit_disposed.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets import register_disposal_guard, unregister_disposal_guard
from tests.db import test_incidents_api
from tests.db.test_asset_moves_api import _move, _states
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import World, field_codes, problem
from tests.db.test_knowledge_api import _match

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"
RECORD = {"disposed_on": "2026-11-01", "method": "recycling", "reason": "End of life"}


async def _retired(world: World, name: str) -> dict[str, Any]:
    a = world.a
    states = await _states(world, a)
    laptop = await _product(world, a, "laptop", f"Disposal {name}")
    asset = (await _add(world, a, {"name": name, "product_id": laptop})).json()
    moved = await _move(world, a, asset, states["retired"], "Worn out")
    assert moved.status_code == 200, moved.text
    return dict(moved.json())


async def _dispose(
    world: World, asset: dict[str, Any], body: dict[str, Any], user: uuid.UUID | None = None
) -> Any:  # noqa: ANN401 - httpx response
    a = world.a
    return await world.call(
        "POST",
        f"{BASE}/{asset['id']}/dispose",
        a,
        user or a.admin,
        json=body,
        headers=_match(asset["version"]),
    )


async def test_disposing_records_how_and_moves_the_asset_in_one_step(world: World) -> None:
    a = world.a
    states = await _states(world, a)
    asset = await _retired(world, "Old laptop")
    done = await _dispose(
        world, asset, {**RECORD, "cost": "12.50", "currency": "PKR", "approved_by": str(a.admin)}
    )
    assert done.status_code == 200, done.text
    record = done.json()
    assert (record["method"], record["cost"], record["approved_by"]) == (
        "recycling",
        "12.50",
        str(a.admin),
    )
    assert done.headers["ETag"] == f'"{asset["version"] + 1}"'
    now = (await world.call("GET", f"{BASE}/{asset['id']}", a, a.tech_a)).json()
    assert now["state_id"] == states["disposed"]
    read = await world.call("GET", f"{BASE}/{asset['id']}/disposal", a, a.tech_a)
    assert read.status_code == 200
    assert read.json()["id"] == record["id"]
    history = (await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.admin)).json()
    assert history["items"][0]["reason"] == "End of life"
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = 'asset.disposed'"
        " AND outcome = 'done'",
        a.tenant,
    )
    assert audit[0]["n"] == 1
    # Once only: a second record is refused, whatever the version.
    again = await _dispose(world, {**asset, "version": asset["version"] + 1}, RECORD)
    assert problem(again) == (409, "asset_already_disposed")


async def test_the_record_is_checked_field_by_field(world: World) -> None:
    asset = await _retired(world, "Checked")
    refused = await _dispose(
        world,
        asset,
        {"disposed_on": "2999-01-01", "method": "recycling", "reason": "x", "cost": "5"},
    )
    assert field_codes(refused) == {"disposed_on": "date_in_future", "currency": "required"}
    bad_method = await _dispose(world, asset, {**RECORD, "method": "burned"})
    assert bad_method.status_code == 422
    nobody = await _dispose(world, asset, {**RECORD, "approved_by": str(uuid.uuid4())})
    assert field_codes(nobody) == {"approved_by": "approver_not_active"}


async def test_only_the_life_cycle_s_way_in_and_the_version_read(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "Straight")
    in_stock = (await _add(world, a, {"name": "Never retired", "product_id": laptop})).json()
    # The seeded life cycle reaches disposed only from retired.
    assert problem(await _dispose(world, in_stock, RECORD)) == (409, "asset_move_not_allowed")
    asset = await _retired(world, "Stale")
    stale = await _dispose(world, {**asset, "version": asset["version"] - 1}, RECORD)
    assert problem(stale) == (409, "version_conflict")
    assert problem(await world.call("GET", f"{BASE}/{asset['id']}/disposal", a, a.admin)) == (
        404,
        "asset_disposal_not_found",
    )


async def test_what_still_holds_the_asset_refuses_the_disposal(world: World) -> None:
    """AC1: an open loan (registered by loans in session 5) refuses until it is closed."""
    asset = await _retired(world, "On loan")

    async def on_loan(_session: object, asset_id: uuid.UUID) -> str | None:
        return "asset_on_loan" if str(asset_id) == asset["id"] else None

    register_disposal_guard(on_loan)
    try:
        assert problem(await _dispose(world, asset, RECORD)) == (409, "asset_on_loan")
    finally:
        unregister_disposal_guard(on_loan)
    assert (await _dispose(world, asset, RECORD)).status_code == 200


async def test_a_disposed_asset_is_read_only_without_its_permission(world: World) -> None:
    """AC3: only assets.edit_disposed changes it, and every change asks for a reason."""
    a = world.a
    asset = await _retired(world, "Read only")
    done = await _dispose(world, asset, RECORD)
    version = asset["version"] + 1
    by_tech = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.tech_a, json={"location": "Store"},
        headers=_match(version),
    )  # fmt: skip
    assert problem(by_tech) == (403, "asset_disposed_read_only")
    no_reason = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.admin, json={"location": "Store"},
        headers=_match(version),
    )  # fmt: skip
    assert field_codes(no_reason) == {"reason": "required"}
    fixed = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.admin,
        json={"location": "Store", "reason": "Corrected the record"}, headers=_match(version),
    )  # fmt: skip
    assert fixed.status_code == 200, fixed.text
    assert done.status_code == 200
    history = (await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.admin)).json()
    assert history["items"][0]["reason"] == "Corrected the record"


async def test_disposal_records_are_isolated_by_rls(world: World) -> None:
    b = world.b
    asset = await _retired(world, "Only A")
    assert (await _dispose(world, asset, RECORD)).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM asset_disposals")) == 0
        assert (
            await session.execute(text("UPDATE asset_disposals SET reason = 'x'"))
        ).rowcount == 0
    assert problem(await world.call("GET", f"{BASE}/{asset['id']}/disposal", b, b.admin)) == (
        404,
        "asset_not_found",
    )


async def test_disposing_asks_about_fitted_components_first(world: World) -> None:
    """026 AC2: a workstation's monitor is detached or disposed of with it, never left hanging."""
    a = world.a
    states = await _states(world, a)
    workstation = await _retired(world, "Old workstation")
    monitor = await _retired(world, "Its monitor")
    fitted = await world.call(
        "PUT", f"{BASE}/{monitor['id']}/holder", a, a.admin,
        json={"kind": "asset", "id": workstation["id"]}, headers=_match(monitor["version"]),
    )  # fmt: skip
    assert fitted.status_code == 200, fitted.text
    asked = await _dispose(world, workstation, RECORD)
    assert problem(asked) == (409, "asset_has_components")
    assert asked.json()["params"] == {"count": 1}
    detached = await _dispose(world, workstation, {**RECORD, "components": "detach"})
    assert detached.status_code == 200, detached.text
    after = (await world.call("GET", f"{BASE}/{monitor['id']}", a, a.admin)).json()
    assert after["parent_asset_id"] is None
    assert after["state_id"] == states["retired"]  # only detached, still its own asset

    rack = await _retired(world, "Old rack")
    shelf = await _retired(world, "Its shelf")
    put = await world.call(
        "PUT", f"{BASE}/{shelf['id']}/holder", a, a.admin,
        json={"kind": "asset", "id": rack["id"]}, headers=_match(shelf["version"]),
    )  # fmt: skip
    assert put.status_code == 200
    both = await _dispose(world, rack, {**RECORD, "components": "dispose"})
    assert both.status_code == 200, both.text
    gone = (await world.call("GET", f"{BASE}/{shelf['id']}", a, a.admin)).json()
    assert gone["state_id"] == states["disposed"]
    record = await world.call("GET", f"{BASE}/{shelf['id']}/disposal", a, a.admin)
    assert record.json()["reason"] == RECORD["reason"]
