"""Service requests in the portal (WP-030 D9; REQ-SR-051, -062). Real PostgreSQL with RLS.

The requester sees their own requests with plain statuses (awaiting approval, not approved),
the item's answers, and the fulfilment's steps with internal names hidden; anyone else's request
reads as not found.
"""

import uuid
from typing import Any

from tests.db.test_approvals_api import approvals, decide, manager_of
from tests.db.test_fulfilment_api import PLAN
from tests.db.test_incidents_api import Org, World, problem, world
from tests.db.test_service_requests_api import an_item, raise_request

__all__ = ["world"]  # the fixture, re-used

PORTAL = "/portal/service-requests"


async def mine(world: World, org: Org, user: uuid.UUID) -> list[dict[str, Any]]:
    found = await world.call("GET", PORTAL, org, user)
    assert found.status_code == 200, found.text
    return list(found.json()["items"])


async def test_a_requester_follows_their_request_in_plain_words(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(
        world, a, plan=PLAN, approval={"approvers": [{"kind": "requested_for_manager"}]}
    )
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    record = made.json()
    [listed] = await mine(world, a, a.requester)
    assert (listed["display_id"], listed["portal_status"], listed["answers"]) == (
        record["display_id"],
        "awaiting_approval",
        {"model": "air"},
    )
    assert await mine(world, a, a.requester2) == []
    hidden = await world.call("GET", f"{PORTAL}/{record['id']}", a, a.requester2)
    assert problem(hidden) == (404, "work_item_not_found")
    empty = (await world.call("GET", f"{PORTAL}/{record['id']}/steps", a, a.requester)).json()
    assert (empty["items"], empty["total"]) == ([], 0)  # no tasks before the approval

    [entry] = await approvals(world, a, a.tech_a, record)
    assert (await decide(world, a, a.tech_a, record, entry, "approve")).status_code == 200
    steps = (await world.call("GET", f"{PORTAL}/{record['id']}/steps", a, a.requester)).json()
    assert [(s["position"], s["title"], s["done"]) for s in steps["items"]] == [
        (1, "Order the laptop", False),
        (2, None, False),  # internal: "step 2 of 3" only
        (3, "Send a welcome note", False),
    ]
    assert (steps["done"], steps["total"]) == (0, 3)
    after = (await world.call("GET", f"{PORTAL}/{record['id']}", a, a.requester)).json()
    assert after["portal_status"] == "received"


async def test_a_rejected_request_reads_as_not_approved(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    record = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()
    [entry] = await approvals(world, a, a.tech_a, record)
    rejected = await decide(world, a, a.tech_a, record, entry, "reject", "No budget")
    assert rejected.status_code == 200, rejected.text
    found = (await world.call("GET", f"{PORTAL}/{record['id']}", a, a.requester)).json()
    assert found["portal_status"] == "rejected"
