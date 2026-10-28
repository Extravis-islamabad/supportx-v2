"""Incoming mail into records, once (WP-024; REQ-INC-023/024/027, REQ-NTF-023, REQ-ADM-067).

Real PostgreSQL (the ledger, RLS, people) with a fake record owner registered on the inbound port,
so these pin what integrations decides; the incident side is tested with lane A's code.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.integrations.domain.mailboxes import PER_SENDER_LIMIT, AfterFetch, Outcome
from app.modules.integrations.infra.imap import FetchedMessage, MailboxUnavailableError
from app.modules.integrations.infra.models import Mailbox, MailFetched
from app.modules.integrations.service.fetching import fetch_mailbox
from app.modules.integrations.service.inbound import NotWaiting, process
from app.modules.integrations.service.mailboxes import discard_mail, release_mail, waiting_mail
from app.modules.notifications.infra.models import NotificationDelivery
from app.shared.files.keyring import KeyRing
from app.shared.mail.infra.models import MailMessage
from app.shared.mail.ports import (
    CreatedRecord,
    FoundRecord,
    InboundRefused,
    register_inbound_target,
    unregister_inbound_target,
)
from conftest import create_tenant, make_settings
from tests.db.test_users_api import seed_users
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

SETTINGS = make_settings()
OWN = ("it@acme.test", "support@supportx.test")


@dataclass
class FakeIncidents:
    """The incident side, in memory."""

    record_type: str = "incident"
    records: dict[str, FoundRecord] = field(default_factory=dict)
    created: list[dict[str, object]] = field(default_factory=list)
    replies: list[dict[str, object]] = field(default_factory=list)
    refuse: str | None = None

    async def find_record(
        self, session: object, *, tokens: Sequence[str], record_ids: Sequence[uuid.UUID]
    ) -> FoundRecord | None:
        del session
        by_id = {r.record_id: r for r in self.records.values()}
        return next((self.records[t] for t in tokens if t in self.records), None) or next(
            (by_id[i] for i in record_ids if i in by_id), None
        )

    async def create_from_mail(self, session: object, **values: object) -> CreatedRecord:
        del session
        if self.refuse:
            raise InboundRefused(self.refuse, {"field": "category"})
        self.created.append(values)
        return CreatedRecord("incident", uuid.uuid4(), f"INC-{len(self.created)}")

    async def reply_from_mail(
        self, session: object, record: FoundRecord, **values: object
    ) -> CreatedRecord | None:
        del session
        self.replies.append({"record": record.display_id, **values})
        return None


@dataclass
class World:
    db: ThrowawayDatabase
    database: Database
    tenant: uuid.UUID
    known: uuid.UUID
    mailbox: uuid.UUID
    incidents: FakeIncidents


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    tenant = await create_tenant(migrated_db.migrator_url, "Mail In")
    (known,) = await seed_users(
        migrated_db, tenant, [{"email": "sara@acme.test", "display_name": "Sara"}]
    )
    database = Database(create_engine(migrated_db.app_url, application_name="test"))
    async with database.tenant_session(TenantContext(tenant)) as session:
        box = Mailbox(
            tenant_id=tenant,
            address="it@acme.test",
            host="imap.acme.test",
            port=993,
            username="it@acme.test",
            allowed_domains=["acme.test"],
        )
        session.add(box)
        await session.flush()
        mailbox_id = box.id
    incidents = FakeIncidents()
    register_inbound_target(incidents)
    try:
        yield World(migrated_db, database, tenant, known, mailbox_id, incidents)
    finally:
        unregister_inbound_target("incident")
        await database.dispose()


def _mail(sender: str = "Sara <sara@acme.test>", **headers: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "it@acme.test"
    message["Subject"] = headers.pop("Subject", "Printer jams")
    message["Message-ID"] = headers.pop("Message_ID", f"<{uuid.uuid4().hex}@mail.acme.test>")
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content(headers.pop("body", "It jams.\n\nOn Mon, IT wrote:\n> old"))
    return message.as_bytes()


async def _process(world: World, raw: bytes) -> Outcome | None:
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        mailbox = await session.get(Mailbox, world.mailbox)
        assert mailbox is not None
        return await process(session, SETTINGS, mailbox, raw, own_addresses=OWN)


async def _ledger(world: World) -> list[MailFetched]:
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        return list(await session.scalars(select(MailFetched).order_by(MailFetched.created_at)))


async def test_a_known_sender_creates_one_incident_even_when_fetched_twice(world: World) -> None:
    raw = _mail()
    assert await _process(world, raw) is Outcome.CREATED
    assert await _process(world, raw) is None  # REQ-ADM-067 AC2: the same message, once
    assert len(world.incidents.created) == 1
    created = world.incidents.created[0]
    assert created["requester_id"] == world.known
    assert created["subject"] == "Printer jams"
    assert "It jams." in str(created["body_html"])
    (row,) = await _ledger(world)
    assert (row.outcome, row.record_type) == ("created", "incident")


async def test_a_reply_lands_on_its_incident_without_the_quote(world: World) -> None:
    world.incidents.records["INC-7"] = FoundRecord(
        "incident", uuid.uuid4(), "INC-7", frozenset({world.known})
    )
    outcome = await _process(world, _mail(Subject="Re: [INC-7] Printer jams (still)"))
    assert outcome is Outcome.REPLIED
    (reply,) = world.incidents.replies
    assert reply["record"] == "INC-7"
    assert reply["automatic"] is False
    assert reply["body_html"] == "<p>It jams.</p>"  # the quoted history is not kept


async def test_a_reply_that_lost_its_token_finds_the_record_by_the_mail_it_answers(
    world: World,
) -> None:
    """REQ-INC-023 AC2: In-Reply-To names a notification SupportX sent about INC-9."""
    record = FoundRecord("incident", uuid.uuid4(), "INC-9", frozenset({world.known}))
    world.incidents.records["INC-9"] = record
    sent = "<notify-1@supportx.test>"
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        mail = MailMessage(
            tenant_id=world.tenant,
            kind="notification",
            language="en",
            recipients=["sara@acme.test"],
            subject="[INC-9] Printer jams",
            state="sent",
            message_id=sent,
        )
        session.add(mail)
        await session.flush()
        session.add(
            NotificationDelivery(
                tenant_id=world.tenant,
                event_id=uuid.uuid4(),
                event_code="incident_updated",
                record_type="incident",
                record_id=record.record_id,
                display_id="INC-9",
                user_id=world.known,
                reasons=["requester"],
                channel="email",
                state="sent",
                mail_id=mail.id,
            )
        )
    outcome = await _process(world, _mail(Subject="Re: Printer jams", In_Reply_To=sent))
    assert outcome is Outcome.REPLIED
    assert [r["record"] for r in world.incidents.replies] == ["INC-9"]


async def test_an_out_of_office_is_recorded_and_wakes_nothing(world: World) -> None:
    """REQ-INC-024 AC2."""
    world.incidents.records["INC-7"] = FoundRecord(
        "incident", uuid.uuid4(), "INC-7", frozenset({world.known})
    )
    raw = _mail(Subject="Auto: [INC-7] away", Auto_Submitted="auto-replied")
    assert await _process(world, raw) is Outcome.AUTOMATIC
    assert [r["automatic"] for r in world.incidents.replies] == [True]
    assert world.incidents.created == []


async def test_strangers_follow_the_mailbox_policy(world: World) -> None:
    """REQ-INC-027: an allowed domain makes a requester; elsewhere is refused politely."""
    assert await _process(world, _mail("New Person <new@acme.test>")) is Outcome.CREATED
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        made = await conn.fetchrow(
            "SELECT user_type, can_sign_in FROM users WHERE tenant_id = $1 AND email = $2",
            world.tenant,
            "new@acme.test",
        )
    finally:
        await conn.close()
    assert made is not None
    assert (made["user_type"], made["can_sign_in"]) == ("requester", False)
    assert await _process(world, _mail("Who <who@elsewhere.test>")) is Outcome.REJECTED
    ledger = await _ledger(world)
    assert [r.outcome for r in ledger] == ["created", "rejected"]
    assert ledger[1].reason == "unknown_sender"


async def test_our_own_mail_and_floods_create_nothing(world: World) -> None:
    """REQ-NTF-023: a loop with ourselves, or two systems answering each other."""
    assert await _process(world, _mail("support@supportx.test")) is Outcome.OWN_ADDRESS
    for _ in range(PER_SENDER_LIMIT):
        await _process(world, _mail())
    assert await _process(world, _mail()) is Outcome.HELD
    assert len(world.incidents.created) == PER_SENDER_LIMIT


async def test_a_refusal_is_held_with_its_code_for_an_admin(world: World) -> None:
    world.incidents.refuse = "validation_failed"
    assert await _process(world, _mail()) is Outcome.HELD
    (row,) = await _ledger(world)
    assert (row.reason, row.reason_params) == ("validation_failed", {"field": "category"})


async def test_the_ledger_stays_in_its_tenant(world: World) -> None:
    await _process(world, _mail())
    other = await create_tenant(world.db.migrator_url, "Other Mail")
    async with world.database.tenant_session(TenantContext(other)) as session:
        assert (await session.scalar(text("SELECT count(*) FROM mail_fetched"))) == 0
        assert (await session.scalar(text("SELECT count(*) FROM mailboxes"))) == 0


@dataclass
class FakeReader:
    """A mailbox on a mail server, in memory."""

    messages: list[tuple[str, bytes]]
    marked: list[tuple[str, str]] = field(default_factory=list)
    fail: str | None = None

    async def new_messages(self, limit: int = 50) -> list[FetchedMessage]:
        if self.fail:
            raise MailboxUnavailableError(self.fail)
        seen = {uid for uid, _ in self.marked}
        return [FetchedMessage(uid, raw) for uid, raw in self.messages if uid not in seen][:limit]

    async def done(self, uid: str, after: AfterFetch, folder: str | None = None) -> None:
        del folder
        self.marked.append((uid, after.value))

    async def close(self) -> None:
        return None


async def _state(world: World) -> tuple[str, str | None]:
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        mailbox = await session.get(Mailbox, world.mailbox)
        assert mailbox is not None
        return mailbox.state, mailbox.state_reason


async def test_fetching_marks_each_message_after_storing_it(world: World) -> None:
    """REQ-INC-023 AC3, REQ-ADM-067: marked read (not deleted), and once only."""
    ring = KeyRing.parse(KeyRing.generate())
    same = _mail()
    reader = FakeReader([("1", same), ("2", _mail()), ("3", same)])
    handled = await fetch_mailbox(
        world.database, SETTINGS, world.tenant, world.mailbox, ring=ring, reader=reader
    )
    assert handled == 2  # the third is the first again (same Message-ID)
    assert reader.marked == [("1", "mark_read"), ("2", "mark_read"), ("3", "mark_read")]
    assert len(world.incidents.created) == 2
    assert await _state(world) == ("working", None)
    assert await _signals(world) == 1
    await fetch_mailbox(  # nothing new, nothing changed: no signal every 2 minutes
        world.database, SETTINGS, world.tenant, world.mailbox, ring=ring, reader=reader
    )
    assert await _signals(world) == 1


async def _signals(world: World) -> int:
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM outbox_events WHERE event_type = $1 AND aggregate_id = $2",
                "integrations.mailbox.changed",
                str(world.mailbox),
            )
        )
    finally:
        await conn.close()


async def test_a_mailbox_that_cannot_be_reached_says_so(world: World) -> None:
    """REQ-INC-023 AC4: shown in the product, not only in logs."""
    ring = KeyRing.parse(KeyRing.generate())
    reader = FakeReader([], fail="imap_login_failed")
    await fetch_mailbox(
        world.database, SETTINGS, world.tenant, world.mailbox, ring=ring, reader=reader
    )
    assert await _state(world) == ("failing", "imap_login_failed")


# --- The review queue (D-109 (9): held mail is never invisible) ------------------------------


async def _waiting(world: World) -> list[tuple[str, str | None, bool]]:
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        return [
            (w.row.outcome, w.row.reason, w.releasable)
            for w in await waiting_mail(session, world.mailbox)
        ]


async def test_held_mail_waits_with_its_copy_and_can_be_handed_in_again(world: World) -> None:
    for _ in range(PER_SENDER_LIMIT):
        await _process(world, _mail())
    flood = _mail(Message_ID="<flood@mail.acme.test>")
    assert await _process(world, flood) is Outcome.HELD
    assert await _waiting(world) == [("held", "sender_rate", True)]
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        row = await release_mail(
            session, SETTINGS, world.mailbox, "flood@mail.acme.test", admin_id=world.known
        )
        assert (row.outcome, row.raw, row.handled_by) == ("created", None, world.known)
    assert len(world.incidents.created) == PER_SENDER_LIMIT + 1
    assert await _waiting(world) == []


async def test_a_release_that_fails_again_waits_with_the_new_reason(world: World) -> None:
    world.incidents.refuse = "validation_failed"
    await _process(world, _mail(Message_ID="<refused@mail.acme.test>"))
    world.incidents.refuse = "template_field_required"
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        row = await release_mail(
            session, SETTINGS, world.mailbox, "refused@mail.acme.test", admin_id=world.known
        )
        assert (row.outcome, row.reason, row.raw is not None) == (
            "held",
            "template_field_required",
            True,
        )


async def test_a_reply_by_someone_else_can_only_be_discarded(world: World) -> None:
    world.incidents.records["INC-7"] = FoundRecord("incident", uuid.uuid4(), "INC-7", frozenset())
    await _process(world, _mail(Subject="Re: [INC-7] x", Message_ID="<other@mail.acme.test>"))
    assert await _waiting(world) == [("held", "not_requester", False)]
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        with pytest.raises(NotWaiting):
            await release_mail(
                session, SETTINGS, world.mailbox, "other@mail.acme.test", admin_id=world.known
            )
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        await discard_mail(session, world.mailbox, "other@mail.acme.test", admin_id=world.known)
    assert await _waiting(world) == []
    (row,) = await _ledger(world)
    assert (row.outcome, row.handled_by) == ("discarded", world.known)
    async with world.database.tenant_session(TenantContext(world.tenant)) as session:
        with pytest.raises(NotWaiting):  # twice: someone else was quicker
            await discard_mail(session, world.mailbox, "other@mail.acme.test", admin_id=world.known)
