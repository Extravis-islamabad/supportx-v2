"""Consumable stock, allocations and minimum stock (WP-049b s1; REQ-AST-033, 034, 035; 0130).

The incident world: org A's admin holds everything; technicians only view assets. Org A has
sites s1 and s2.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.assets import (
    register_draft_purchase_requests,
    unregister_draft_purchase_requests,
)
from app.modules.assets.service.notifications import SOURCE
from app.modules.assets.service.realtime import CONSUMABLES_CHANGED, ROUTES
from app.shared.events import EventEnvelope
from app.shared.realtime import broadcast
from tests.db import test_incidents_api
from tests.db.test_assets_api import _product
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"
NEW_TABLES = (
    "asset_consumables",
    "asset_consumable_stocks",
    "asset_consumable_batches",
    "asset_consumable_movements",
    "asset_stock_rules",
)


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def _consumable(
    world: World, name: str, *, batches: bool = False, api_name: str = "toner_and_ink"
) -> dict[str, Any]:
    a = world.a
    product = await _product(world, a, api_name, name)
    made = await world.call(
        "POST", f"{BASE}/consumables", a, a.admin,
        json={"product_id": product, "batch_tracked": batches, "barcode": f"BC-{name}"},
        headers=_key(),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _receive(
    world: World,
    item: dict[str, Any],
    quantity: str,
    site: uuid.UUID | None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - httpx response
    a = world.a
    body = {"quantity": quantity, "site_id": None if site is None else str(site), **extra}
    return await world.call(
        "POST", f"{BASE}/consumables/{item['id']}/receipts", a, a.admin, json=body, headers=_key()
    )


async def _detail(world: World, item: dict[str, Any], org: Org | None = None) -> dict[str, Any]:
    org = org or world.a
    found = await world.call("GET", f"{BASE}/consumables/{item['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


def _stock(detail: dict[str, Any], site: uuid.UUID) -> dict[str, Any]:
    return next(s for s in detail["stocks"] if s["site_id"] == str(site))


async def _allocate(
    world: World,
    item: dict[str, Any],
    stock_id: str,
    quantity: str,
    *,
    kind: str = "user",
    to: uuid.UUID | str | None = None,
    user: uuid.UUID | None = None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - httpx response
    a = world.a
    body = {
        "stock_id": stock_id,
        "quantity": quantity,
        "recipient_kind": kind,
        "recipient_id": str(to or a.requester),
        **extra,
    }
    return await world.call(
        "POST", f"{BASE}/consumables/{item['id']}/allocations", a, user or a.admin,
        json=body, headers=_key(),
    )  # fmt: skip


async def _events(world: World, kind: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2"
        " ORDER BY created_at",
        world.a.tenant,
        kind,
    )
    return [json.loads(r["envelope"]) for r in rows]


async def test_033_ac1_receiving_raises_that_site_only(world: World) -> None:
    """Adding 20 toner cartridges at site A raises site A's stock by 20; site B is unchanged."""
    a = world.a
    toner = await _consumable(world, "Toner 26A")
    assert (await _receive(world, toner, "5", a.s2)).status_code == 201
    first = await _receive(world, toner, "20", a.s1, location="Store room 2")
    assert first.status_code == 201, first.text
    assert first.json()["kind"] == "receive"
    assert Decimal(first.json()["balance_after"]) == Decimal(20)
    assert (await _receive(world, toner, "20", a.s1)).status_code == 201
    detail = await _detail(world, toner)
    assert Decimal(_stock(detail, a.s1)["quantity"]) == 40
    assert Decimal(_stock(detail, a.s2)["quantity"]) == 5
    assert _stock(detail, a.s1)["location"] == "Store room 2"
    assert Decimal(detail["total"]) == 45
    listed = (await world.call("GET", f"{BASE}/consumables?site_id={a.s2}", a, a.tech_a)).json()
    assert [c["id"] for c in listed if c["id"] == toner["id"]] == [toner["id"]]
    # Exact decimals; never a float, never zero or negative.
    paper = await _consumable(world, "Paper roll", api_name="paper")
    assert (await _receive(world, paper, "2.125", a.s1)).status_code == 201
    assert Decimal(_stock(await _detail(world, paper), a.s1)["quantity"]) == Decimal("2.125")
    assert field_codes(await _receive(world, paper, "0", a.s1)) == {
        "quantity": "asset_quantity_positive"
    }
    assert field_codes(await _receive(world, paper, "1.0001", a.s1)) == {
        "quantity": "too_many_decimals"
    }


async def test_033_ac2_batches_show_their_expiry_and_an_expired_one_is_flagged(
    world: World,
) -> None:
    a = world.a
    ink = await _consumable(world, "Ink kit", batches=True)
    no_lot = await _receive(world, ink, "3", a.s1)
    assert field_codes(no_lot) == {"batch": "asset_batch_required"}
    old = (datetime.now(UTC) - timedelta(days=2)).date().isoformat()
    later = (datetime.now(UTC) + timedelta(days=200)).date().isoformat()
    lot_a = {"lot_number": "L-100", "manufactured_on": "2025-01-01", "expires_on": old}
    lot_b = {"lot_number": "L-200", "reference": "PO-9", "expires_on": later}
    assert (await _receive(world, ink, "3", a.s1, batch=lot_a)).status_code == 201
    assert (await _receive(world, ink, "4", a.s1, batch=lot_b)).status_code == 201
    assert (await _receive(world, ink, "1", a.s1, batch={"lot_number": "l-200"})).status_code == 201
    detail = await _detail(world, ink)
    lots = {b["lot_number"]: b for b in detail["batches"]}
    assert set(lots) == {"L-100", "L-200"}  # the same lot, whatever its case
    assert (lots["L-100"]["expired"], lots["L-200"]["expired"]) == (True, False)
    assert lots["L-100"]["expires_on"] == old
    assert Decimal(lots["L-200"]["quantity"]) == 5
    assert Decimal(_stock(detail, a.s1)["quantity"]) == 8
    # Allocating from a batch-tracked consumable names its lot, and takes from that lot.
    stock = _stock(detail, a.s1)["id"]
    assert field_codes(await _allocate(world, ink, stock, "1")) == {
        "batch_id": "asset_batch_required"
    }
    done = await _allocate(world, ink, stock, "2", batch_id=lots["L-200"]["id"])
    assert done.status_code == 201, done.text
    short = await _allocate(world, ink, stock, "4", batch_id=lots["L-100"]["id"])
    assert problem(short) == (409, "asset_stock_short")
    assert short.json()["params"]["available"] == "3"
    after = {
        b["lot_number"]: Decimal(b["quantity"]) for b in (await _detail(world, ink))["batches"]
    }
    assert after == {"L-100": 3, "L-200": 3}


async def test_033_ac3_batch_tracking_cannot_be_switched_later(world: World) -> None:
    a = world.a
    cables = await _consumable(world, "Cat6 cable", api_name="cables")
    switched = await world.call(
        "PATCH", f"{BASE}/consumables/{cables['id']}", a, a.admin,
        json={"batch_tracked": True}, headers=_match(cables["version"]),
    )  # fmt: skip
    assert problem(switched) == (409, "asset_consumable_batch_tracking_fixed")
    changed = await world.call(
        "PATCH", f"{BASE}/consumables/{cables['id']}", a, a.admin,
        json={"barcode": "NEW-1", "comment": "Blue only", "unit_cost": "3.50"},
        headers=_match(cables["version"]),
    )  # fmt: skip
    assert changed.status_code == 200, changed.text
    assert (changed.json()["barcode"], changed.json()["batch_tracked"]) == ("NEW-1", False)
    stale = await world.call(
        "PATCH", f"{BASE}/consumables/{cables['id']}", a, a.admin,
        json={"barcode": "NEW-2"}, headers=_match(cables["version"]),
    )  # fmt: skip
    assert problem(stale) == (409, "version_conflict")
    # Only a product of a consumable type, once.
    laptop = await _product(world, a, "laptop", "Not a consumable")
    refused = await world.call(
        "POST", f"{BASE}/consumables", a, a.admin,
        json={"product_id": laptop, "batch_tracked": False}, headers=_key(),
    )  # fmt: skip
    assert field_codes(refused) == {"product_id": "asset_product_not_consumable"}
    again = await world.call(
        "POST", f"{BASE}/consumables", a, a.admin,
        json={"product_id": cables["product_id"], "batch_tracked": True}, headers=_key(),
    )  # fmt: skip
    assert problem(again) == (409, "asset_consumable_exists")


async def test_034_ac1_allocating_more_than_in_stock_names_what_is_available(
    world: World,
) -> None:
    a = world.a
    cables = await _consumable(world, "USB-C cable", api_name="cables")
    await _receive(world, cables, "2", a.s1)
    stock = _stock(await _detail(world, cables), a.s1)["id"]
    short = await _allocate(world, cables, stock, "3")
    assert problem(short) == (409, "asset_stock_short")
    assert short.json()["params"] == {"available": "2"}
    department = await world.call(
        "POST", "/organization/departments", a, a.admin, json={"name": "Stock finance"}
    )
    assert department.status_code == 201, department.text
    to_department = await _allocate(
        world, cables, stock, "1", kind="department", to=department.json()["id"]
    )
    assert to_department.status_code == 201, to_department.text
    to_person = await _allocate(world, cables, stock, "1", comment="New starter")
    assert Decimal(to_person.json()["balance_after"]) == 0
    assert problem(await _allocate(world, cables, stock, "1")) == (409, "asset_stock_ran_out")
    nobody = await _allocate(world, cables, stock, "1", kind="asset", to=uuid.uuid4())
    assert field_codes(nobody) == {"recipient_id": "asset_holder_not_found"}
    # Technicians only view assets: they may not allocate.
    assert (await _allocate(world, cables, stock, "1", user=a.tech_a)).status_code == 403
    ledger = (
        await world.call("GET", f"{BASE}/consumables/{cables['id']}/ledger", a, a.tech_a)
    ).json()
    assert [(m["kind"], m["quantity"], m["balance_after"]) for m in ledger] == [
        ("allocate", "-1.000", "0.000"),
        ("allocate", "-1.000", "1.000"),
        ("receive", "2.000", "2.000"),
    ]
    assert ledger[0]["comment"] == "New starter"
    assert ledger[1]["recipient_kind"] == "department"
    assert ledger[0]["created_by"] == str(a.admin)
    # Back to stock, and corrected with a reason (never below zero).
    back = await world.call(
        "POST", f"{BASE}/consumables/{cables['id']}/returns", a, a.admin,
        json={"stock_id": stock, "quantity": "1", "recipient_kind": "user",
              "recipient_id": str(a.requester)},
        headers=_key(),
    )  # fmt: skip
    assert back.status_code == 201, back.text
    no_reason = await world.call(
        "POST", f"{BASE}/consumables/{cables['id']}/adjustments", a, a.admin,
        json={"stock_id": stock, "change": "-1", "comment": " "}, headers=_key(),
    )  # fmt: skip
    assert field_codes(no_reason) == {"comment": "required"}
    too_far = await world.call(
        "POST", f"{BASE}/consumables/{cables['id']}/adjustments", a, a.admin,
        json={"stock_id": stock, "change": "-2", "comment": "Counted"}, headers=_key(),
    )  # fmt: skip
    assert problem(too_far) == (409, "asset_stock_short")


async def test_034_ac2_an_allocation_from_a_request_is_linked_on_both_sides(world: World) -> None:
    a = world.a
    request = await world.create(a, a.admin, subject="Needs a toner")
    toner = await _consumable(world, "Toner 12A")
    await _receive(world, toner, "4", a.s1)
    stock = _stock(await _detail(world, toner), a.s1)["id"]
    made = await _allocate(world, toner, stock, "1", work_item_id=request["id"])
    assert made.status_code == 201, made.text
    assert made.json()["work_item_id"] == request["id"]
    # The request's side: what was allocated from it.
    found = await world.call(
        "GET", f"{BASE}/consumable-allocations?work_item_id={request['id']}", a, a.tech_a
    )
    assert [m["id"] for m in found.json()] == [made.json()["id"]]
    # And its event names the request, for the request's own screens (an ID only).
    moved = [
        e for e in await _events(world, "assets.stock.moved") if e["payload"]["kind"] == "allocate"
    ]
    assert moved[-1]["payload"]["work_item_id"] == request["id"]
    assert "quantity" not in moved[-1]["payload"]


async def test_034_ac3_two_people_taking_the_last_unit_at_once_one_wins(world: World) -> None:
    a = world.a
    cables = await _consumable(world, "Last HDMI cable", api_name="cables")
    await _receive(world, cables, "1", a.s1)
    stock = _stock(await _detail(world, cables), a.s1)["id"]
    first, second = await asyncio.gather(
        _allocate(world, cables, stock, "1", to=a.requester),
        _allocate(world, cables, stock, "1", to=a.requester2),
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 409], (first.text, second.text)
    loser = first if first.status_code == 409 else second
    assert loser.json()["code"] == "asset_stock_ran_out"
    rows = await world.sql(
        "SELECT quantity FROM asset_consumable_stocks WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(stock),
    )
    assert rows[0]["quantity"] == 0
    lines = await world.sql(
        "SELECT count(*) AS n FROM asset_consumable_movements WHERE tenant_id = $1"
        " AND stock_id = $2 AND kind = 'allocate'",
        a.tenant,
        uuid.UUID(stock),
    )
    assert lines[0]["n"] == 1


async def _types(world: World) -> dict[str, str]:
    found = await world.call("GET", f"{BASE}/product-types", world.a, world.a.admin)
    return {t["api_name"]: t["id"] for t in found.json()}


async def _rule(world: World, **body: Any) -> Any:  # noqa: ANN401 - JSON and httpx response
    a = world.a
    return await world.call("POST", f"{BASE}/stock-rules", a, a.admin, json=body, headers=_key())


async def test_035_ac1_stock_falling_below_notifies_once_until_it_rises_again(
    world: World,
) -> None:
    """6 → 4 with a minimum of 5 notifies once; → 3 does not; above 5 again re-arms it."""
    a = world.a
    types = await _types(world)
    toner = await _consumable(world, "Toner 05X")
    await _receive(world, toner, "6", a.s1)
    stock = _stock(await _detail(world, toner), a.s1)["id"]
    rule = await _rule(
        world, product_type_id=types["toner_and_ink"], min_quantity="5",
        notify_user_ids=[str(a.tech_a)],
    )  # fmt: skip
    assert rule.status_code == 201, rule.text

    async def lows() -> list[dict[str, Any]]:
        return [
            e for e in await _events(world, "assets.stock.low") if e["payload"]["stock_id"] == stock
        ]

    assert await lows() == []
    await _allocate(world, toner, stock, "2")  # 6 → 4
    assert len(await lows()) == 1
    detail = await _detail(world, toner)
    assert (_stock(detail, a.s1)["low"], _stock(detail, a.s1)["minimum"]) == (True, "5.000")
    await _allocate(world, toner, stock, "1")  # 4 → 3: no second notice
    assert len(await lows()) == 1
    await _receive(world, toner, "2", a.s1)  # 3 → 5: still at the minimum, still alerted
    assert len(await lows()) == 1
    await _receive(world, toner, "1", a.s1)  # 5 → 6: above it, re-armed
    assert _stock(await _detail(world, toner), a.s1)["low"] is False
    await _allocate(world, toner, stock, "2")  # 6 → 4: notifies again
    found = await lows()
    assert len(found) == 2
    # The notice goes to the rule's people, with the quantity and minimum.
    envelope = EventEnvelope.model_validate(found[-1])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert SOURCE.events_for(envelope) == ("asset.stock_low",)
        context = await SOURCE.context(session, "asset.stock_low", envelope)
    assert context is not None
    assert context.relatives["stock_watchers"] == frozenset({a.tech_a})
    assert (context.variables["stock.quantity"], context.variables["stock.minimum"]) == ("4", "5")
    # A product's own rule (and a site's) is more specific than its type's.
    own = await _rule(world, product_id=toner["product_id"], site_id=str(a.s1), min_quantity="2")
    assert own.status_code == 201, own.text
    assert _stock(await _detail(world, toner), a.s1)["minimum"] == "2.000"
    assert _stock(await _detail(world, toner), a.s1)["low"] is False  # 4 > 2: re-armed
    duplicate = await _rule(
        world, product_id=toner["product_id"], site_id=str(a.s1), min_quantity="1"
    )
    assert problem(duplicate) == (409, "asset_stock_rule_exists")


async def test_035_rules_are_set_up_by_admins_and_checked(world: World) -> None:
    a = world.a
    types = await _types(world)
    both = await _rule(
        world, product_type_id=types["toner_and_ink"], product_id=str(uuid.uuid4()),
        min_quantity="1",
    )  # fmt: skip
    assert field_codes(both) == {"product_id": "asset_stock_rule_target"}
    not_stock = await _rule(world, product_type_id=types["laptop"], min_quantity="1")
    assert field_codes(not_stock) == {"product_type_id": "asset_type_not_consumable"}
    no_reorder = await _rule(
        world, product_type_id=types["cables"], min_quantity="1", create_purchase_request=True
    )
    assert field_codes(no_reorder) == {"reorder_quantity": "required"}
    by_tech = await world.call(
        "POST", f"{BASE}/stock-rules", a, a.tech_a,
        json={"product_type_id": types["cables"], "min_quantity": "1"}, headers=_key(),
    )  # fmt: skip
    assert by_tech.status_code == 403
    made = await _rule(world, product_type_id=types["batteries"], min_quantity="0")
    assert made.status_code == 201, made.text
    changed = await world.call(
        "PATCH", f"{BASE}/stock-rules/{made.json()['id']}", a, a.admin,
        json={"min_quantity": "3"}, headers=_match(made.json()["version"]),
    )  # fmt: skip
    assert changed.json()["min_quantity"] == "3.000"
    gone = await world.call(
        "DELETE", f"{BASE}/stock-rules/{made.json()['id']}", a, a.admin,
        headers=_match(changed.json()["version"]),
    )  # fmt: skip
    assert gone.status_code == 204
    listed = (await world.call("GET", f"{BASE}/stock-rules", a, a.tech_a)).json()
    assert made.json()["id"] not in {r["id"] for r in listed}


async def test_035_ac2_the_draft_purchase_request_goes_through_procurements_port(
    world: World,
) -> None:
    """Procurement (WP-054) fills the port; until then nothing is made. A recording port here."""
    a = world.a
    calls: list[dict[str, Any]] = []

    async def record(session: Any, **values: Any) -> uuid.UUID | None:  # noqa: ANN401 - the port's arguments
        del session
        calls.append(values)
        return None

    batteries = await _consumable(world, "AA batteries", api_name="batteries")
    await _receive(world, batteries, "10", a.s1)
    stock = _stock(await _detail(world, batteries), a.s1)["id"]
    made = await _rule(
        world, product_id=batteries["product_id"], min_quantity="5",
        create_purchase_request=True, reorder_quantity="40",
    )  # fmt: skip
    assert made.status_code == 201, made.text
    await _allocate(world, batteries, stock, "3")  # 10 → 7: nothing
    unregister_draft_purchase_requests()
    await _allocate(world, batteries, stock, "3")  # 7 → 4: alert, no port: none made
    await _receive(world, batteries, "10", a.s1)  # re-arm
    register_draft_purchase_requests(record)
    try:
        await _allocate(world, batteries, stock, "10")  # 14 → 4: alert, the port is asked
    finally:
        unregister_draft_purchase_requests()
    assert len(calls) == 1
    assert (calls[0]["quantity"], str(calls[0]["stock_id"])) == (Decimal(40), stock)


async def test_stock_tables_are_isolated_by_rls_and_the_ledger_is_append_only(
    world: World,
) -> None:
    a, b = world.a, world.b
    types = await _types(world)
    lots = await _consumable(world, "RLS ink", batches=True)
    await _receive(world, lots, "2", a.s1, batch={"lot_number": "R-1"})
    stock = _stock(await _detail(world, lots), a.s1)["id"]
    await _allocate(
        world, lots, stock, "1", batch_id=(await _detail(world, lots))["batches"][0]["id"]
    )
    assert (await _rule(world, product_type_id=types["paper"], min_quantity="1")).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in NEW_TABLES:
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        changed = await session.execute(text("UPDATE asset_consumable_stocks SET quantity = 99"))
        assert changed.rowcount == 0
    assert (await world.call("GET", f"{BASE}/consumables", b, b.admin)).json() == []
    assert (
        await world.call("GET", f"{BASE}/consumables/{lots['id']}", b, b.admin)
    ).status_code == 404
    # The application role reads and adds ledger lines, and can do nothing else to them.
    for statement in (
        "UPDATE asset_consumable_movements SET comment = 'x'",
        "DELETE FROM asset_consumable_movements",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
                await session.execute(text(statement))


async def test_a_stock_change_refreshes_consumable_screens_live_with_ids_only(world: World) -> None:
    a = world.a
    toner = await _consumable(world, "Live toner")
    await _receive(world, toner, "1", a.s1)
    envelope = EventEnvelope.model_validate((await _events(world, "assets.stock.moved"))[-1])
    route = next(r for r in ROUTES if envelope.event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(envelope, session)
    assert {(p.channel, p.type, p.ids) for p in effects.publications} == {
        (broadcast(a.tenant), CONSUMABLES_CHANGED, (toner["id"],))
    }
    # A consumable that still holds stock is not removed.
    fresh = await _detail(world, toner)
    kept = await world.call(
        "DELETE", f"{BASE}/consumables/{toner['id']}", a, a.admin, headers=_match(fresh["version"])
    )
    assert problem(kept) == (409, "asset_consumable_has_stock")
    # Requesters see no stock at all.
    assert (await world.call("GET", f"{BASE}/consumables", a, a.requester)).status_code == 403
