"""Change notifications and reminders on the engine (WP-045d S3; REQ-CHG-091, -103..105).

Lane B's review of the design: approvers without `changes.view` are told through their live
approval (the public side and their own link), requesters see only their own view, a person a
rule names who may not see the change gets nothing, and each reminder is sent once.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.work_items.service import change_reminders
from app.shared.clock import FrozenClock
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import manager_of
from tests.db.test_change_closure_api import _in_review, fresh
from tests.db.test_changes_api import CHG, a_change, move, new_change
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_notifications_api import run_engine

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def sent(world: World, org: Org, record_id: str, code: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT user_id, channel, state, reason, subject, text_body FROM notification_deliveries"
        " WHERE tenant_id = $1 AND record_id = $2 AND event_code = $3",
        org.tenant,
        uuid.UUID(record_id),
        code,
    )
    return [dict(r) for r in rows]


async def _role(world: World, org: Org, item: dict[str, Any], role: str, user: uuid.UUID) -> None:
    now = await fresh(world, org, item)
    set_ = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/roles/{role}",
        org,
        org.admin,
        json={"user_ids": [str(user)]},
        headers={"If-Match": f'"{now["version"]}"', **CONSOLE},
    )
    assert set_.status_code == 200, set_.text


async def _sweep(world: World, org: Org, now: datetime) -> int:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            return await change_reminders.sweep(session, FrozenClock(now))
    finally:
        await database.dispose()


async def _window(world: World, org: Org, item: dict[str, Any], start: datetime) -> None:
    rows = (await world.call("GET", f"{CHG}/{item['id']}/schedule", org, org.admin)).json()
    row = next(r for r in rows if r["stage"] == "implementation")
    saved = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/implementation",
        org,
        org.admin,
        json={
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=2)).isoformat(),
        },
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert saved.status_code == 200, saved.text


async def test_req_chg_104_the_new_owner_and_the_change_manager_hear_without_set_up(
    world: World,
) -> None:
    a = world.a
    item = await a_change(world, a)
    await _role(world, a, item, "change_manager", a.lead)
    now = await fresh(world, a, item)
    assigned = await world.call(
        "POST",
        f"{CHG}/{item['id']}/assign",
        a,
        a.admin,
        json={"group_id": str(a.ga), "technician_id": str(a.tech_a)},
        headers={"If-Match": f'"{now["version"]}"', **CONSOLE},
    )
    assert assigned.status_code == 200, assigned.text
    await run_engine(world, a)
    assert a.tech_a in {d["user_id"] for d in await sent(world, a, item["id"], "change.assigned")}


async def test_lane_b_an_approver_without_changes_view_is_told_with_the_public_side(
    world: World,
) -> None:
    """The requester's manager is a requester only: they still hear of the approval waiting
    for them, with the change's number and title only, never its risk or plans."""
    a = world.a
    await manager_of(world, a.requester, a.requester2)
    item = await a_change(world, a)
    raised = await move(world, a, item, "submission_awaiting_acceptance")
    assert raised.status_code == 200, raised.text
    approvals = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()
    assert [e["approver_id"] for e in approvals["items"]] == [str(a.requester2)]
    await run_engine(world, a)
    told = [
        d
        for d in await sent(world, a, item["id"], "change.approval_requested")
        if d["user_id"] == a.requester2
    ]
    assert {d["channel"] for d in told} == {"in_app", "email"}, told
    assert all(d["reason"] != "no_access" for d in told), told
    [mail] = [d for d in told if d["channel"] == "email"]
    body = (mail["text_body"] or "") + (mail["subject"] or "")
    assert item["display_id"] in body
    assert "approval_link" in body  # their own one-time link, made by the mail sender
    assert "/changes/" not in body  # never the console address they cannot open
    assert "risk" not in body.lower()


async def test_lane_b_a_decided_approval_gives_no_public_side_any_more(world: World) -> None:
    from app.modules.work_items.service.change_notifications import SOURCE  # noqa: PLC0415

    a = world.a
    await manager_of(world, a.requester, a.requester2)
    item = await a_change(world, a)
    await move(world, a, item, "submission_awaiting_acceptance")
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            before = await SOURCE.access(session, a.requester2, uuid.UUID(item["id"]))
        await world.sql(
            "UPDATE work_item_approvals SET state = 'approved'"
            " WHERE tenant_id = $1 AND work_item_id = $2",
            a.tenant,
            uuid.UUID(item["id"]),
        )
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            after = await SOURCE.access(session, a.requester2, uuid.UUID(item["id"]))
    finally:
        await database.dispose()
    assert (before.value, after.value) == ("public", "none")


async def test_req_chg_104_the_requester_sees_only_their_own_view(world: World) -> None:
    """Closed goes to the requester as its status: no plans, no risk words."""
    a = world.a
    item = await _in_review(world, a)
    await world.call(
        "PUT",
        f"{CHG}/{item['id']}/plan/backout",
        a,
        a.admin,
        json={"content": "<p>Secret backout steps</p>"},
        headers=CONSOLE,
    )
    codes = (await world.call("GET", f"{CHG}/settings", a, a.admin)).json()["closure_codes"]
    now = await fresh(world, a, item)
    closed = await world.call(
        "POST",
        f"{CHG}/{item['id']}/moves",
        a,
        a.admin,
        json={"to_status": "review_complete", "closure_code": codes[0]["code"]},
        headers={"If-Match": f'"{now["version"]}"', **CONSOLE},
    )
    assert closed.status_code == 200, closed.text
    await run_engine(world, a)
    told = [
        d for d in await sent(world, a, item["id"], "change.closed") if d["user_id"] == a.requester
    ]
    assert told, "the requester was not told the change closed"
    for d in told:
        body = (d["text_body"] or "") + (d["subject"] or "")
        assert "/changes/" not in body
        assert "Secret backout steps" not in body
        assert "risk" not in body.lower()


async def test_lane_b_a_mention_of_someone_who_cannot_see_it_tells_nobody(world: World) -> None:
    a = world.a
    item = await a_change(world, a)
    note = await world.call(
        "POST",
        f"{CHG}/{item['id']}/conversation",
        a,
        a.admin,
        json={
            "kind": "note",
            "body": f'<p><span data-type="mention" data-id="{a.requester2}">@x</span> look</p>',
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert note.status_code == 201, note.text
    assert str(a.requester2) in [str(u) for u in note.json().get("not_notified", [])]
    await run_engine(world, a)
    assert all(
        d["user_id"] != a.requester2 for d in await sent(world, a, item["id"], "change.mentioned")
    )


async def test_req_chg_105_each_reminder_is_sent_once_and_a_moved_window_reminds_again(
    world: World,
) -> None:
    a = world.a
    made = await new_change(world, a, a.admin, change_type="standard")
    item = made.json()
    await _role(world, a, item, "implementer", a.tech_a)
    start = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0)
    await _window(world, a, item, start)
    before = start - timedelta(minutes=30)
    assert await _sweep(world, a, before) == 1
    assert await _sweep(world, a, before + timedelta(minutes=5)) == 0  # two sweeps, one reminder
    await run_engine(world, a)
    first = await sent(world, a, item["id"], "change.window_reminder")
    assert a.tech_a in {d["user_id"] for d in first}  # AC1: the implementer, with a link
    later = start + timedelta(hours=3)
    await _window(world, a, await fresh(world, a, item), later)
    assert await _sweep(world, a, later - timedelta(minutes=30)) == 1  # moved: a fresh one


async def test_req_chg_105_a_moved_window_s_old_reminder_is_never_sent_late(world: World) -> None:
    a = world.a
    made = await new_change(world, a, a.admin, change_type="standard")
    item = made.json()
    await _role(world, a, item, "implementer", a.tech_a)
    start = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)
    await _window(world, a, item, start)
    assert await _sweep(world, a, start - timedelta(minutes=30)) == 1
    await _window(world, a, await fresh(world, a, item), start + timedelta(days=1))
    await run_engine(world, a)  # the claim was for the old time: nothing goes out
    assert await sent(world, a, item["id"], "change.window_reminder") == []


async def test_req_chg_105_a_canceled_change_is_never_reminded(world: World) -> None:
    a = world.a
    made = await new_change(world, a, a.admin, change_type="standard")
    item = made.json()
    start = (datetime.now(UTC) + timedelta(days=4)).replace(microsecond=0)
    await _window(world, a, item, start)
    canceled = await move(
        world, a, await fresh(world, a, item), "closure_canceled", reason_text="Not needed"
    )
    assert canceled.status_code == 200, canceled.text
    assert await _sweep(world, a, start - timedelta(minutes=30)) == 0  # AC2


async def test_req_chg_103_a_status_rule_reaches_its_people_but_never_one_who_cannot_see_it(
    world: World,
) -> None:
    """Notify on entering a status (REQ-CHG-103): the rule's named staff member hears of it;
    a requester named in the same rule gets nothing, as the event is staff-only (lane B)."""
    a = world.a
    rule = (await world.call("GET", "/notifications/rules", a, a.admin)).json()
    view = next(r for r in rule if r["event_code"] == "change.status_entered")
    keys = ("recipients", "channels", "group_ids")
    saved = await world.call(
        "PUT",
        "/notifications/rules/change.status_entered",
        a,
        a.admin,
        json={
            **{k: view[k] for k in keys},
            "enabled": True,
            "user_ids": [str(a.tech_b), str(a.requester2)],
            "conditions": [
                {"field": "status", "operator": "in", "values": ["submission_awaiting_acceptance"]}
            ],
            "notify_actor": view["notify_actor"],
        },
        headers={"If-Match": f'"{view["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    item = await a_change(world, a)
    await move(world, a, item, "submission_awaiting_acceptance")
    await run_engine(world, a)
    told = await sent(world, a, item["id"], "change.status_entered")
    reached = {d["user_id"] for d in told if d["state"] != "skipped" and d["reason"] is None}
    assert a.tech_b in reached
    assert a.requester2 not in reached


async def test_req_chg_107_a_business_rule_on_changes_sets_the_group_and_names_itself(
    world: World,
) -> None:
    """AC1: a rule on changes that sets the group runs on creation, recorded with its name."""
    from tests.db.test_automation_api import add_rule, set_  # noqa: PLC0415 - shared helpers

    a = world.a
    await add_rule(
        world, a, record_type="change", name="Changes to GA", actions=[set_("group_id", str(a.ga))]
    )
    item = await a_change(world, a)
    assert item["group_id"] == str(a.ga)
    history = (await world.call("GET", f"{CHG}/{item['id']}/history", a, a.admin)).json()["items"]
    ruled = [h for h in history if h.get("source") == "rule"]
    assert [h["automation"]["rule"] for h in ruled] == ["Changes to GA"]
