"""The approval engine over HTTP (WP-030 s2; REQ-SR-021..025, -027, -028, -061, -063).

Real PostgreSQL with RLS. The requester's manager approves from their inbox; the first decision
decides; a rejection needs a reason; nobody approves their own request; nobody waits on nobody;
the requester withdraws while it waits; a private comment stays with staff.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.work_items.service.approvals import on_user_status_changed, reroute_inactive
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, world
from tests.db.test_service_requests_api import SR, an_item, raise_request

__all__ = ["world"]  # the fixture, re-used

MANAGER = {"approval": {"approvers": [{"kind": "requested_for_manager"}]}}
PORTAL = {"X-SupportX-Client": "portal"}


async def manager_of(world: World, person: uuid.UUID, manager: uuid.UUID) -> None:
    await world.sql("UPDATE users SET manager_id = $1 WHERE id = $2", manager, person)


async def waiting(world: World, org: Org, **item: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made_item = await an_item(world, org, **{**MANAGER, **item})
    made = await raise_request(
        world, org, org.requester, catalog_item_id=made_item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def fresh(world: World, org: Org, record: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{SR}/{record['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def approvals(world: World, org: Org, user: uuid.UUID, record: dict[str, Any]) -> Any:  # noqa: ANN401 - JSON
    found = await world.call("GET", f"{SR}/{record['id']}/approvals", org, user)
    assert found.status_code == 200, found.text
    return found.json()["items"]


async def inbox(world: World, org: Org, user: uuid.UUID) -> list[str]:
    found = await world.call("GET", f"{SR}/my-approvals", org, user)
    assert found.status_code == 200, found.text
    return [a["record_id"] for a in found.json()["items"]]


async def decide(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    approval: dict[str, Any],
    decision: str,
    comment: str | None = None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "POST",
        f"{SR}/{record['id']}/approvals/{approval['id']}/decision",
        org,
        user,
        json={"decision": decision, "comment": comment, **extra},
        headers={"If-Match": f'"{approval["version"]}"', **CONSOLE},
    )


async def test_the_managers_approval_moves_the_request_on(world: World) -> None:
    """REQ-SR-021, -022 AC1, -025 AC2: the manager decides from their inbox; then it moves on."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a, technician_id=str(a.tech_b), technician_after_approval=True)
    assert await inbox(world, a, a.tech_a) == [record["id"]]
    assert await inbox(world, a, a.tech_b) == []
    [entry] = await approvals(world, a, a.tech_a, record)
    assert (entry["approver_id"], entry["origin"], entry["can_decide"]) == (
        str(a.tech_a),
        "manager",
        True,
    )
    approved = await decide(world, a, a.tech_a, record, entry, "approve")
    assert approved.status_code == 200, approved.text
    assert (approved.json()["state"], approved.json()["channel"]) == ("approved", "app")
    after = await fresh(world, a, record)
    assert after["approval_status"] == "approved"
    # The technician the item named waits for the approval, then the usual move to "assigned".
    assert (after["technician_id"], after["status"]) == (str(a.tech_b), "assigned")
    assert await inbox(world, a, a.tech_a) == []
    again = await decide(world, a, a.tech_a, record, approved.json(), "reject", "late")
    assert problem(again) == (409, "approval_closed")


async def test_a_requester_only_manager_approves(world: World) -> None:
    """REQ-SR-022 AC2, -063: no special approver flag; a requester can be the approver."""
    a = world.a
    await manager_of(world, a.requester, a.requester2)
    record = await waiting(world, a)
    [entry] = await approvals(world, a, a.requester2, record)
    approved = await decide(world, a, a.requester2, record, entry, "approve")
    assert approved.status_code == 200, approved.text
    assert (await fresh(world, a, record))["status"] == "new"


async def test_a_rejection_needs_a_reason_and_ends_the_request(world: World) -> None:
    """REQ-SR-028 AC1, REQ-SR-021 AC3."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    [entry] = await approvals(world, a, a.tech_a, record)
    bare = await decide(world, a, a.tech_a, record, entry, "reject", "  ")
    assert bare.status_code == 422, bare.text
    assert bare.json()["errors"][0]["code"] == "reason_required"
    rejected = await decide(world, a, a.tech_a, record, entry, "reject", "Not in budget")
    assert rejected.status_code == 200, rejected.text
    after = await fresh(world, a, record)
    assert (after["status"], after["approval_status"]) == ("rejected", "rejected")


async def test_comments_required_and_private_comments(world: World) -> None:
    """REQ-SR-028 AC2, AC3: a private comment is the staff's and its author's only."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(
        world,
        a,
        approval={"approvers": [{"kind": "requested_for_manager"}], "comments_required": True},
    )
    [entry] = await approvals(world, a, a.tech_a, record)
    silent = await decide(world, a, a.tech_a, record, entry, "approve")
    assert silent.json()["errors"][0]["code"] == "comment_required"
    done = await decide(world, a, a.tech_a, record, entry, "approve", "Budget ok", private=True)
    assert done.status_code == 200, done.text
    [mine] = await approvals(world, a, a.requester, record)
    assert (mine["state"], mine["comment"]) == ("approved", None)
    [staff] = await approvals(world, a, a.admin, record)
    assert staff["comment"] == "Budget ok"


async def test_only_the_approver_decides(world: World) -> None:
    """REQ-SR-025 AC3: anyone else gets 403; outside the record they see nothing."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    [entry] = await approvals(world, a, a.tech_a, record)
    refused = await decide(world, a, a.tech_b, record, entry, "approve")
    assert problem(refused) == (403, "not_an_approver")
    hidden = await world.call("GET", f"{SR}/{record['id']}/approvals", a, a.requester2)
    assert problem(hidden) == (404, "work_item_not_found")


async def test_nobody_waits_on_nobody(world: World) -> None:
    """REQ-SR-023 AC1: no manager → the approval administrators, with the reason."""
    a = world.a
    record = await waiting(world, a)
    [entry] = await approvals(world, a, a.admin, record)
    assert (entry["approver_id"], entry["origin"], entry["route_reason"]) == (
        None,
        "administrators",
        "no_manager",
    )
    assert await inbox(world, a, a.admin) == [record["id"]]  # the admin holds approve_any
    assert await inbox(world, a, a.tech_a) == []
    approved = await decide(world, a, a.admin, record, entry, "approve")
    assert approved.status_code == 200, approved.text


async def test_nobody_approves_their_own_request(world: World) -> None:
    """REQ-SR-027 AC1, AC2: never routed to them; refused if they hold the fallback."""
    a = world.a
    item = await an_item(
        world, a, approval={"approvers": [{"kind": "person", "person_id": str(a.admin)}]}
    )
    made = await raise_request(
        world, a, a.admin, catalog_item_id=item["id"], answers={"model": "air"}
    )
    record = made.json()
    [entry] = await approvals(world, a, a.admin, record)
    assert (entry["origin"], entry["route_reason"], entry["can_decide"]) == (
        "administrators",
        "self_approval_blocked",
        False,
    )
    refused = await decide(world, a, a.admin, record, entry, "approve")
    assert problem(refused) == (403, "approval_segregation")


async def test_self_approval_when_the_item_allows_it(world: World) -> None:
    """REQ-SR-027 AC3: the decision is marked as a self-approval."""
    a = world.a
    item = await an_item(
        world,
        a,
        approval={
            "approvers": [{"kind": "person", "person_id": str(a.requester)}],
            "self_approval": True,
        },
    )
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    record = made.json()
    [entry] = await approvals(world, a, a.requester, record)
    approved = await decide(world, a, a.requester, record, entry, "approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["self_approved"] is True


async def test_the_requester_withdraws_while_it_waits(world: World) -> None:
    """REQ-SR-061 AC1: cancelled as withdrawn; the approvals close; a late decision is refused."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    [entry] = await approvals(world, a, a.tech_a, record)
    stranger = await world.call(
        "POST",
        f"{SR}/{record['id']}/withdraw",
        a,
        a.tech_b,
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert problem(stranger) == (403, "withdraw_not_allowed")
    withdrawn = await world.call(
        "POST",
        f"{SR}/{record['id']}/withdraw",
        a,
        a.requester,
        headers={"If-Match": f'"{record["version"]}"', **PORTAL},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    after = await fresh(world, a, record)
    assert (after["status"], after["approval_status"]) == ("canceled", "withdrawn")
    [closed] = await approvals(world, a, a.tech_a, record)
    assert closed["state"] == "withdrawn"
    late = await decide(world, a, a.tech_a, record, entry, "approve")
    assert problem(late) == (409, "approval_closed")
    assert await inbox(world, a, a.tech_a) == []


async def test_approvals_are_isolated_by_rls(world: World) -> None:
    """CLAUDE.md rule a: tenant B neither reads nor changes tenant A's approvals."""
    a, b = world.a, world.b
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (await session.execute(text("SELECT id FROM work_item_approvals"))).all()
        assert rows == []
        changed = await session.execute(text("UPDATE work_item_approvals SET state = 'approved'"))
        assert changed.rowcount == 0
    foreign = await world.call("GET", f"{SR}/{record['id']}/approvals", b, b.admin)
    assert problem(foreign) == (404, "work_item_not_found")
    assert await inbox(world, b, b.admin) == []
    kept = await world.sql("SELECT state FROM work_item_approvals WHERE tenant_id = $1", a.tenant)
    assert [r["state"] for r in kept] == ["pending"]


async def test_the_resolution_clock_waits_for_the_approval(world: World) -> None:
    """REQ-SR-007 AC1 (D6): paused while awaiting approval, running once approved."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)

    async def resolution_state() -> list[str]:
        rows = await world.sql(
            "SELECT state FROM sla_targets WHERE record_id = $1 AND kind = 'resolution'",
            uuid.UUID(record["id"]),
        )
        return [r["state"] for r in rows]

    assert await resolution_state() == ["paused"]
    [entry] = await approvals(world, a, a.tech_a, record)
    assert (await decide(world, a, a.tech_a, record, entry, "approve")).status_code == 200
    assert await resolution_state() == ["running"]


async def test_a_deactivated_approvers_approvals_go_to_the_fallback(world: World) -> None:
    """REQ-SR-023 AC2: the administrators take them, with the reason; the leaver's inbox empties."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    person = await world.call("GET", f"/users/{a.tech_a}", a, a.admin)
    left = await world.call(
        "POST",
        f"/users/{a.tech_a}/deactivate",
        a,
        a.admin,
        headers={"If-Match": person.headers["ETag"], **CONSOLE},
    )
    assert left.status_code == 200, left.text
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1"
        " AND event_type = 'identity_access.user.status_changed'",
        str(a.tech_a),
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[-1]["envelope"]))
    for _ in range(2):  # a second delivery changes nothing
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            await on_user_status_changed(envelope, session)
    [entry] = await approvals(world, a, a.admin, record)
    assert (entry["approver_id"], entry["origin"], entry["route_reason"]) == (
        None,
        "administrators",
        "approver_inactive",
    )
    assert await inbox(world, a, a.admin) == [record["id"]]


async def test_the_daily_check_reroutes_what_the_event_missed(world: World) -> None:
    """REQ-SR-023 AC3: an approver gone without an event still never holds an approval."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    await world.sql("UPDATE users SET status = 'disabled' WHERE id = $1", a.tech_a)  # no event
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await reroute_inactive(session) == 1
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await reroute_inactive(session) == 0  # nothing left to move
    [entry] = await approvals(world, a, a.admin, record)
    assert (entry["origin"], entry["route_reason"]) == ("administrators", "approver_inactive")


async def test_an_item_that_counts_approval_time_keeps_the_clock_running(world: World) -> None:
    """REQ-SR-007 AC2: with "count approval time" the due date does not move."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a, count_approval_time=True)
    rows = await world.sql(
        "SELECT state FROM sla_targets WHERE record_id = $1 AND kind = 'resolution'",
        uuid.UUID(record["id"]),
    )
    assert [r["state"] for r in rows] == ["running"]
    assert (await fresh(world, a, record))["resolution_due_at"] is not None
