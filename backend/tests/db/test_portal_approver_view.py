"""An approver opens what they are asked to approve, read-only, in the portal (QA10-P2-06).

Real PostgreSQL. A requester-only person named as the request's approver (their manager) sees
it in the portal with its answers and requester, the requester's fields only, never technician
fields; anyone else without reach gets 404; the approver cannot confirm or reject its delivery.
"""

from tests.db.test_approvals_api import manager_of, waiting
from tests.db.test_incidents_api import CONSOLE, World, world

__all__ = ["world"]  # the fixture, re-used

PORTAL = "/portal/service-requests"


async def test_qa10_p2_06_the_approver_opens_the_request_read_only(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.requester2)  # a requester-only manager approves
    record = await waiting(world, a)
    shown = await world.call("GET", f"{PORTAL}/{record['id']}", a, a.requester2)
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert body["reach"] == "approver"
    assert body["answers"] == {"model": "air"}
    assert body["requester_id"] == str(a.requester)
    assert "technician_id" not in body
    assert "group_id" not in body
    # Read-only: the delivery is the requester's to confirm.
    confirm = await world.call(
        "POST",
        f"{PORTAL}/{record['id']}/resolution/confirm",
        a,
        a.requester2,
        headers={"If-Match": f'"{body["version"]}"', **CONSOLE},
    )
    assert confirm.status_code in {403, 404, 409}, confirm.text
    # Not named on it, no reach: 404. A request whose approver is someone else.
    await manager_of(world, a.requester, a.tech_a)
    theirs = await waiting(world, a)
    assert (await world.call("GET", f"{PORTAL}/{theirs['id']}", a, a.requester2)).status_code == 404
    other = await world.call("GET", f"{PORTAL}/{record['id']}", world.b, world.b.requester)
    assert other.status_code == 404
