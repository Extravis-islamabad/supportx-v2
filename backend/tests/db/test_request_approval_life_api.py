"""Request approval reminders, escalation and clarification (WP-047a S3a; REQ-SR-034, -036, -037).

Real PostgreSQL with RLS. The sweep runs with a frozen clock over approvals whose opening time is
set by SQL, so each acceptance criterion is a date: opened Monday 09:00 (UTC: nobody here has a
time zone), reminded Wednesday, Thursday and Friday at 10:00, escalated on Monday the 30th.

The coordinator's conditions: an escalation with nobody to take it goes to the administrators,
recorded (2); the sweep is claim-once and idempotent (5); the question and the answer are shown
only to the asker and the request's staff (4).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.work_items.infra.models import WorkItemApproval
from app.modules.work_items.service import clarifications
from app.modules.work_items.service import request_approval_reminders as sweeper
from app.modules.work_items.service.approvals import issue_links
from app.shared.clock import FrozenClock
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, decide, fresh, manager_of
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_notifications_api import MAIL, run_engine
from tests.db.test_service_requests_api import an_item, raise_request

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

SR = "/service-requests"
PORTAL = "/portal/service-requests"
MONDAY = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
WEDNESDAY_TEN = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
NEXT_MONDAY_TEN = datetime(2026, 11, 30, 10, 0, tzinfo=UTC)


async def _raised(world: World, org: Org, approver: uuid.UUID, **approval: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    item = await an_item(
        world,
        org,
        approval={"approvers": [{"kind": "person", "person_id": str(approver)}], **approval},
    )
    made = await raise_request(
        world, org, org.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    record = dict(made.json())
    await world.sql(
        "UPDATE work_item_approvals SET created_at = $1 WHERE tenant_id = $2 AND work_item_id = $3",
        MONDAY,
        org.tenant,
        uuid.UUID(record["id"]),
    )
    return record


async def _sweep(world: World, org: Org, now: datetime) -> int:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        return await sweeper.sweep(session, FrozenClock(now))


async def _opened(world: World, approval_id: str) -> int:
    """How many times the approval's "opened" event went out (each one mails its approver)."""
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'work_items.approval.changed'"
    )
    return sum(
        1
        for r in rows
        if (p := json.loads(r["envelope"])["payload"])["approval_id"] == approval_id
        and p["change"] == "opened"
    )


async def _history(world: World, org: Org, record: dict[str, Any], field: str) -> list[Any]:
    rows = await world.sql(
        "SELECT new_value FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = $3 ORDER BY occurred_at",
        org.tenant,
        uuid.UUID(record["id"]),
        field,
    )
    return [json.loads(r["new_value"]) for r in rows]


async def _deliver_answers(world: World, org: Org, record: dict[str, Any]) -> None:
    """Hand the record's conversation events to the clarification consumer, twice (idempotent)."""
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'work_items.conversation.added'"
    )
    envelopes = [
        EventEnvelope.model_validate(json.loads(r["envelope"]))
        for r in rows
        if json.loads(r["envelope"])["payload"]["work_item_id"] == record["id"]
    ]
    for _ in range(2):
        for envelope in envelopes:
            async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
                await clarifications.on_conversation_added(envelope, session)


async def _settle_other_sweeps(world: World, org: Org) -> None:
    """Earlier tests' approvals in the shared world are left pending: close them out."""
    await world.sql(
        "UPDATE work_item_approvals SET state = 'withdrawn' WHERE tenant_id = $1"
        " AND state = 'pending'",
        org.tenant,
    )


async def test_ac1_sent_monday_reminded_wednesday_at_ten_once(world: World) -> None:
    """034 AC1 and condition 5: the first reminder Wednesday 10:00; a second sweep sends nothing."""
    a = world.a
    await _settle_other_sweeps(world, a)
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    assert await _sweep(world, a, WEDNESDAY_TEN - timedelta(minutes=1)) == 0
    assert await _sweep(world, a, WEDNESDAY_TEN) == 1
    assert await _sweep(world, a, WEDNESDAY_TEN + timedelta(minutes=5)) == 0  # claimed once
    assert await _opened(world, row["id"]) == 2  # opened, then the reminder
    [said] = await _history(world, a, record, sweeper.REMINDER_FIELD)
    assert (said["stage"], said["number"]) == (1, 1)
    # The manual reminder's own cap (REQ-SR-042) does not count the automatic ones.
    assert await _history(world, a, record, "approval_reminder") == []


async def test_ac2_after_the_last_reminder_the_backup_is_added_and_the_primary_stays(
    world: World,
) -> None:
    """034 AC2 and 036 AC2: the backup gets it next to the approver; the first to decide wins."""
    a = world.a
    await _settle_other_sweeps(world, a)
    record = await _raised(world, a, a.tech_a, backup_id=str(a.tech_b))
    assert await _sweep(world, a, NEXT_MONDAY_TEN) == 1
    rows = await approvals(world, a, a.admin, record)
    primary = next(r for r in rows if r["approver_id"] == str(a.tech_a))
    added = next(r for r in rows if r["approver_id"] == str(a.tech_b))
    assert (primary["state"], added["state"]) == ("pending", "pending")
    assert (added["origin"], added["escalated_from_id"]) == ("escalated", primary["id"])
    # Escalated once: a later sweep may remind the added approver (their own plan), never
    # escalate the primary again.
    await _sweep(world, a, NEXT_MONDAY_TEN + timedelta(days=1))
    later = await approvals(world, a, a.admin, record)
    assert sum(1 for r in later if r["escalated_from_id"] == primary["id"]) == 1
    [said] = await _history(world, a, record, sweeper.ESCALATED_FIELD)
    assert (said["to"], said["count"], said["fallback"]) == ("backup", 1, False)
    audit = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2 AND object_id = $3",
        a.tenant,
        sweeper.ESCALATED,
        record["id"],
    )
    assert len(audit) == 1
    assert (await decide(world, a, a.tech_b, record, added, "approve")).status_code == 200
    rows = {r["id"]: r for r in await approvals(world, a, a.admin, record)}
    assert rows[primary["id"]]["state"] == "not_needed"  # the family's one vote was cast
    assert (await fresh(world, a, record))["approval_status"] == "approved"


async def test_condition_2_nobody_to_escalate_to_goes_to_the_administrators(world: World) -> None:
    a = world.a
    await _settle_other_sweeps(world, a)
    record = await _raised(world, a, a.tech_a)  # no backup
    assert await _sweep(world, a, NEXT_MONDAY_TEN) == 1
    added = next(r for r in await approvals(world, a, a.admin, record) if r["escalated_from_id"])
    assert (added["origin"], added["route_reason"], added["approver_id"]) == (
        "administrators",
        "no_escalation_target",
        None,
    )
    [said] = await _history(world, a, record, sweeper.ESCALATED_FIELD)
    assert said["fallback"] is True


async def test_the_approvers_manager_and_none(world: World) -> None:
    a = world.a
    await _settle_other_sweeps(world, a)
    await manager_of(world, a.tech_a, a.lead)
    to_manager = await _raised(world, a, a.tech_a, escalate_to="approver_manager")
    reminders_only = await _raised(world, a, a.tech_a, escalate_to="none")
    assert await _sweep(world, a, NEXT_MONDAY_TEN) == 1  # only the first escalates
    rows = await approvals(world, a, a.admin, to_manager)
    assert any(r["approver_id"] == str(a.lead) and r["origin"] == "escalated" for r in rows)
    assert len(await approvals(world, a, a.admin, reminders_only)) == 1


async def test_ac3_a_decided_stage_gets_no_more_reminders(world: World) -> None:
    a = world.a
    await _settle_other_sweeps(world, a)
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    assert (await decide(world, a, a.tech_a, record, row, "approve")).status_code == 200
    assert await _sweep(world, a, WEDNESDAY_TEN) == 0
    assert await _sweep(world, a, NEXT_MONDAY_TEN) == 0


async def _ask(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    row: dict[str, Any],
    question: str = "Which colour do you need?",
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "POST",
        f"{SR}/{record['id']}/approvals/{row['id']}/clarification",
        org,
        user,
        json={"question": question, **extra},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )


async def test_037_a_question_reaches_the_portal_pauses_reminders_and_its_answer_returns(
    world: World,
) -> None:
    """037 AC1-AC3 and condition 4."""
    a = world.a
    await _settle_other_sweeps(world, a)
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    asked = await _ask(world, a, a.tech_a, record, row)
    assert asked.status_code == 200, asked.text
    shown = asked.json()
    assert shown["state"] == "pending"
    assert shown["clarification"]["state"] == "open"
    assert "colour" in shown["clarification"]["question"]
    # AC1: in the requester's portal conversation, as a public reply.
    talk = await world.call("GET", f"{PORTAL}/{record['id']}/conversation", a, a.requester)
    assert talk.status_code == 200, talk.text
    assert any("colour" in e["body"] for e in talk.json()["items"])
    # AC3: no reminder while it is open.
    assert await _sweep(world, a, WEDNESDAY_TEN) == 0
    # Condition 4: the requester's view of the approval has no texts.
    [seen] = await approvals(world, a, a.requester, record)
    assert seen["clarification"]["question"] is None
    # AC2: the requester's reply answers it and the approver can decide.
    reply = await world.call(
        "POST",
        f"{PORTAL}/{record['id']}/replies",
        a,
        a.requester,
        json={"body": "<p>Silver, please</p>"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert reply.status_code == 201, reply.text
    await _deliver_answers(world, a, record)  # the consumer, on the conversation's event
    [after] = await approvals(world, a, a.tech_a, record)
    assert after["clarification"]["state"] == "answered"
    assert "Silver" in after["clarification"]["answer"]
    paused = await world.sql(
        "SELECT paused_seconds FROM work_item_approvals WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(row["id"]),
    )
    assert paused[0]["paused_seconds"] >= 0
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'work_items.approval.clarification'"
    )
    changes = [
        json.loads(e["envelope"])["payload"]
        for e in events
        if json.loads(e["envelope"])["payload"]["approval_id"] == row["id"]
    ]
    assert [c["change"] for c in changes] == ["asked", "answered"]
    assert all("Silver" not in json.dumps(c) for c in changes)  # IDs and codes only
    assert (await decide(world, a, a.tech_a, record, after, "approve")).status_code == 200


async def test_037_one_open_question_and_the_technician_needs_one(world: World) -> None:
    a = world.a
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    nobody = await _ask(world, a, a.tech_a, record, row, addressee="technician")
    assert problem(nobody)[0] == 422
    first = await _ask(world, a, a.tech_a, record, row)
    assert first.status_code == 200, first.text
    again = await _ask(world, a, a.tech_a, record, first.json())
    assert problem(again) == (409, "clarification_open")
    stranger = await _ask(world, a, a.tech_b, record, first.json())
    assert problem(stranger) == (403, "not_an_approver")
    # A decision ends the open question.
    assert (await decide(world, a, a.tech_a, record, first.json(), "approve")).status_code == 200
    [done] = await approvals(world, a, a.tech_a, record)
    assert done["clarification"]["state"] == "decided"


async def test_the_schedule_is_a_request_setting_within_limits(world: World) -> None:
    a = world.a
    current = await world.call("GET", f"{SR}/settings", a, a.admin)
    body = current.json()
    assert (
        body["approval_reminder_after_days"],
        body["approval_reminder_count"],
        body["approval_reminder_minute"],
    ) == (2, 3, 600)
    wrong = await world.call(
        "PATCH",
        f"{SR}/settings",
        a,
        a.admin,
        json={"approval_reminder_count": 11},
        headers={"If-Match": f'"{body["version"]}"', **CONSOLE},
    )
    assert problem(wrong)[0] == 422
    saved = await world.call(
        "PATCH",
        f"{SR}/settings",
        a,
        a.admin,
        json={"approval_reminder_after_days": 3, "approval_reminder_minute": 540},
        headers={"If-Match": f'"{body["version"]}"', **CONSOLE},
    )
    assert saved.status_code == 200, saved.text
    assert (
        saved.json()["approval_reminder_after_days"],
        saved.json()["approval_reminder_minute"],
    ) == (3, 540)
    back = await world.call(
        "PATCH",
        f"{SR}/settings",
        a,
        a.admin,
        json={"approval_reminder_after_days": 2, "approval_reminder_minute": 600},
        headers={"If-Match": f'"{saved.json()["version"]}"', **CONSOLE},
    )
    assert back.status_code == 200, back.text
    incidents = await world.call("GET", "/incidents/settings", a, a.admin)
    refused = await world.call(
        "PATCH",
        "/incidents/settings",
        a,
        a.admin,
        json={"approval_reminder_count": 1},
        headers={"If-Match": f'"{incidents.json()["version"]}"', **CONSOLE},
    )
    assert problem(refused)[0] == 422


async def test_clarifications_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    assert (await _ask(world, a, a.tech_a, record, row)).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        mine = await session.scalar(
            text("SELECT count(*) FROM approval_clarifications WHERE work_item_id = :w"),
            {"w": record["id"]},
        )
    assert mine == 1
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.scalar(
            text("SELECT count(*) FROM approval_clarifications WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert seen == 0
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO approval_clarifications (id, tenant_id, work_item_id,"
                    " approval_id, asked_by, addressee, addressee_id, question_entry_id, asked_at)"
                    " VALUES (:i, :t, :w, :p, :u, 'requester', :u, :i, now())"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": a.tenant,
                    "w": record["id"],
                    "p": row["id"],
                    "u": a.tech_a,
                },
            )


async def test_a_reminder_revokes_the_earlier_link_and_the_new_one_decides(world: World) -> None:
    """Lane C's #604 review: one live no-sign-in link per approval, never one per reminder."""
    a = world.a
    await _settle_other_sweeps(world, a)
    record = await _raised(world, a, a.tech_a)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        rows = list(
            await session.scalars(
                select(WorkItemApproval).where(WorkItemApproval.work_item_id == record["id"])
            )
        )
        [earlier] = (await issue_links(session, rows)).values()  # the first mail's link
    assert await _sweep(world, a, WEDNESDAY_TEN) == 1
    await run_engine(world, a, settings=MAIL)  # the reminder's mail is dispatched
    refused = await world.call(
        "POST",
        "/action-links/use",
        a,
        a.tech_a,
        json={"token": earlier, "body": {"decision": "approve"}},
        headers=CONSOLE,
    )
    assert problem(refused) == (409, "action_link_revoked")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        rows = list(
            await session.scalars(
                select(WorkItemApproval).where(WorkItemApproval.work_item_id == record["id"])
            )
        )
        [fresh_link] = (await issue_links(session, rows)).values()
    used = await world.call(
        "POST",
        "/action-links/use",
        a,
        a.tech_a,
        json={"token": fresh_link, "body": {"decision": "approve"}},
        headers=CONSOLE,
    )
    assert used.status_code == 200, used.text
