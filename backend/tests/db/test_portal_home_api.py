"""The portal home (WP-032 D1; REQ-PRT-002, REQ-CAT-027). Real Postgres.

The summary counts only the person's own open requests (incidents and service requests), the
approvals waiting for them and their open tasks. "Most requested" items come in request order,
only items the person may see, never one nobody asked for.
"""

import uuid

from tests.db.test_approvals_api import manager_of
from tests.db.test_incident_settings_api import admin_write
from tests.db.test_incidents_api import Org, World, world
from tests.db.test_service_requests_api import an_item, raise_request

__all__ = ["world"]  # the fixture, re-used

SUMMARY = "/portal/summary"
POPULAR = "/catalog/items/popular"


async def counts(world: World, org: Org, user: uuid.UUID) -> dict[str, object]:
    found = await world.call("GET", SUMMARY, org, user)
    assert found.status_code == 200, found.text
    body = found.json()
    return {
        "open": {e["status"]: e["count"] for e in body["open_by_status"]},
        "approvals": body["approvals"],
        "tasks": body["tasks"],
    }


async def test_the_summary_counts_only_my_own_open_work(world: World) -> None:
    a, b = world.a, world.b
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    await world.create(a, a.admin, requester_id=str(a.requester))  # an incident for them
    await world.create(a, a.admin, requester_id=str(a.requester2))  # someone else's
    mine = await counts(world, a, a.requester)
    assert mine == {
        "open": {"received": 1, "awaiting_approval": 1},
        "approvals": 0,
        "tasks": 0,
    }
    # The manager has the approval waiting; another person and another tenant see nothing.
    assert (await counts(world, a, a.tech_a))["approvals"] == 1
    assert (await counts(world, a, a.requester2))["open"] == {"received": 1}
    assert (await counts(world, b, b.requester))["open"] == {}


async def test_most_requested_items_in_request_order_and_only_visible_ones(world: World) -> None:
    a = world.a
    quiet = await an_item(world, a, status="published")
    busy = await an_item(world, a, status="published")
    never = await an_item(world, a, status="published")
    for _ in range(3):
        sent = await raise_request(
            world, a, a.requester, catalog_item_id=busy["id"], answers={"model": "pro"}
        )
        assert sent.status_code == 201, sent.text
    sent = await raise_request(
        world, a, a.requester, catalog_item_id=quiet["id"], answers={"model": "air"}
    )
    assert sent.status_code == 201, sent.text
    found = await world.call("GET", POPULAR, a, a.requester)
    assert found.status_code == 200, found.text
    ids = [i["id"] for i in found.json()]
    assert ids == [busy["id"], quiet["id"]]
    assert never["id"] not in ids  # nobody asked for it
    # A retired item is no longer offered, however popular.
    retired = await world.call(
        "PATCH",
        f"/catalog/items/{busy['id']}",
        a,
        a.admin,
        json={"status": "retired"},
        headers={"If-Match": f'"{busy["version"]}"'},
    )
    assert retired.status_code == 200, retired.text
    again = await world.call("GET", POPULAR, a, a.requester)
    assert [i["id"] for i in again.json()] == [quiet["id"]]
    assert (await world.call("GET", POPULAR, world.b, world.b.requester)).json() == []


async def test_a_request_says_when_to_expect_it_only_if_the_tenant_shows_it(world: World) -> None:
    """REQ-PRT-006 AC2 (the "what happens next" page), within WP-028 D5's setting."""
    a = world.a
    item = await an_item(world, a, status="published")
    made = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()
    path = f"/portal/service-requests/{made['id']}"
    hidden = (await world.call("GET", path, a, a.requester)).json()
    assert hidden["resolution_due_at"] is None
    switched = await admin_write(
        world, a, "PATCH", "/service-requests/settings", {"portal_show_due_time": True}
    )
    assert switched.status_code == 200, switched.text
    shown = (await world.call("GET", path, a, a.requester)).json()
    assert shown["resolution_due_at"] is not None
