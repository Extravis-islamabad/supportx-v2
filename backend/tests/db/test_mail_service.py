"""The mail service in PostgreSQL (WP-039 session 2; D-089 D3): queue, send, retry, purge.

Real database (throwaway, RLS on); SMTP is a fake sender (tests/integration covers a real
server). Each test names the rule it proves.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import asyncpg
import pytest
import pytest_asyncio

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.shared.mail import Attachment, MailNotConfigured, OutgoingMail, queue_mail
from app.shared.mail.infra import smtp
from app.shared.mail.service import outgoing
from conftest import make_settings
from tests.db.test_access_api import make_org
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

SETTINGS = make_settings(
    mail_smtp_host="smtp.acme.test",
    mail_from_address="support@acme.test",
    mail_from_name="Acme Service Desk",
    mail_max_attempts=3,
)
MAIL = OutgoingMail(
    kind="report",
    to=("pat@acme.test",),
    subject="Weekly report",
    text="Hi",
    attachments=(Attachment("r.csv", "text/csv", b"a,b\n"),),
)


class FakeSender:
    """Records what was sent; can fail temporarily or for good."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self.fail: type[Exception] | None = None

    async def __call__(self, settings: smtp.SmtpSettings, message: EmailMessage) -> None:
        del settings
        if self.fail is smtp.PermanentFailure:
            raise smtp.PermanentFailure(code="recipient_refused")
        if self.fail is smtp.TemporaryFailure:
            raise smtp.TemporaryFailure
        self.sent.append(message)


@pytest_asyncio.fixture
async def world(
    migrated_db: ThrowawayDatabase,
) -> AsyncIterator[tuple[Database, uuid.UUID, uuid.UUID]]:
    database = Database(create_engine(migrated_db.app_url, application_name="test"))
    a = await make_org(migrated_db, "Alpha")
    b = await make_org(migrated_db, "Beta")
    yield database, a.tenant, b.tenant


async def _queue(database: Database, tenant: uuid.UUID, mail: OutgoingMail = MAIL) -> uuid.UUID:
    async with database.tenant_session(TenantContext(tenant)) as session:
        return await queue_mail(session, SETTINGS, mail)


async def _deliver(
    database: Database, tenant: uuid.UUID, mail_id: uuid.UUID, sender: FakeSender
) -> str:
    async with database.tenant_session(TenantContext(tenant)) as session:
        return await outgoing.deliver(session, SETTINGS, mail_id, send=sender)


async def _row(db: ThrowawayDatabase, mail_id: uuid.UUID) -> asyncpg.Record:
    conn = await asyncpg.connect(db.admin_url)
    try:
        row = await conn.fetchrow("SELECT * FROM mail_messages WHERE id = $1", mail_id)
    finally:
        await conn.close()
    assert row is not None
    return row


async def test_a_message_is_queued_with_its_event_in_the_callers_transaction(
    world: tuple[Database, uuid.UUID, uuid.UUID], migrated_db: ThrowawayDatabase
) -> None:
    """CLAUDE.md rule b: sent exactly when the caller's change commits; the event names no one."""
    database, tenant, _ = world
    mail_id = await _queue(database, tenant)
    conn = await asyncpg.connect(migrated_db.admin_url)
    try:
        # Only this test's tenant: other tests share the database.
        event = await conn.fetchval(
            "SELECT envelope::text FROM outbox_events"
            " WHERE event_type = 'system.mail.queued' AND tenant_id = $1",
            tenant,
        )
        # Rolled back with its transaction: nothing queued, no event.
        with pytest.raises(RuntimeError):
            await _queue_then_fail(database, tenant)
        queued = "SELECT count(*) FROM mail_messages WHERE tenant_id = $1"
        assert await conn.fetchval(queued, tenant) == 1
    finally:
        await conn.close()
    assert str(mail_id) in event
    assert "pat@acme.test" not in event
    assert "Weekly report" not in event


async def _queue_then_fail(database: Database, tenant: uuid.UUID) -> None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        await queue_mail(session, SETTINGS, MAIL)
        raise RuntimeError


async def test_nothing_is_queued_without_a_mail_server(
    world: tuple[Database, uuid.UUID, uuid.UUID],
) -> None:
    database, tenant, _ = world
    async with database.tenant_session(TenantContext(tenant)) as session:
        with pytest.raises(MailNotConfigured):
            await queue_mail(session, make_settings(), MAIL)
    assert outgoing.mail_configured(SETTINGS)
    assert not outgoing.mail_configured(make_settings(mail_smtp_host="smtp.acme.test"))


async def test_messages_are_tenant_isolated(
    world: tuple[Database, uuid.UUID, uuid.UUID], migrated_db: ThrowawayDatabase
) -> None:
    """CLAUDE.md rule a, both tables."""
    database, a, b = world
    await _queue(database, a)
    await _queue(database, b)
    conn = await asyncpg.connect(migrated_db.app_direct_url)
    try:
        for table in ("mail_messages", "mail_attachments"):
            async with conn.transaction():
                await conn.execute(f"SET LOCAL app.tenant_id = '{a}'")
                rows = await conn.fetch(f"SELECT tenant_id FROM {table}")  # noqa: S608 - fixed names
            assert {r["tenant_id"] for r in rows} == {a}, table
        async with conn.transaction():
            await conn.execute(f"SET LOCAL app.tenant_id = '{a}'")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(
                    "INSERT INTO mail_messages (id, tenant_id, kind, language, recipients, subject)"
                    " VALUES ($1, $2, 'x', 'en', ARRAY['a@b.test'], 's')",
                    uuid.uuid4(),
                    b,
                )
    finally:
        await conn.close()


async def test_sent_once_then_a_redelivery_does_nothing(
    world: tuple[Database, uuid.UUID, uuid.UUID], migrated_db: ThrowawayDatabase
) -> None:
    database, tenant, _ = world
    sender = FakeSender()
    mail_id = await _queue(database, tenant)
    assert await _deliver(database, tenant, mail_id, sender) == "sent"
    assert await _deliver(database, tenant, mail_id, sender) == "sent"  # the event again
    assert len(sender.sent) == 1
    message = sender.sent[0]
    assert message["From"] == "Acme Service Desk <support@acme.test>"
    assert [p.get_filename() for p in message.iter_attachments()] == ["r.csv"]
    row = await _row(migrated_db, mail_id)
    assert row["state"] == "sent"
    assert row["message_id"] == message["Message-ID"]


async def test_a_temporary_failure_is_retried_with_backoff_then_given_up(
    world: tuple[Database, uuid.UUID, uuid.UUID], migrated_db: ThrowawayDatabase
) -> None:
    database, tenant, _ = world
    sender = FakeSender()
    sender.fail = smtp.TemporaryFailure
    mail_id = await _queue(database, tenant)
    assert await _deliver(database, tenant, mail_id, sender) == "queued"
    row = await _row(migrated_db, mail_id)
    assert row["attempts"] == 1
    assert row["next_attempt_at"] is not None
    # Due only once the backoff passed.
    async with database.tenant_session(TenantContext(tenant)) as session:
        assert await outgoing.due_messages(session) == []
        later = datetime.now(UTC) + timedelta(minutes=2)
        assert await outgoing.due_messages(session, later) == [mail_id]
    await _deliver(database, tenant, mail_id, sender)
    assert await _deliver(database, tenant, mail_id, sender) == "failed"  # third = max
    row = await _row(migrated_db, mail_id)
    assert (row["state"], row["failure"], row["attempts"]) == ("failed", "gave_up", 3)
    assert row["purge_after"] is not None


async def test_a_permanent_refusal_is_recorded_at_once(
    world: tuple[Database, uuid.UUID, uuid.UUID], migrated_db: ThrowawayDatabase
) -> None:
    database, tenant, _ = world
    sender = FakeSender()
    sender.fail = smtp.PermanentFailure
    mail_id = await _queue(database, tenant)
    assert await _deliver(database, tenant, mail_id, sender) == "failed"
    assert (await _row(migrated_db, mail_id))["failure"] == "recipient_refused"


async def test_bodies_and_attachments_are_cleared_after_the_retention(
    world: tuple[Database, uuid.UUID, uuid.UUID], migrated_db: ThrowawayDatabase
) -> None:
    """Personal data: the record of what was sent stays, the content goes."""
    database, tenant, _ = world
    mail_id = await _queue(database, tenant)
    await _deliver(database, tenant, mail_id, FakeSender())
    async with database.tenant_session(TenantContext(tenant)) as session:
        assert await outgoing.purge_content(session) == 0  # not yet
        later = datetime.now(UTC) + timedelta(days=31)
        assert await outgoing.purge_content(session, later) == 1
    row = await _row(migrated_db, mail_id)
    assert (row["text_body"], row["subject"], row["state"]) == (None, "Weekly report", "sent")
    conn = await asyncpg.connect(migrated_db.admin_url)
    try:
        content = await conn.fetchval(
            "SELECT content FROM mail_attachments WHERE message_id = $1", mail_id
        )
    finally:
        await conn.close()
    assert content is None
