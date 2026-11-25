"""Service request channels (WP-047a S4; REQ-SR-017, -038, -043, -044). Real PostgreSQL.

- SR-017: a request mailbox makes requests of its item, channel e-mail; required answers missing
  make it wait (awaiting answers, no approval yet); the requester's completion submits it; an
  item no longer requestable holds the mail (never an incident); a plain mailbox still makes
  incidents.
- SR-038: a reply to the approval mail decides only from the approver, vouched for, while the
  approval is pending and the reply is clear; anything else changes nothing and is audited.
- SR-043: an approver sees the approver questions' answers, never one hidden from approvers.
- SR-044: an approval node's timeout expires the level (links revoked, `approval_expired`
  afterwards) unless a decision got there first; a trigger's ask never asks twice.
"""

import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.errors import Conflict
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.integrations.domain.mailboxes import Outcome
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.service.inbound import process
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import approval_mail, approvals, workflow_approvals
from conftest import make_settings
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_automation_triggers_api import drain
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_service_requests_api import an_item, raise_request

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

SETTINGS = make_settings()
OWN = ("requests@alpha.test",)
PORTAL = "/portal/service-requests"


def _db(world: World) -> Database:
    return Database(create_engine(world.db.app_url, application_name="tests"))


async def _email(world: World, user: uuid.UUID) -> str:
    rows = await world.sql("SELECT email FROM users WHERE id = $1", user)
    return str(rows[0]["email"])


def _mail(sender: str, subject: str, body: str = "I need a laptop.", **headers: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = OWN[0]
    message["Subject"] = subject
    message["Message-ID"] = f"<{uuid.uuid4().hex}@mail.alpha.test>"
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content(body)
    return message.as_bytes()


async def _mailbox(
    world: World, database: Database, *, item_id: uuid.UUID | None, address: str
) -> uuid.UUID:
    async with database.tenant_session(TenantContext(world.a.tenant)) as session:
        box = Mailbox(
            tenant_id=world.a.tenant,
            address=address,
            host="imap.alpha.test",
            port=993,
            username=address,
            group_id=world.a.ga,
            creates="service_request" if item_id else "incident",
            catalog_item_id=item_id,
        )
        session.add(box)
        await session.flush()
        return box.id


async def _process(world: World, database: Database, box_id: uuid.UUID, raw: bytes) -> Outcome:
    async with database.tenant_session(TenantContext(world.a.tenant)) as session:
        mailbox = await session.get(Mailbox, box_id)
        assert mailbox is not None
        found = await process(session, SETTINGS, mailbox, raw, own_addresses=OWN)
        assert found is not None
        return found


# --- SR-017 -----------------------------------------------------------------------------------


async def test_sr_017_mail_makes_a_waiting_request_its_requester_completes(world: World) -> None:
    a = world.a
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    database = _db(world)
    try:
        box = await _mailbox(
            world, database, item_id=uuid.UUID(item["id"]), address="access@alpha.test"
        )
        sender = await _email(world, a.requester)
        assert await _process(world, database, box, _mail(sender, "Laptop please")) is (
            Outcome.CREATED
        )
    finally:
        await database.dispose()
    (made,) = await world.sql(
        "SELECT id, type, channel, status, approval_status, catalog_item_id, version"
        " FROM work_items WHERE tenant_id = $1 AND channel = 'email' AND type = 'service_request'",
        a.tenant,
    )
    assert (made["status"], made["approval_status"]) == ("awaiting_requester", "awaiting_answers")
    assert str(made["catalog_item_id"]) == item["id"]
    rows = await world.sql("SELECT id FROM work_item_approvals WHERE work_item_id = $1", made["id"])
    assert rows == []  # AC3: no approval before the answers
    # AC2: the portal asks only what is missing; anyone else gets 404.
    missing = await world.call("GET", f"{PORTAL}/{made['id']}/missing-answers", a, a.requester)
    assert missing.status_code == 200, missing.text
    assert missing.json()["missing"] == ["model"]
    other = await world.call("GET", f"{PORTAL}/{made['id']}/missing-answers", a, a.requester2)
    assert other.status_code == 404
    done = await world.call(
        "PUT",
        f"{PORTAL}/{made['id']}/missing-answers",
        a,
        a.requester,
        json={"answers": {"model": "air"}},
        headers={"If-Match": f'"{missing.json()["version"]}"', **CONSOLE},
    )
    assert done.status_code == 200, done.text
    (after,) = await world.sql(
        "SELECT status, approval_status FROM work_items WHERE id = $1", made["id"]
    )
    assert (after["status"], after["approval_status"]) == ("awaiting_approval", "pending")
    opened = await world.sql(
        "SELECT state FROM work_item_approvals WHERE work_item_id = $1", made["id"]
    )
    assert [r["state"] for r in opened] == ["pending"]  # the item's approval starts now
    again = await world.call("GET", f"{PORTAL}/{made['id']}/missing-answers", a, a.requester)
    assert again.status_code == 404  # no longer waiting


async def test_sr_017_an_item_no_longer_requestable_holds_the_mail(world: World) -> None:
    a = world.a
    item = await an_item(world, a)
    database = _db(world)
    try:
        box = await _mailbox(
            world, database, item_id=uuid.UUID(item["id"]), address="retired@alpha.test"
        )
        await world.sql(
            "UPDATE catalog_items SET status = 'retired' WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            uuid.UUID(item["id"]),
        )
        sender = await _email(world, a.requester)
        outcome = await _process(world, database, box, _mail(sender, "Old item"))
        plain = await _mailbox(world, database, item_id=None, address="plain@alpha.test")
        incident = await _process(world, database, plain, _mail(sender, "Printer jams"))
    finally:
        await database.dispose()
    assert outcome is Outcome.HELD  # never an incident instead (lane B's rule)
    assert incident is Outcome.CREATED  # a plain mailbox still makes incidents
    made = await world.sql(
        "SELECT type FROM work_items WHERE tenant_id = $1 AND subject = 'Printer jams'", a.tenant
    )
    assert [r["type"] for r in made] == ["incident"]


# --- SR-038 -----------------------------------------------------------------------------------


async def _waiting_request(world: World, org: Org) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A request waiting on tech_b's approval: (record, approval row, approver)."""
    item = await an_item(
        world, org, approval={"approvers": [{"kind": "person", "person_id": str(org.tech_b)}]}
    )
    made = await raise_request(
        world, org, org.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    record_id = uuid.UUID(made.json()["id"])
    (row,) = await world.sql(
        "SELECT id FROM work_item_approvals WHERE work_item_id = $1 AND state = 'pending'",
        record_id,
    )
    return record_id, uuid.UUID(str(row["id"])), org.tech_b


async def _reply(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    record_id: uuid.UUID,
    approver: uuid.UUID,
    *,
    sender: uuid.UUID | None,
    verified: bool = True,
    text: str,
) -> tuple[str | None, bool]:
    """The reply's outcome code (None: applied) and whether its sender is answered."""

    async def mails(*_: Any, **__: Any) -> list[tuple[uuid.UUID, uuid.UUID, datetime]]:  # noqa: ANN401
        return [(record_id, approver, datetime.now(UTC) + timedelta(minutes=1))]

    monkeypatch.setattr(approval_mail, "mail_recipients_for", mails)
    database = _db(world)
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            found = await approval_mail.TARGET.decide_from_mail(
                session,
                thread_ids=["<approval@mail.alpha.test>"],
                sender_id=sender,
                sender_verified=verified,
                text=text,
            )
    finally:
        await database.dispose()
    assert found is not None
    return found.reason, found.answer_sender


async def test_sr_038_a_clear_reply_from_the_approver_decides_once(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    record_id, row_id, approver = await _waiting_request(world, a)
    # Lane B's condition 1: an unverified or foreign sender is never answered (no backscatter).
    assert await _reply(world, monkeypatch, record_id, approver, sender=a.tech_c, text="ok") == (
        approval_mail.WRONG_SENDER,
        False,
    )
    assert await _reply(
        world,
        monkeypatch,
        record_id,
        approver,
        sender=approver,
        verified=False,
        text="Approved",
    ) == (approval_mail.NOT_VERIFIED, False)
    assert await _reply(
        world, monkeypatch, record_id, approver, sender=approver, text="approve only if cheaper"
    ) == (approval_mail.UNCLEAR, True)
    applied = await _reply(
        world, monkeypatch, record_id, approver, sender=approver, text="Approved, thanks"
    )
    assert applied == (None, True)  # AC1
    (row,) = await world.sql("SELECT state, channel FROM work_item_approvals WHERE id = $1", row_id)
    assert (row["state"], row["channel"]) == ("approved", "email_reply")
    # Condition 1: a second reply changes nothing.
    assert await _reply(
        world, monkeypatch, record_id, approver, sender=approver, text="Reject"
    ) == (approval_mail.ALREADY_DECIDED, True)
    audit = await world.sql(
        "SELECT action, details->>'reason' AS reason, actor_id FROM audit_entries"
        " WHERE tenant_id = $1"
        " AND object_id = $2 AND action LIKE 'service_request.approval_mail_%' ORDER BY id",
        a.tenant,
        str(record_id),
    )
    assert [(r["action"].rsplit("_", 1)[1], r["reason"]) for r in audit] == [
        ("ignored", "wrong_sender"),
        ("ignored", "sender_not_verified"),
        ("ignored", "unclear"),
        ("decided", None),
        ("ignored", "already_decided"),
    ]
    # Lane B's condition 3: the decision is the approver's own act in the audit log.
    assert [r["actor_id"] for r in audit if r["action"].endswith("decided")] == [approver]


# --- SR-043 -----------------------------------------------------------------------------------


async def test_sr_043_an_approver_never_sees_an_answer_hidden_from_approvers(
    world: World,
) -> None:
    a = world.a
    item = await an_item(
        world,
        a,
        questions=[
            {"key": "model", "label": {"en": "Model"}, "kind": "text", "required": True},
            {
                "key": "salary",
                "label": {"en": "Salary band"},
                "kind": "text",
                "shown_to": ["requester", "technician"],  # hidden from approvers (AC2)
            },
        ],
        approval={"approvers": [{"kind": "person", "person_id": str(a.requester2)}]},
    )
    made = await raise_request(
        world,
        a,
        a.requester,
        catalog_item_id=item["id"],
        answers={"model": "air", "salary": "B3"},
    )
    assert made.status_code == 201, made.text
    shown = await world.call("GET", f"{PORTAL}/{made.json()['id']}", a, a.requester2)
    assert shown.status_code == 200, shown.text
    assert shown.json()["reach"] == "approver"
    assert shown.json()["answers"] == {"model": "air"}


# --- SR-044 -----------------------------------------------------------------------------------


async def _open_level(world: World) -> tuple[uuid.UUID, uuid.UUID, str]:
    a = world.a
    item = await an_item(world, a)
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    record_id, instance_id, command = uuid.UUID(made.json()["id"]), uuid.uuid4(), "c1"
    database = _db(world)
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            record = await session.get(WorkItem, record_id)
            assert record is not None
            await workflow_approvals.open_for(
                session,
                record,
                instance_id=instance_id,
                command=command,
                approvers={"user_ids": [str(a.tech_b)]},
                rule="any",
            )
    finally:
        await database.dispose()
    return record_id, instance_id, command


async def test_sr_044_a_timeout_expires_the_level_unless_decided_first(world: World) -> None:
    a = world.a
    record_id, instance_id, command = await _open_level(world)
    database = _db(world)
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            record = await session.get(WorkItem, record_id)
            assert record is not None
            port = await workflow_approvals.expire_for(
                session, record, instance_id=instance_id, command=command
            )
        assert port == workflow_approvals.TIMED_OUT
        (row,) = await world.sql(
            "SELECT id, state, expires_at, version FROM work_item_approvals"
            " WHERE workflow_instance_id = $1",
            instance_id,
        )
        assert row["state"] == "expired"
        assert row["expires_at"] is not None
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            approver = await subject_for(session, a.tenant, a.tech_b)
            with pytest.raises(Conflict) as late:
                await approvals.decide(
                    session,
                    approver,
                    SERVICE_REQUEST,
                    record_id,
                    uuid.UUID(str(row["id"])),
                    decision=rules.Decision.APPROVE,
                    comment=None,
                    private=False,
                    expected_version=int(row["version"]),
                    channel=rules.DecisionChannel.APP,
                    source="ui",
                )
        assert late.value.instance_code == "approval_expired"
        # A level decided before its timeout keeps the decision.
        record2, instance2, command2 = await _open_level(world)
        await world.sql(
            "UPDATE work_item_approvals SET state = 'approved' WHERE workflow_instance_id = $1",
            instance2,
        )
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            found = await session.get(WorkItem, record2)
            assert found is not None
            first = await workflow_approvals.expire_for(
                session, found, instance_id=instance2, command=command2
            )
        assert first == workflow_approvals.APPROVED
    finally:
        await database.dispose()


async def test_sr_044_a_rules_ask_never_asks_twice_while_pending(world: World) -> None:
    a = world.a
    item = await an_item(world, a)
    trigger = await world.call(
        "POST",
        "/automation/triggers",
        a,
        a.admin,
        json={
            "record_type": "service_request",
            "name": "Ask the budget holder",
            "state": "enabled",
            "events": ["created", "updated"],
            "actions": [{"kind": "start_approval", "approvers": {"user_ids": [str(a.tech_b)]}}],
        },
    )
    assert trigger.status_code == 201, trigger.text
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    await drain(world, a)
    record_id = uuid.UUID(made.json()["id"])
    asks = await world.sql(
        "SELECT purpose, state, trigger_id FROM work_item_approvals WHERE work_item_id = $1",
        record_id,
    )
    assert [(r["purpose"], r["state"]) for r in asks] == [("ad_hoc", "pending")]
    assert str(asks[0]["trigger_id"]) == trigger.json()["id"]
    # A second save while the ask is pending: no second ask (the coordinator's guard).
    current = await world.call("GET", f"/service-requests/{record_id}", a, a.admin)
    saved = await world.call(
        "PATCH",
        f"/service-requests/{record_id}",
        a,
        a.admin,
        json={"subject": "New laptop for Sara (urgent)"},
        headers={"If-Match": f'"{current.json()["version"]}"', **CONSOLE},
    )
    assert saved.status_code == 200, saved.text
    await drain(world, a)
    again = await world.sql("SELECT id FROM work_item_approvals WHERE work_item_id = $1", record_id)
    assert len(again) == 1
    # The request itself never moved for the ask.
    (status,) = await world.sql("SELECT status FROM work_items WHERE id = $1", record_id)
    assert status["status"] in {"new", "assigned"}
