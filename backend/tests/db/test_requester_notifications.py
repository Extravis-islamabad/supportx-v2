"""The requester hears about their own requests (QA10, root cause by lane B).

Real PostgreSQL and the notification engine. A request raised by the requester acknowledges
them (they are the actor, and still told); approval, rejection (with the approver's comment),
withdrawal and fulfilment reach the requester; an incident they raise themself is acknowledged
too. Other events keep leaving the actor out.
"""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, decide, manager_of, waiting
from tests.db.test_changes_api import CHG, a_change
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_notifications_api import MAIL, run_engine

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

SR = "/service-requests"


async def told(world: World, org: Org, record_id: str, user: uuid.UUID) -> dict[str, list[str]]:
    """{event code: channels} delivered (or queued) to one person for one record."""
    rows = await world.sql(
        "SELECT event_code, channel FROM notification_deliveries"
        " WHERE tenant_id = $1 AND record_id = $2 AND user_id = $3 AND state <> 'suppressed'"
        " ORDER BY created_at",
        org.tenant,
        uuid.UUID(record_id),
        user,
    )
    found: dict[str, list[str]] = {}
    for r in rows:
        found.setdefault(r["event_code"], []).append(r["channel"])
    return found


async def test_a_request_is_acknowledged_and_its_approval_told(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    [entry] = await approvals(world, a, a.tech_a, record)
    assert (await decide(world, a, a.tech_a, record, entry, "approve")).status_code == 200
    await run_engine(world, a, settings=MAIL)
    news = await told(world, a, record["id"], a.requester)
    assert sorted(news["service_request.received"]) == ["email", "in_app"]  # though the actor
    assert sorted(news["service_request.approved"]) == ["email", "in_app"]


async def test_a_rejection_tells_the_requester_with_the_approvers_comment(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    [entry] = await approvals(world, a, a.tech_a, record)
    rejected = await decide(world, a, a.tech_a, record, entry, "reject", "Over the budget")
    assert rejected.status_code == 200, rejected.text
    await run_engine(world, a, settings=MAIL)
    mails = await world.sql(
        "SELECT m.text_body FROM notification_deliveries d JOIN mail_messages m ON m.id = d.mail_id"
        " WHERE d.tenant_id = $1 AND d.record_id = $2 AND d.user_id = $3"
        " AND d.event_code = 'service_request.rejected'",
        a.tenant,
        uuid.UUID(record["id"]),
        a.requester,
    )
    assert any("Over the budget" in (m["text_body"] or "") for m in mails)


async def test_the_requester_is_told_their_withdrawal(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record: dict[str, Any] = await waiting(world, a)
    withdrawn = await world.call(
        "POST",
        f"{SR}/{record['id']}/withdraw",
        a,
        a.requester,
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    await run_engine(world, a, settings=MAIL)
    news = await told(world, a, record["id"], a.requester)
    assert "service_request.withdrawn" in news


async def test_an_incident_the_requester_raised_themself_is_acknowledged(world: World) -> None:
    a = world.a
    made = await world.call(
        "POST",
        "/portal/incidents",
        a,
        a.requester,
        json={"subject": "Printer jams", "description": "<p>Every page</p>"},
        headers={"Idempotency-Key": str(uuid.uuid4()), "X-SupportX-Client": "portal"},
    )
    assert made.status_code == 201, made.text
    await run_engine(world, a, settings=MAIL)
    news = await told(world, a, made.json()["id"], a.requester)
    assert "incident.created" in news


async def test_e1_a_request_ready_to_fulfil_tells_its_group_once_in_the_app(world: World) -> None:
    """D-154 "E1 follows d": its last task done with nobody on it, each person of its group
    gets one in-app notice; the requester hears nothing of it."""
    from tests.db.test_service_requests_api import an_item, raise_request  # noqa: PLC0415 - shared helpers

    a = world.a
    item = await an_item(world, a, plan=[{"title": {"en": "Order the laptop"}}])
    record = (
        await raise_request(
            world,
            a,
            a.admin,
            catalog_item_id=item["id"],
            answers={"model": "air"},
            group_id=str(a.ga),
        )
    ).json()
    listed = await world.call("GET", f"{SR}/{record['id']}/tasks", a, a.admin)
    [task] = listed.json()["items"]
    ticked = await world.call(
        "PATCH",
        f"{SR}/{record['id']}/tasks/{task['id']}",
        a,
        a.admin,
        json={"status": "done"},
        headers={"If-Match": f'"{task["version"]}"', **CONSOLE},
    )
    assert ticked.status_code == 200, ticked.text
    await run_engine(world, a, settings=MAIL)
    for member in (a.tech_a, a.tech_c):  # GA's people
        news = await told(world, a, record["id"], member)
        assert news.get("service_request.ready_to_fulfil") == ["in_app"], news
    assert "service_request.ready_to_fulfil" not in await told(world, a, record["id"], a.admin)


async def test_a_reply_on_a_request_reaches_its_requester_and_carries_the_reply(
    world: World,
) -> None:
    """Lane B's #359 finding: a request's replies had no notice, so they stayed queued and the
    requester never got the technician's words. Now as on incidents."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    replied = await world.call(
        "POST",
        f"{SR}/{record['id']}/conversation",
        a,
        a.admin,
        json={"kind": "reply", "body": "<p>Your laptop is on its way.</p>"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert replied.status_code == 201, replied.text
    entry_id = replied.json()["entry"]["id"]
    await run_engine(world, a, settings=MAIL)
    news = await told(world, a, record["id"], a.requester)
    assert "email" in news["service_request.public_reply"]
    # The requester's e-mail carries this reply: its delivery follows that e-mail.
    carried = await world.sql(
        "SELECT count(*) AS n FROM notification_deliveries WHERE tenant_id = $1"
        " AND entry_id = $2 AND channel = 'email' AND 'requester' = ANY(reasons)",
        a.tenant,
        uuid.UUID(entry_id),
    )
    assert carried[0]["n"] == 1


async def test_a_reply_on_a_change_is_settled_not_e_mailed_never_left_queued(
    world: World,
) -> None:
    """The coordinator, 2026-11-11: a change's reply notice is off by default (a staff record);
    with no e-mail made, #359's settle step marks the reply not e-mailed at once."""
    a = world.a
    change = await a_change(world, a)
    replied = await world.call(
        "POST",
        f"{CHG}/{change['id']}/conversation",
        a,
        a.admin,
        json={"kind": "reply", "body": "<p>Scheduled for Saturday.</p>"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert replied.status_code == 201, replied.text
    entry_id = replied.json()["entry"]["id"]
    await run_engine(world, a, settings=MAIL)
    (row,) = await world.sql(
        "SELECT delivery_state, delivery_reason FROM work_item_conversations WHERE id = $1",
        uuid.UUID(entry_id),
    )
    assert (row["delivery_state"], row["delivery_reason"]) == ("failed", "not_notified")
