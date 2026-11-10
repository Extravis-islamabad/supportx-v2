"""A catalogue item says how long a request usually takes (Haider, 2026-11-10; F2).

Real PostgreSQL. The item's own SLA policy gives it; without one, the requests' fallback policy
does; a policy without a resolution target, or none at all, says nothing.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_service_requests_api import an_item

__all__ = ["world"]  # the fixture, re-used

POLICIES = "/sla/record-types/service_request/policies"


async def policy(world: World, org: Org, targets: list[dict[str, Any]]) -> dict[str, Any]:
    made = await world.call(
        "POST",
        POLICIES,
        org,
        org.admin,
        json={
            "name": f"Delivery {uuid.uuid4().hex[:6]}",
            "conditions": {"field": "priority", "op": "eq", "value": "p1"},
            "targets": targets,
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def delivery(world: World, org: Org, item: dict[str, Any], who: uuid.UUID) -> Any:  # noqa: ANN401 - JSON
    read = await world.call("GET", f"/catalog/items/{item['id']}", org, who)
    assert read.status_code == 200, read.text
    return read.json()["expected_delivery"]


async def test_the_items_policy_says_how_long_in_working_time(world: World) -> None:
    a = world.a
    days = await policy(
        world, a, [{"kind": "resolution", "priority": None, "amount": 3, "unit": "business_days"}]
    )
    item = await an_item(world, a, sla_policy_id=days["id"])
    assert await delivery(world, a, item, a.requester) == {
        "amount": 3,
        "unit": "business_days",
        "around_the_clock": False,
    }


async def test_a_policy_with_no_resolution_target_says_nothing(world: World) -> None:
    a = world.a
    respond_only = await policy(
        world, a, [{"kind": "first_response", "priority": None, "amount": 4, "unit": "hours"}]
    )
    item = await an_item(world, a, sla_policy_id=respond_only["id"])
    assert await delivery(world, a, item, a.requester) is None


async def test_without_its_own_policy_the_fallback_applies(world: World) -> None:
    a = world.a
    listed = await world.call("GET", POLICIES, a, a.admin)
    assert listed.status_code == 200, listed.text
    fallback = next(p for p in listed.json() if p["fallback"])
    rows = [t for t in fallback["targets"] if t["kind"] == "resolution"]
    p2 = next((t for t in rows if t["priority"] == "p2"), None) or next(
        (t for t in rows if t["priority"] is None), None
    )
    item = await an_item(world, a)  # default priority p2, no policy of its own
    expected = (
        None
        if p2 is None or p2.get("amount") is None
        else {
            "amount": p2["amount"],
            "unit": p2["unit"],
            "around_the_clock": p2.get("source") == "around_the_clock",
        }
    )
    assert await delivery(world, a, item, a.requester) == expected
