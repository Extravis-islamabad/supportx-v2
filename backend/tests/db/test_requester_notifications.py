"""The requester hears about their own requests (QA10, root cause by lane B).

Real PostgreSQL and the notification engine. A request raised by the requester acknowledges
them (they are the actor, and still told); approval, rejection (with the approver's comment),
withdrawal and fulfilment reach the requester; an incident they raise themself is acknowledged
too. Other events keep leaving the actor out.
"""

import uuid
from typing import Any

import pytest

from tests.db.test_approvals_api import approvals, decide, manager_of, waiting
from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_notifications_api import MAIL, run_engine

pytestmark = pytest.mark.db

__all__ = ["world"]  # the fixture, re-used

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
