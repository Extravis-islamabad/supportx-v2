"""Service requests in the portal (WP-030 D9; REQ-SR-051, -062). Real PostgreSQL with RLS.

The requester sees their own requests with plain statuses (awaiting approval, not approved),
the item's answers, and the fulfilment's steps with internal names hidden; anyone else's request
reads as not found.
"""

import uuid
from typing import Any

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, decide, manager_of
from tests.db.test_fulfilment_api import PLAN, done, tasks
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_service_requests_api import SR, an_item, raise_request

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

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


async def test_the_requester_confirms_receipt_once_it_is_fulfilled(world: World) -> None:
    """REQ-SR-059: fulfilled reads as 'resolved'; confirming closes it."""
    a = world.a
    item = await an_item(world, a, plan=PLAN[:1])
    record = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()
    early = await world.call("POST", f"{PORTAL}/{record['id']}/resolution/confirm", a, a.requester)
    assert problem(early)[0] == 409  # nothing to confirm yet
    # Someone is on it first (D-154 "E1 follows d": nobody, and it would only be ready).
    current = (await world.call("GET", f"{SR}/{record['id']}", a, a.admin)).json()
    assigned = await world.call(
        "POST",
        f"{SR}/{record['id']}/assign",
        a,
        a.admin,
        json={"group_id": str(a.ga), "technician_id": str(a.tech_a)},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert assigned.status_code == 200, assigned.text
    [task] = await tasks(world, a, record)
    await done(world, a, record, task)
    fulfilled = (await world.call("GET", f"{PORTAL}/{record['id']}", a, a.requester)).json()
    assert fulfilled["portal_status"] == "resolved"
    confirmed = await world.call(
        "POST", f"{PORTAL}/{record['id']}/resolution/confirm", a, a.requester
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["portal_status"] == "closed"
