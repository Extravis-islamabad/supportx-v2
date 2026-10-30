"""A reply's delivery state follows its e-mail (WP-024 session 3; REQ-INC-059, REQ-INC-060).

The incident world of test_incidents_api, the engine as the dispatch consumer runs it, and the
one mail sender with a fake SMTP. Covers: waiting while mail is not set up (and the 7-day give
up, never sent late), queued, retrying, sent and failed with the server's reason, order (a late
report never moves a reply back), resend (once, audited by the route), and the composer's status.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.notifications.service import resend
from app.modules.notifications.service.engine import expire_waiting, send_waiting
from app.shared.events import EventEnvelope
from app.shared.mail.infra import smtp
from app.shared.mail.service.outgoing import deliver
from tests.db.test_conversation_api import say
from tests.db.test_incidents_api import Org, World, world
from tests.db.test_notifications_api import MAIL, NO_MAIL, run_engine

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]


class FakeSmtp:
    """The SMTP server's answer for the next send."""

    def __init__(self) -> None:
        self.answer: Exception | None = None
        self.sent: list[EmailMessage] = []

    async def __call__(self, settings: smtp.SmtpSettings, message: EmailMessage) -> None:
        del settings
        if self.answer is not None:
            raise self.answer
        self.sent.append(message)


async def _reply(world: World, org: Org) -> tuple[dict[str, Any], dict[str, Any]]:
    item = await world.create(org, org.admin, subject="Printer jams")
    made = await say(world, org, org.admin, item, kind="reply", body="<p>Try tray 2.</p>")
    assert made.status_code == 201, made.text
    return item, made.json()["entry"]


async def _entry(world: World, entry_id: str) -> dict[str, Any]:
    (row,) = await world.sql(
        "SELECT delivery_state, delivery_reason, version FROM work_item_conversations"
        " WHERE id = $1",
        uuid.UUID(entry_id),
    )
    return dict(row)


async def _requester_mail(world: World, entry_id: str) -> uuid.UUID:
    rows = await world.sql(
        "SELECT mail_id FROM notification_deliveries WHERE entry_id = $1 AND channel = 'email'"
        " AND 'requester' = ANY(reasons) AND mail_id IS NOT NULL ORDER BY created_at DESC",
        uuid.UUID(entry_id),
    )
    return uuid.UUID(str(rows[0]["mail_id"]))


async def _send(world: World, org: Org, mail_id: uuid.UUID, server: FakeSmtp) -> str:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            return await deliver(session, MAIL, mail_id, send=server)
    finally:
        await database.dispose()


async def _in_session(world: World, org: Org, work: Any) -> Any:  # noqa: ANN401 - the work's result
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            return await work(session)
    finally:
        await database.dispose()


async def test_req_inc_060_a_reply_waits_while_mail_is_not_set_up(world: World) -> None:
    org = world.a
    _, entry = await _reply(world, org)
    assert (entry["delivery_state"], entry["delivery_reason"]) == (
        "waiting",
        "mail_not_configured",
    )
    await run_engine(world, org, settings=NO_MAIL)
    assert (await _entry(world, entry["id"]))["delivery_state"] == "waiting"


async def test_req_inc_059_queued_retrying_sent_in_order(world: World) -> None:
    org = world.a
    _, entry = await _reply(world, org)
    await run_engine(world, org, settings=MAIL)
    queued = await _entry(world, entry["id"])
    assert (queued["delivery_state"], queued["delivery_reason"]) == ("queued", None)
    mail_id = await _requester_mail(world, entry["id"])
    server = FakeSmtp()
    server.answer = smtp.TemporaryFailure(code="server_busy")
    assert await _send(world, org, mail_id, server) == "queued"
    await run_engine(world, org, settings=MAIL)
    retrying = await _entry(world, entry["id"])
    assert (retrying["delivery_state"], retrying["delivery_reason"]) == ("retrying", "server_busy")
    assert retrying["version"] > queued["version"]  # a stale screen's resend is refused
    server.answer = None
    await world.sql("UPDATE mail_messages SET next_attempt_at = now() WHERE id = $1", mail_id)
    assert await _send(world, org, mail_id, server) == "sent"
    await run_engine(world, org, settings=MAIL)
    assert (await _entry(world, entry["id"]))["delivery_state"] == "sent"
    # A late, older report never moves a sent reply back.
    late = EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "system.mail.state_changed",
            "schema_version": 1,
            "tenant_id": str(org.tenant),
            "aggregate_type": "mail_message",
            "aggregate_id": str(mail_id),
            "occurred_at": datetime.now(UTC).isoformat(),
            "actor": {"type": "system", "id": "mail"},
            "payload": {
                "mail_id": str(mail_id),
                "kind": "notification",
                "state": "failed",
                "failure": "gave_up",
                "at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            },
        }
    )
    from app.modules.notifications.service.engine import mail_changed  # noqa: PLC0415 - one use

    await _in_session(world, org, lambda s: mail_changed(s, late))
    assert (await _entry(world, entry["id"]))["delivery_state"] == "sent"


async def test_req_inc_059_a_refusal_fails_with_its_reason_and_resends_once(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = world.a
    _, entry = await _reply(world, org)
    await run_engine(world, org, settings=MAIL)
    mail_id = await _requester_mail(world, entry["id"])
    server = FakeSmtp()
    server.answer = smtp.PermanentFailure(code="recipient_refused")
    assert await _send(world, org, mail_id, server) == "failed"
    await run_engine(world, org, settings=MAIL)
    failed = await _entry(world, entry["id"])
    assert (failed["delivery_state"], failed["delivery_reason"]) == ("failed", "recipient_refused")

    monkeypatch.setattr(resend, "get_settings", lambda: MAIL)
    actor = type("Actor", (), {"tenant_id": org.tenant, "user_id": org.admin})()
    await _in_session(world, org, lambda s: resend.resend_entry(s, uuid.UUID(entry["id"]), actor))
    again = await _entry(world, entry["id"])
    assert (again["delivery_state"], again["delivery_reason"]) == ("queued", None)
    rows = await world.sql(
        "SELECT resent_from, resent_by, state FROM notification_deliveries"
        " WHERE entry_id = $1 AND resent_from IS NOT NULL",
        uuid.UUID(entry["id"]),
    )
    assert [(r["resent_by"], r["state"]) for r in rows] == [(org.admin, "queued")]
    # A double click: nothing failed any more, so nothing is sent twice.
    with pytest.raises(resend.DeliveryNotFailed):
        await _in_session(
            world, org, lambda s: resend.resend_entry(s, uuid.UUID(entry["id"]), actor)
        )


async def test_resend_while_mail_is_still_not_set_up_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = world.a
    _, entry = await _reply(world, org)
    await run_engine(world, org, settings=MAIL)
    mail_id = await _requester_mail(world, entry["id"])
    server = FakeSmtp()
    server.answer = smtp.PermanentFailure(code="message_refused")
    await _send(world, org, mail_id, server)
    await run_engine(world, org, settings=MAIL)
    monkeypatch.setattr(resend, "get_settings", lambda: NO_MAIL)
    actor = type("Actor", (), {"tenant_id": org.tenant, "user_id": org.admin})()
    with pytest.raises(resend.MailStillNotConfigured):
        await _in_session(
            world, org, lambda s: resend.resend_entry(s, uuid.UUID(entry["id"]), actor)
        )


async def test_req_inc_060_after_seven_days_it_fails_visibly_and_is_never_sent_late(
    world: World,
) -> None:
    org = world.a
    _, entry = await _reply(world, org)
    await run_engine(world, org, settings=NO_MAIL)
    await world.sql(
        "UPDATE notification_deliveries SET created_at = now() - interval '8 days'"
        " WHERE entry_id = $1",
        uuid.UUID(entry["id"]),
    )
    expired = await _in_session(world, org, expire_waiting)
    assert expired >= 1
    gave_up = await _entry(world, entry["id"])
    assert (gave_up["delivery_state"], gave_up["delivery_reason"]) == (
        "failed",
        "not_sent_in_time",
    )
    # Mail is set up later: other waiting mail goes, the reply's old e-mail does not.
    await _in_session(world, org, lambda s: send_waiting(s, MAIL))
    rows = await world.sql(
        "SELECT state, reason FROM notification_deliveries"
        " WHERE entry_id = $1 AND channel = 'email'",
        uuid.UUID(entry["id"]),
    )
    assert {(r["state"], r["reason"]) for r in rows} == {("failed", "not_sent_in_time")}


async def test_the_timeline_hears_of_each_change(world: World) -> None:
    """Live (rule c): each applied change is an outbox event with codes only."""
    org = world.a
    _, entry = await _reply(world, org)
    await run_engine(world, org, settings=MAIL)
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.conversation.delivery_changed' AND aggregate_id = $2",
        org.tenant,
        entry["id"],
    )
    payloads = [json.loads(r["envelope"])["payload"] for r in rows]
    assert [(p["delivery_state"], p["delivery_reason"]) for p in payloads] == [("queued", None)]
    assert "@" not in json.dumps(payloads)


async def test_the_composer_sees_mail_status_and_who_can_fix_it(world: World) -> None:
    org = world.a
    staff = await world.call("GET", "/notifications/mail-status", org, org.tech_a)
    assert staff.status_code == 200, staff.text
    body = staff.json()
    assert set(body) == {"mail_configured", "waiting", "who_can_fix"}
    assert all(set(p) == {"id", "display_name"} for p in body["who_can_fix"])  # never addresses
    assert str(org.admin) in {p["id"] for p in body["who_can_fix"]}
    requester = await world.call("GET", "/notifications/mail-status", org, org.requester)
    assert requester.status_code == 403
    assert requester.json()["code"] == "mail_status_staff_only"


async def test_the_mail_state_event_names_no_one(world: World) -> None:
    org = world.a
    _, entry = await _reply(world, org)
    await run_engine(world, org, settings=MAIL)
    mail_id = await _requester_mail(world, entry["id"])
    await _send(world, org, mail_id, FakeSmtp())
    (row,) = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'system.mail.state_changed'"
        " AND aggregate_id = $1",
        str(mail_id),
    )
    payload = json.loads(row["envelope"])["payload"]
    assert set(payload) == {"mail_id", "kind", "state", "failure", "at"}


async def test_a_reply_the_requester_wrote_never_moves(world: World) -> None:
    """Lane A's `received` (a reply that came in by mail) is not ours to deliver."""
    from app.modules.work_items.service.notifications import SOURCE  # noqa: PLC0415 - one use

    org = world.a
    item, entry = await _reply(world, org)
    await world.sql(
        "UPDATE work_item_conversations SET delivery_state = 'received', delivery_reason = NULL"
        " WHERE id = $1",
        uuid.UUID(entry["id"]),
    )
    await _in_session(
        world,
        org,
        lambda s: SOURCE.delivery_changed(
            s,
            record_id=uuid.UUID(item["id"]),
            entry_id=uuid.UUID(entry["id"]),
            state="failed",
            reason="gave_up",
            at=datetime.now(UTC) + timedelta(minutes=1),
        ),
    )
    assert (await _entry(world, entry["id"]))["delivery_state"] == "received"
