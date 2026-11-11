"""D-157: a technician's narrower write on its tickets' assets, and money behind view_financials.

The incident world (tests/db/test_incidents_api.py): org A's admin holds everything; tech_a and
tech_b are built-in technicians (`assets.view`, no `assets.manage`, no
`assets.view_financials`); the requester is built-in. Assets are made by the admin.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from tests.db import test_incidents_api
from tests.db.test_asset_holders_api import _asset, _hold
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import World, problem, role
from tests.db.test_knowledge_api import _match

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused

ASSETS = "/assets"


async def _fresh(world: World, asset: dict[str, Any], user: uuid.UUID | None = None) -> Any:  # noqa: ANN401 - JSON
    a = world.a
    found = await world.call("GET", f"{ASSETS}/{asset['id']}", a, user or a.admin)
    assert found.status_code == 200, found.text
    return found.json()


async def _patch(world: World, user: uuid.UUID, asset: dict[str, Any], **body: Any) -> Any:  # noqa: ANN401 - JSON and httpx
    return await world.call(
        "PATCH",
        f"{ASSETS}/{asset['id']}",
        world.a,
        user,
        json=body,
        headers=_match(asset["version"]),
    )


async def _ticket(world: World, asset: dict[str, Any], technician: uuid.UUID) -> dict[str, Any]:
    a = world.a
    return await world.create(
        a,
        a.admin,
        group_id=str(a.gb if technician == a.tech_b else a.ga),
        technician_id=str(technician),
        requester_id=str(a.requester),
        asset_ids=[asset["id"]],
    )


async def _requesters_asset(world: World, name: str) -> dict[str, Any]:
    asset = await _asset(world, name)
    held = await _hold(world, asset, "user", world.a.requester)
    assert held.status_code == 200, held.text
    return dict(held.json())


async def _component(world: World, name: str) -> dict[str, Any]:
    """A part nobody holds: a product of the seeded memory module type (kind component)."""
    a = world.a
    product = await _product(world, a, "memory_module", f"Part {name}")
    made = await _add(world, a, {"name": name, "product_id": product})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _fit(world: World, user: uuid.UUID, part: dict[str, Any], into: dict[str, Any]) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "PUT",
        f"{ASSETS}/{part['id']}/holder",
        world.a,
        user,
        json={"kind": "asset", "id": into["id"]},
        headers=_match(part["version"]),
    )


def _refused_field(response: Any) -> str:  # noqa: ANN401 - httpx response
    assert problem(response) == (403, "asset_field_not_allowed"), response.text
    return str(response.json()["params"]["field"])


async def test_a_technician_changes_the_allowed_fields_of_its_tickets_requester_asset(
    world: World,
) -> None:
    """Location, a state move and fitted parts: saved, with history and audit as the technician."""
    a = world.a
    laptop = await _requesters_asset(world, "D157 laptop")
    await _ticket(world, laptop, a.tech_a)
    reach = await world.call("GET", f"{ASSETS}/{laptop['id']}/access", a, a.tech_a)
    assert reach.json() == {"manage": False, "through_ticket": True}, reach.text
    reach = await world.call("GET", f"{ASSETS}/{laptop['id']}/access", a, a.admin)
    assert reach.json() == {"manage": True, "through_ticket": False}, reach.text
    changed = await _patch(world, a.tech_a, laptop, location="Desk 4")
    assert changed.status_code == 200, changed.text
    laptop = changed.json()
    assert laptop["location"] == "Desk 4"
    history = await world.call("GET", f"{ASSETS}/{laptop['id']}/history", a, a.admin)
    newest = history.json()["items"][0]
    assert newest["actor_id"] == str(a.tech_a)
    assert [c["field"] for c in newest["changes"]] == ["location"]
    audit = await world.sql(
        "SELECT actor_id FROM audit_entries WHERE tenant_id = $1 AND action = 'asset.updated'"
        " AND object_id = $2 AND outcome = 'done'",
        a.tenant,
        laptop["id"],
    )
    assert [r["actor_id"] for r in audit] == [a.tech_a]
    # A move along the life cycle: offered, and made.
    options = await world.call("GET", f"{ASSETS}/{laptop['id']}/moves", a, a.tech_a)
    allowed = [o for o in options.json() if o["allowed"] and not o["required_fields"]]
    assert allowed, options.text
    target = allowed[0]
    moved = await world.call(
        "POST",
        f"{ASSETS}/{laptop['id']}/move",
        a,
        a.tech_a,
        json={"to_state_id": target["to_state_id"], "reason": "Swapped at the desk"},
        headers=_match(laptop["version"]),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["state_id"] == target["to_state_id"]
    laptop = moved.json()
    # A free part fitted into it, and taken back out.
    ram = await _component(world, "D157 memory")
    fitted = await world.call(
        "PUT",
        f"{ASSETS}/{ram['id']}/holder",
        a,
        a.tech_a,
        json={"kind": "asset", "id": laptop["id"]},
        headers=_match(ram["version"]),
    )
    assert fitted.status_code == 200, fitted.text
    assert fitted.json()["parent_asset_id"] == laptop["id"]
    out = await world.call(
        "DELETE",
        f"{ASSETS}/{ram['id']}/holder",
        a,
        a.tech_a,
        headers=_match(fitted.json()["version"]),
    )
    assert out.status_code == 200, out.text
    assert out.json()["parent_asset_id"] is None


async def test_fields_outside_the_allow_list_are_refused_with_their_code(world: World) -> None:
    a = world.a
    laptop = await _requesters_asset(world, "D157 refused")
    await _ticket(world, laptop, a.tech_a)
    assert _refused_field(await _patch(world, a.tech_a, laptop, purchase_price="900.00")) == (
        "purchase_price"
    )
    assert _refused_field(await _patch(world, a.tech_a, laptop, name="Renamed")) == "name"
    assert _refused_field(await _patch(world, a.tech_a, laptop, cost_centre="CC-1")) == (
        "cost_centre"
    )
    # Mixed with an allowed one: nothing is saved.
    both = await _patch(world, a.tech_a, laptop, location="Desk 9", site_id=str(a.s2))
    assert _refused_field(both) == "site_id"
    assert (await _fresh(world, laptop))["location"] is None
    # Its holder never changes this way, to anyone.
    given = await world.call(
        "PUT",
        f"{ASSETS}/{laptop['id']}/holder",
        a,
        a.tech_a,
        json={"kind": "user", "id": str(a.tech_a)},
        headers=_match(laptop["version"]),
    )
    assert _refused_field(given) == "holder"
    taken = await world.call(
        "DELETE", f"{ASSETS}/{laptop['id']}/holder", a, a.tech_a, headers=_match(laptop["version"])
    )
    assert _refused_field(taken) == "holder"
    # A part held by someone is not taken from them to be fitted.
    mouse = await _asset(world, "D157 someone's mouse")
    mouse = (await _hold(world, mouse, "user", a.requester2)).json()
    stolen = await world.call(
        "PUT",
        f"{ASSETS}/{mouse['id']}/holder",
        a,
        a.tech_a,
        json={"kind": "asset", "id": laptop["id"]},
        headers=_match(mouse["version"]),
    )
    assert problem(stolen) == (403, "permission_denied")


async def test_an_asset_not_held_by_the_requester_or_department_is_refused(world: World) -> None:
    a = world.a
    elsewhere = await _asset(world, "D157 someone else's")
    elsewhere = (await _hold(world, elsewhere, "user", a.requester2)).json()
    await _ticket(world, elsewhere, a.tech_a)
    refused = await _patch(world, a.tech_a, elsewhere, location="Desk 1")
    assert problem(refused) == (403, "permission_denied")
    unheld = await _asset(world, "D157 in stock")
    await _ticket(world, unheld, a.tech_a)
    assert problem(await _patch(world, a.tech_a, unheld, location="Desk 1")) == (
        403,
        "permission_denied",
    )
    # Held by the requester's department: allowed.
    made = await world.call(
        "POST",
        "/organization/departments",
        a,
        a.admin,
        json={"name": f"D157 {uuid.uuid4().hex[:6]}"},
    )
    assert made.status_code == 201, made.text
    department = made.json()["id"]
    await world.sql(
        "UPDATE users SET department_id = $1 WHERE id = $2", uuid.UUID(department), a.requester
    )
    shared = await _asset(world, "D157 department printer")
    shared = (await _hold(world, shared, "department", department)).json()
    await _ticket(world, shared, a.tech_a)
    ok = await _patch(world, a.tech_a, shared, location="Floor 2")
    assert ok.status_code == 200, ok.text


async def test_another_tenants_asset_is_not_found(world: World) -> None:
    a, b = world.a, world.b
    laptop = await _requesters_asset(world, "D157 tenant A")
    await _ticket(world, laptop, a.tech_a)
    foreign = await world.call(
        "PATCH",
        f"{ASSETS}/{laptop['id']}",
        b,
        b.tech_a,
        json={"location": "Elsewhere"},
        headers=_match(laptop["version"]),
    )
    assert problem(foreign) == (404, "asset_not_found")


async def test_someone_elses_ticket_and_a_closed_ticket_grant_nothing(world: World) -> None:
    a = world.a
    laptop = await _requesters_asset(world, "D157 assigned to B")
    ticket = await _ticket(world, laptop, a.tech_b)
    assert problem(await _patch(world, a.tech_a, laptop, location="Desk 2")) == (
        403,
        "permission_denied",
    )
    ok = await _patch(world, a.tech_b, laptop, location="Desk 2")
    assert ok.status_code == 200, ok.text
    laptop = ok.json()
    resolved = await world.act(a, a.tech_b, ticket, "resolve")
    assert resolved.status_code == 200, resolved.text
    ok = await _patch(world, a.tech_b, laptop, location="Desk 3")  # resolved, not closed: still
    assert ok.status_code == 200, ok.text
    laptop = ok.json()
    closed = await world.act(a, a.tech_b, await world.fresh(a, ticket), "close")
    assert closed.status_code == 200, closed.text
    assert problem(await _patch(world, a.tech_b, laptop, location="Desk 4")) == (
        403,
        "permission_denied",
    )
    options = await world.call("GET", f"{ASSETS}/{laptop['id']}/moves", a, a.tech_b)
    assert not any(o["allowed"] for o in options.json())
    reach = await world.call("GET", f"{ASSETS}/{laptop['id']}/access", a, a.tech_b)
    assert reach.json() == {"manage": False, "through_ticket": False}, reach.text


async def test_only_free_components_are_fitted_through_a_ticket(world: World) -> None:
    """Lane B review: a free laptop is no part; a part someone holds is not taken from them."""
    a = world.a
    laptop = await _requesters_asset(world, "D157 parts laptop")
    await _ticket(world, laptop, a.tech_a)
    disk = await _component(world, "D157 free disk")
    fitted = await _fit(world, a.tech_a, disk, laptop)
    assert fitted.status_code == 200, fitted.text
    spare = await _asset(world, "D157 spare laptop")  # kind asset, in stock, nobody's
    assert problem(await _fit(world, a.tech_a, spare, laptop)) == (403, "asset_not_a_component")
    assert (await _fresh(world, spare))["parent_asset_id"] is None
    held = await _component(world, "D157 someone's disk")
    held = (await _hold(world, held, "user", a.requester2)).json()
    assert problem(await _fit(world, a.tech_a, held, laptop)) == (403, "permission_denied")
    # An asset manager is unaffected: they fit anything.
    assert (await _fit(world, a.admin, spare, laptop)).status_code == 200


async def test_a_ticket_never_retires_or_disposes_of_an_asset(world: World) -> None:
    """Lane B review: end of life (retired, disposed) has its own process; repair is fine."""
    a = world.a
    laptop = await _requesters_asset(world, "D157 end of life")
    await _ticket(world, laptop, a.tech_a)
    states = {
        s["id"]: s["category"]
        for s in (await world.call("GET", f"{ASSETS}/states", a, a.admin)).json()
    }
    options = (await world.call("GET", f"{ASSETS}/{laptop['id']}/moves", a, a.tech_a)).json()
    by_category = {states[o["to_state_id"]]: o for o in options}
    assert by_category["retired"]["allowed"] is False
    assert by_category["in_repair"]["allowed"] is True

    async def move(category: str, version: int) -> Any:  # noqa: ANN401 - httpx response
        return await world.call(
            "POST",
            f"{ASSETS}/{laptop['id']}/move",
            a,
            a.tech_a,
            json={"to_state_id": by_category[category]["to_state_id"], "reason": "Broken"},
            headers=_match(version),
        )

    refused = await move("retired", laptop["version"])
    assert problem(refused) == (403, "asset_move_not_allowed_through_ticket"), refused.text
    repaired = await move("in_repair", laptop["version"])
    assert repaired.status_code == 200, repaired.text
    # The admin still retires it.
    admin = await world.call("GET", f"{ASSETS}/{laptop['id']}/moves", a, a.admin)
    assert any(states[o["to_state_id"]] == "retired" and o["allowed"] for o in admin.json())


# --- money behind assets.view_financials --------------------------------------------------------

_MONEY = ("purchase_price", "purchase_tax", "purchase_total")


async def test_money_is_hidden_without_view_financials_in_get_list_and_history(
    world: World,
) -> None:
    a = world.a
    laptop = await _asset(world, "D157 priced")
    priced = await world.call(
        "PATCH",
        f"{ASSETS}/{laptop['id']}",
        a,
        a.admin,
        json={"purchase_price": "1000.00", "purchase_tax": "170.00", "useful_life_years": 4},
        headers=_match(laptop["version"]),
    )
    assert priced.status_code == 200, priced.text
    assert priced.json()["purchase_total"] == "1170.00"
    # The holder (the admin) sees it all; the technician sees nulls.
    mine = await _fresh(world, laptop)
    assert (mine["purchase_price"], mine["purchase_tax"]) == ("1000.00", "170.00")
    theirs = await _fresh(world, laptop, a.tech_a)
    assert all(theirs[k] is None for k in _MONEY), theirs
    listed = await world.call("GET", ASSETS, a, a.tech_a, params={"name": "D157 priced"})
    assert listed.status_code == 200, listed.text
    (row,) = listed.json()["items"]
    assert all(row[k] is None for k in _MONEY)

    def lines(body: dict[str, Any]) -> list[dict[str, Any]]:
        return [c for e in body["items"] for c in e["changes"] if c["field"] in money_fields]

    money_fields = {"purchase_price", "purchase_tax", "useful_life_years"}
    seen = await world.call("GET", f"{ASSETS}/{laptop['id']}/history", a, a.admin)
    assert {(c["field"], c["new"], c["hidden"]) for c in lines(seen.json())} == {
        ("purchase_price", "1000.00", False),
        ("purchase_tax", "170.00", False),
        ("useful_life_years", 4, False),
    }
    masked = await world.call("GET", f"{ASSETS}/{laptop['id']}/history", a, a.tech_a)
    assert {(c["field"], c["old"], c["new"], c["hidden"]) for c in lines(masked.json())} == {
        ("purchase_price", None, None, True),
        ("purchase_tax", None, None, True),
        ("useful_life_years", None, None, True),
    }
    # No filtering or sorting by money in the list.
    for params in (
        {"sort": "purchase_price"},
        {"filter": '{"field": "purchase_price", "op": "gt", "value": "1"}'},
        {"purchase_tax": "170.00"},
    ):
        refused = await world.call("GET", ASSETS, a, a.tech_a, params=params)
        assert refused.status_code == 422, (params, refused.text)


async def test_writing_the_price_needs_view_financials(world: World) -> None:
    """A manager of assets without view_financials may not set the price or the tax."""
    a = world.a
    keeper = await role(
        world,
        a,
        f"Asset keeper {uuid.uuid4().hex[:6]}",
        [("assets.view", "all"), ("assets.manage", "all")],
    )
    given = await world.call("PUT", f"/users/{a.tech_c}/roles/{keeper}", a, a.admin)
    assert given.status_code == 204, given.text
    laptop = await _asset(world, "D157 unpriced")
    for body in ({"purchase_price": "10.00"}, {"purchase_tax": "1.00"}):
        refused = await _patch(world, a.tech_c, laptop, **body)
        assert problem(refused) == (403, "permission_denied"), refused.text
        assert refused.json()["params"]["permission"] == "assets.view_financials"
    ok = await _patch(world, a.tech_c, laptop, location="Store")
    assert ok.status_code == 200, ok.text
    assert ok.json()["purchase_price"] is None


# --- straight line by default; declining balance with the type's factor --------------------------


async def test_straight_line_is_the_default_and_declining_balance_takes_the_types_factor(
    world: World,
) -> None:
    a = world.a
    bought = datetime.now(UTC).date() - timedelta(days=366)
    laptop = await _asset(world, "D157 depreciating")
    priced = await _patch(
        world,
        a.admin,
        laptop,
        purchase_price="10000.00",
        acquired_on=str(bought),
        useful_life_years=5,
        salvage_value="1000.00",
    )
    assert priced.status_code == 200, priced.text
    laptop = priced.json()

    async def money() -> dict[str, Any]:
        found = await world.call("GET", f"{ASSETS}/{laptop['id']}/financials", a, a.admin)
        assert found.status_code == 200, found.text
        return dict(found.json())

    # Neither the asset nor its product names a method: straight line, 1,800 a year.
    terms = (await money())["depreciation"]
    assert (terms["method"], terms["method_from"]) == ("straight_line", "default")
    assert Decimal((await money())["book_value"]) == Decimal(8200)
    # Declining balance with the type's factor: 2 by default (40 % a year here).
    chosen = await _patch(world, a.admin, laptop, depreciation_method="declining_balance")
    assert chosen.status_code == 200, chosen.text
    assert Decimal((await money())["book_value"]) == Decimal(6000)
    # The type's factor, set on the type (admin API), changes it: 1.5 is 30 % a year.
    kind = next(
        t
        for t in (await world.call("GET", f"{ASSETS}/product-types", a, a.admin)).json()
        if t["id"] == laptop["product_type_id"]
    )
    assert Decimal(kind["depreciation_factor"]) == Decimal(2)
    for wrong in ("0", "10.5"):
        refused = await world.call(
            "PATCH",
            f"{ASSETS}/product-types/{kind['id']}",
            a,
            a.admin,
            json={"depreciation_factor": wrong},
            headers=_match(kind["version"]),
        )
        assert refused.status_code == 422, refused.text
    changed = await world.call(
        "PATCH",
        f"{ASSETS}/product-types/{kind['id']}",
        a,
        a.admin,
        json={"depreciation_factor": "1.5"},
        headers=_match(kind["version"]),
    )
    assert changed.status_code == 200, changed.text
    assert Decimal(changed.json()["depreciation_factor"]) == Decimal("1.5")
    assert Decimal((await money())["book_value"]) == Decimal(7000)
    # Double declining stays 200 %, whatever the type's factor.
    double = await _patch(
        world, a.admin, chosen.json(), depreciation_method="double_declining_balance"
    )
    assert double.status_code == 200, double.text
    assert Decimal((await money())["book_value"]) == Decimal(6000)


async def test_catalogue_prices_need_view_financials_and_the_picker_still_works(
    world: World,
) -> None:
    """D-157 2b: list price, tax, total and default depreciation are money too."""
    a = world.a
    product_types = (await world.call("GET", f"{ASSETS}/product-types", a, a.admin)).json()
    laptop_type = next(t for t in product_types if t["api_name"] == "laptop")
    made = await world.call(
        "POST",
        f"{ASSETS}/products",
        a,
        a.admin,
        json={
            "product_type_id": laptop_type["id"],
            "name": "D157 priced model",
            "price": "900.00",
            "tax": "153.00",
            "depreciation_method": "straight_line",
            "useful_life_years": 4,
            "salvage_value": "100.00",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert made.status_code == 201, made.text
    product = made.json()
    money = ("price", "tax", "total", "depreciation_method", "useful_life_years", "salvage_value")

    async def seen(user: uuid.UUID) -> dict[str, Any]:
        listed = await world.call(
            "GET", f"{ASSETS}/products", a, user, params={"product_type_id": laptop_type["id"]}
        )
        assert listed.status_code == 200, listed.text
        (row,) = [p for p in listed.json()["items"] if p["id"] == product["id"]]
        one = await world.call("GET", f"{ASSETS}/products/{product['id']}", a, user)
        assert one.status_code == 200, one.text
        assert {k: one.json()[k] for k in money} == {k: row[k] for k in money}
        return dict(row)

    holder = await seen(a.admin)
    assert (holder["price"], holder["total"], holder["useful_life_years"]) == (
        "900.00",
        "1053.00",
        4,
    )
    viewer = await seen(a.tech_a)  # the picker still lists it, by name, without money
    assert viewer["name"] == "D157 priced model"
    assert all(viewer[k] is None for k in money), viewer
    # Writing the money needs the right too, even for a catalogue configurer.
    keeper = await role(
        world,
        a,
        f"Catalogue keeper {uuid.uuid4().hex[:6]}",
        [("assets.view", "all"), ("config.assets", "all")],
    )
    given = await world.call("PUT", f"/users/{a.tech_c}/roles/{keeper}", a, a.admin)
    assert given.status_code == 204, given.text
    for body in ({"price": "1.00"}, {"tax": "1.00"}, {"useful_life_years": 3}):
        refused = await world.call(
            "PATCH",
            f"{ASSETS}/products/{product['id']}",
            a,
            a.tech_c,
            json=body,
            headers=_match(product["version"]),
        )
        assert problem(refused) == (403, "permission_denied"), refused.text
        assert refused.json()["params"]["permission"] == "assets.view_financials"
    renamed = await world.call(
        "PATCH",
        f"{ASSETS}/products/{product['id']}",
        a,
        a.tech_c,
        json={"name": "D157 renamed model"},
        headers=_match(product["version"]),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["price"] is None  # their own answer is masked too
    assert (await seen(a.admin))["price"] == "900.00"  # and nothing was cleared


async def test_an_asset_of_the_person_a_ticket_is_on_behalf_of_counts(world: World) -> None:
    """Lane A: the ticket's on-behalf person (and their department) holds it: allowed too."""
    a = world.a
    laptop = await _requesters_asset(world, "D157 on behalf")  # held by a.requester
    ticket = await world.create(
        a,
        a.admin,
        group_id=str(a.ga),
        technician_id=str(a.tech_a),
        requester_id=str(a.requester2),
        on_behalf_of_id=str(a.requester),
        asset_ids=[laptop["id"]],
    )
    assert (ticket["requester_id"], ticket["on_behalf_of_id"]) == (
        str(a.requester2),
        str(a.requester),
    )
    ok = await _patch(world, a.tech_a, laptop, location="Desk 7")
    assert ok.status_code == 200, ok.text
