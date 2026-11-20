"""Staff booking writes and CIs from assets never reach past the caller's asset scope (2026-11-20).

Found by lane B's write walk (#560) and confirmed on main by lane C's own re-check, whose cases
these are:
- an S2-only asset manager could cancel an S1 booking by its ID (200) and reach a hand-over's
  version check (409 naming who changed it); both now answer the same 404 as an unknown booking,
  with the manage scope checked before the version and the status;
- `POST /cmdb/cis/from-assets` skipped an unseen asset as "hidden" and a nonexistent one as
  "gone", confirming the unseen one exists; both now read the same.

The manager views assets everywhere (the built-in technician role) but manages only S2: the
booking writes follow the manage scope, the right they need. Real PostgreSQL and Valkey on the
incident world; every record is new (rule 5h).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_loans_api import _loanable
from tests.db.test_assets_api import _add, _product
from tests.db.test_cmdb_api import _types
from tests.db.test_incidents_api import World, problem, role
from tests.db.test_knowledge_api import _match

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

TAG = "QA-2026-11-20"


async def _asset_at(world: World, name: str, site: uuid.UUID) -> dict[str, Any]:
    a = world.a
    product = await _product(world, a, "laptop", f"{TAG} {name} {uuid.uuid4().hex[:6]}")
    made = await _add(
        world, a, {"name": f"{TAG} {name}", "product_id": product, "site_id": str(site)}
    )
    assert made.status_code == 201, made.text
    asset = dict(made.json())
    await _loanable(world, asset)
    return asset


async def _booking(world: World, asset: dict[str, Any]) -> dict[str, Any]:
    a = world.a
    starts = datetime.now(UTC) - timedelta(minutes=5)
    made = await world.call(
        "POST", "/assets/bookings", a, a.admin,
        json={
            "asset_id": asset["id"], "borrower_id": str(a.requester),
            "starts_at": starts.isoformat(), "ends_at": (starts + timedelta(days=2)).isoformat(),
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_a_booking_outside_the_managers_sites_reads_as_none(world: World) -> None:
    a = world.a
    manager = await role(
        world, a, f"{TAG} S2 asset manager", [("assets.view", "site"), ("assets.manage", "site")]
    )
    assigned = await world.call("PUT", f"/users/{a.tech_b}/roles/{manager}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    try:
        out_of_scope = await _booking(world, await _asset_at(world, "S1 projector", a.s1))
        in_scope = await _booking(world, await _asset_at(world, "S2 projector", a.s2))
        bid, version = out_of_scope["id"], out_of_scope["version"]
        for path, if_match in (
            (f"/assets/bookings/{bid}/handover", version),
            (f"/assets/bookings/{bid}/handover", version + 5),  # stale: still 404, never 409
            (f"/assets/bookings/{bid}/cancel", version),
            (f"/assets/bookings/{bid}/cancel", version + 5),
        ):
            refused = await world.call("POST", path, a, a.tech_b, headers=_match(if_match))
            assert problem(refused) == (404, "asset_booking_not_found"), (path, refused.text)
        still = await world.call("GET", f"/assets/bookings?asset_id={out_of_scope['asset_id']}",
                                 a, a.admin)  # fmt: skip
        assert still.status_code == 200, still.text
        assert {b["status"] for b in still.json() if b["id"] == bid} == {"booked"}  # untouched
        own = await world.call(
            "POST", f"/assets/bookings/{in_scope['id']}/cancel", a, a.tech_b,
            headers=_match(in_scope["version"]),
        )  # fmt: skip
        assert own.status_code == 200, own.text  # the control: within the manage scope
        nothing = await world.call(
            "POST", f"/assets/bookings/{uuid.uuid4()}/cancel", a, a.tech_b, headers=_match(1)
        )
        assert problem(nothing) == (404, "asset_booking_not_found")  # the control: no booking
    finally:
        await world.call("DELETE", f"/users/{a.tech_b}/roles/{manager}", a, a.admin)


async def test_cis_from_assets_never_tells_an_unseen_asset_from_none(world: World) -> None:
    a = world.a
    adder = await role(
        world,
        a,
        f"{TAG} CI adder, S2 assets",
        [("cmdb.view", "all"), ("cmdb.add", "all"), ("assets.view", "site")],
    )
    assigned = await world.call("PUT", f"/users/{a.requester2}/roles/{adder}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    try:
        unseen = await _asset_at(world, "S1 server", a.s1)
        hidden = await world.call("GET", f"/assets/{unseen['id']}", a, a.requester2)
        assert hidden.status_code == 404, hidden.text
        nowhere = str(uuid.uuid4())
        made = await world.call(
            "POST", "/cmdb/cis/from-assets", a, a.requester2,
            json={"asset_ids": [unseen["id"], nowhere],
                  "type_id": (await _types(world, a))["server"]["id"]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )  # fmt: skip
        assert made.status_code == 201, made.text
        reasons = {s["asset_id"]: s["reason"] for s in made.json()["skipped"]}
        assert reasons == {unseen["id"]: "hidden", nowhere: "hidden"}
        assert made.json()["created"] == []
    finally:
        await world.call("DELETE", f"/users/{a.requester2}/roles/{adder}", a, a.admin)
