"""An approver opens what they are asked to approve, read-only, in the portal (QA10-P2-06).

Real PostgreSQL. A requester-only person named as the request's approver (their manager) sees
it in the portal with its answers and requester, the requester's fields only, never technician
fields, and the public conversation but never a private note (WP-047a S4, REQ-SR-043, which
supersedes this test's earlier no-conversation rule); it cannot confirm or reject, and a decided
approval keeps the read (open or decided). Anyone else without reach gets 404; the approver
cannot confirm or reject its delivery.
"""

import uuid

from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.service import portal
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import manager_of, waiting
from tests.db.test_incidents_api import CONSOLE, World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

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
    assert (confirm.status_code, confirm.json()["code"]) == (403, "permission_denied")
    not_done = await world.call(
        "POST",
        f"{PORTAL}/{record['id']}/resolution/reject",
        a,
        a.requester2,
        json={"comment": "Not mine"},
        headers={"If-Match": f'"{body["version"]}"', **CONSOLE},
    )
    assert not_done.status_code == 403, not_done.text
    # REQ-SR-043: the public conversation, never a private note.
    for kind, visibility, words in (
        ("reply", "public", "<p>Which colour would you like?</p>"),
        ("note", "private", "<p>Budget is tight this quarter</p>"),
    ):
        made = await world.call(
            "POST",
            f"/service-requests/{record['id']}/conversation",
            a,
            a.admin,
            json={"kind": kind, "visibility": visibility, "body": words},
            headers=CONSOLE,
        )
        assert made.status_code == 201, made.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        approver = await subject_for(session, a.tenant, a.requester2)
        entries = await portal.conversation(
            session, approver, uuid.UUID(record["id"]), SERVICE_REQUEST
        )
    bodies = " ".join(str(e.body) for e in entries)
    assert "Which colour" in bodies
    assert "Budget is tight" not in bodies
    # Not named on it, no reach: 404. A request whose approver is someone else.
    await manager_of(world, a.requester, a.tech_a)
    theirs = await waiting(world, a)
    assert (await world.call("GET", f"{PORTAL}/{theirs['id']}", a, a.requester2)).status_code == 404
    other = await world.call("GET", f"{PORTAL}/{record['id']}", world.b, world.b.requester)
    assert other.status_code == 404
