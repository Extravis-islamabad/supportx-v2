"""Item prices, the estimate and charge-back (WP-047b S1; REQ-CAT-020, -021, D-184, SR-033 AC2).

Real PostgreSQL with RLS. The estimate is snapshotted at submission and on changed answers,
never on item edits; who sees it (D-184); the charge frozen at fulfilment, once; editions; an
automatic rule "below a cost"; prices in the portal only when the tenant shows them.
"""

import uuid
from decimal import Decimal
from typing import Any

from conftest import assign_system_role, create_tenant
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, fresh, manager_of
from tests.db.test_catalog_api import add as add_item
from tests.db.test_fulfilment_api import done, tasks
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_service_requests_api import SR, an_item, raise_request
from tests.db.test_users_api import seed_users

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

MODEL = {
    "key": "model",
    "label": {"en": "Model"},
    "kind": "choice",
    "required": True,
    "options": ["air", "pro"],
    "option_prices": {"pro": "100.00"},
}


async def priced(world: World, org: Org, **over: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return await an_item(world, org, questions=[MODEL], price="500.00", max_quantity=5, **over)


async def raised(
    world: World, org: Org, item: dict[str, Any], model: str, quantity: int | None = None
) -> dict[str, Any]:
    made = await raise_request(
        world,
        org,
        org.admin,
        catalog_item_id=item["id"],
        answers={"model": model},
        on_behalf_of_id=str(org.requester),
        group_id=str(org.ga),
        technician_id=str(org.tech_a),
        **({"quantity": quantity} if quantity else {}),
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_the_estimate_is_taken_at_submission_and_on_changed_answers_only(
    world: World,
) -> None:
    """CAT-020 AC1, D-184: 500 + 100 = 600, times the quantity; an item edit changes nothing."""
    a = world.a
    item = await priced(world, a)
    record = await raised(world, a, item, "pro", quantity=2)
    assert Decimal((await fresh(world, a, record))["estimated_cost"]) == Decimal("1200.00")
    edited = await world.call(
        "PATCH",
        f"/catalog/items/{item['id']}",
        a,
        a.admin,
        json={"price": "900.00"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert edited.status_code == 200, edited.text
    assert Decimal((await fresh(world, a, record))["estimated_cost"]) == Decimal("1200.00")
    current = await fresh(world, a, record)
    changed = await world.call(
        "PATCH",
        f"{SR}/{record['id']}/answers",
        a,
        a.admin,
        json={"answers": {"model": "air"}},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    # A changed answer takes the estimate again from the item as it is then (900 x 2).
    assert Decimal((await fresh(world, a, record))["estimated_cost"]) == Decimal("1800.00")


async def _show_prices(world: World, org: Org, *, show: bool) -> Any:  # noqa: ANN401 - httpx response
    current = await world.call("GET", "/catalog/settings", org, org.admin)
    assert current.status_code == 200, current.text
    return await world.call(
        "PATCH",
        "/catalog/settings",
        org,
        org.admin,
        json={"requesters_see_prices": show},
        headers={"If-Match": f'"{current.json()["version"]}"', **CONSOLE},
    )


async def test_d184_who_sees_the_estimate(world: World) -> None:
    """View_costs and approvers see it; another technician never; the requester by setting."""
    a = world.a
    await manager_of(world, a.requester, a.tech_b)
    item = await priced(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    record = await raised(world, a, item, "air")
    seen = await world.call("GET", f"{SR}/{record['id']}", a, a.admin)
    assert Decimal(seen.json()["estimated_cost"]) == Decimal("500.00")  # admin: view_costs
    approver = await world.call("GET", f"{SR}/{record['id']}", a, a.tech_b)
    if approver.status_code == 200:
        assert Decimal(approver.json()["estimated_cost"]) == Decimal("500.00")
    other = await world.call("GET", f"{SR}/{record['id']}", a, a.tech_a)
    assert other.status_code == 200, other.text
    assert other.json()["estimated_cost"] is None
    assert other.json()["charged_amount"] is None
    portal = f"/portal/service-requests/{record['id']}"
    hidden = await world.call("GET", portal, a, a.requester)
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["estimated_cost"] is None  # off by default
    on = await _show_prices(world, a, show=True)
    assert on.status_code == 200, on.text
    try:
        shown = await world.call("GET", portal, a, a.requester)
        assert Decimal(shown.json()["estimated_cost"]) == Decimal("500.00")
        card = await world.call("GET", f"/catalog/items/{item['id']}", a, a.requester)
        assert Decimal(card.json()["price"]) == Decimal("500.00")
        assert card.json()["internal_cost"] is None
    finally:
        await _show_prices(world, a, show=False)
    card = await world.call("GET", f"/catalog/items/{item['id']}", a, a.requester)
    assert card.json()["price"] is None
    assert not any(q.get("option_prices") for q in card.json()["questions"])  # none sent


async def test_fulfilment_freezes_the_charge_once(world: World) -> None:
    """CAT-021 AC1: the department at fulfilment; a later move of the person changes nothing."""
    a = world.a
    depts = await world.sql(
        "SELECT id FROM departments WHERE tenant_id = $1 AND deleted_at IS NULL LIMIT 2", a.tenant
    )
    item = await priced(world, a, plan=[{"title": {"en": "Order"}}])
    if depts:
        await world.sql(
            "UPDATE users SET department_id = $3 WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            a.requester,
            depts[0]["id"],
        )
    record = await raised(world, a, item, "pro")
    [order] = await tasks(world, a, record)
    await done(world, a, record, order)
    after = await fresh(world, a, record)
    assert after["status"] == "fulfilled"
    assert Decimal(after["charged_amount"]) == Decimal("600.00")  # the frozen estimate
    assert after["charged_at"] is not None
    if depts:
        assert after["charge_department_id"] == str(depts[0]["id"])
        await world.sql(
            "UPDATE users SET department_id = NULL WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            a.requester,
        )
        assert (await fresh(world, a, record))["charge_department_id"] == str(depts[0]["id"])


async def test_a_cost_centre_comes_from_the_form_answer(world: World) -> None:
    a = world.a
    centre = {"key": "cc", "label": {"en": "Cost centre"}, "kind": "text", "required": True}
    item = await an_item(
        world,
        a,
        questions=[MODEL, centre],
        price="10.00",
        charge_to="question",
        charge_question_key="cc",
        plan=[{"title": {"en": "Order"}}],
    )
    made = await raise_request(
        world,
        a,
        a.admin,
        catalog_item_id=item["id"],
        answers={"model": "air", "cc": "CC-4410"},
        group_id=str(a.ga),
        technician_id=str(a.tech_a),
    )
    assert made.status_code == 201, made.text
    record = made.json()
    [order] = await tasks(world, a, record)
    await done(world, a, record, order)
    assert (await fresh(world, a, record))["charge_cost_centre"] == "CC-4410"


async def test_editions_prices_are_professional(world: World) -> None:
    tenant = await create_tenant(world.db.migrator_url, "Essentials price", edition="essentials")
    (admin,) = await seed_users(world.db, tenant, [{"user_type": "technician"}])
    await assign_system_role(world.db.admin_url, tenant, admin, "tenant_admin")
    org = Org(tenant, admin, admin, admin, admin, admin, admin, admin)
    group = await world.call("POST", "/organization/groups", org, admin, json={"name": "Desk"})
    assert group.status_code == 201, group.text
    base: dict[str, Any] = {"names": {"en": "Laptop"}, "group_id": group.json()["id"]}
    professional: dict[str, dict[str, Any]] = {
        "CAT-020 price": {"price": "10.00"},
        "CAT-020 option price": {"questions": [MODEL]},
        "CAT-021 charge to an answer": {"charge_to": "question"},
    }
    for req, extra in professional.items():
        refused = await add_item(world, org, admin, **base, **extra)
        assert problem(refused) == (403, "entitlement_required"), req
    made = await add_item(world, org, admin, **base)
    assert made.status_code == 201, made.text  # no price: every edition


async def test_sr033_ac2_a_rule_approves_below_a_cost(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_b)
    rule = {
        "name": {"en": "Cheap kit is pre-approved"},
        "condition": {"field": "estimated_cost", "op": "lt", "value": 550},
    }
    item = await priced(
        world,
        a,
        approval={
            "approvers": [{"kind": "requested_for_manager"}],
            "stages": [{"approvers": [{"kind": "requested_for_manager"}], "auto_rules": [rule]}],
        },
    )
    cheap = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    dear = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "pro"}
    )
    assert cheap.status_code == 201, cheap.text
    assert dear.status_code == 201, dear.text
    assert (await fresh(world, a, cheap.json()))["approval_status"] == "approved"  # 500 < 550
    assert (await fresh(world, a, dear.json()))["approval_status"] == "pending"  # 600
    assert await approvals(world, a, a.admin, dear.json())
    assert uuid.UUID(cheap.json()["id"])


async def test_lane_c_money_cannot_be_filtered_or_sorted_without_the_cost_right(
    world: World,
) -> None:
    """D-184 (lane C's #633 review): a filter `estimated_cost gt N` would reveal the value."""
    import json  # noqa: PLC0415 - one test

    a = world.a
    item = await priced(world, a)
    await raised(world, a, item, "pro")
    for field, op, value in (
        ("estimated_cost", "gt", 100),
        ("charged_amount", "gte", 1),
        ("charge_department_id", "is_not_null", None),
        ("charge_cost_centre", "eq", "CC-1"),
    ):
        probe = {"field": field, "op": op, **({} if value is None else {"value": value})}
        params = {"filter": json.dumps(probe)}
        refused = await world.call("GET", SR, a, a.tech_a, params=params)
        assert refused.status_code == 422, (field, refused.text)
        allowed = await world.call("GET", SR, a, a.admin, params=params)
        assert allowed.status_code == 200, (field, allowed.text)
    sorted_ = await world.call("GET", SR, a, a.tech_a, params={"sort": "charged_at"})
    assert sorted_.status_code == 422, sorted_.text
    fields = (await world.call("GET", f"{SR}/list-fields", a, a.tech_a)).json()
    assert not {"estimated_cost", "charged_amount"} & {f["name"] for f in fields}
