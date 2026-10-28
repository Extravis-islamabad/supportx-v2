"""Mail into real incidents (WP-024; REQ-INC-023, REQ-INC-024, REQ-INC-027; lane A reviews).

The work items side of the inbound port with the real services: an incident created in the
requester's name with channel e-mail and the mailbox's group, the requester's reply on it, an
out-of-office recorded and nothing else, a staff member's mail held, and a create the incident
side refuses kept with the fields it needs. Same world as test_incidents_api.py.
"""

import uuid
from email.message import EmailMessage

import pytest

from app.core.database import Database, create_engine
from app.core.errors import FieldError, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.integrations.domain.mailboxes import Outcome
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.service.inbound import process
from app.modules.work_items.service.inbound_mail import FIELDS_NEEDED, _refusals
from app.shared.mail.ports import InboundRefused
from conftest import make_settings
from tests.db.test_incidents_api import World, world

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]

SETTINGS = make_settings()
OWN = ("it@alpha.test",)


async def _email(world: World, user: uuid.UUID) -> str:
    rows = await world.sql("SELECT email FROM users WHERE id = $1", user)
    return str(rows[0]["email"])


def _mail(sender: str, subject: str, *, body: str = "It jams.", **headers: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "it@alpha.test"
    message["Subject"] = subject
    message["Message-ID"] = f"<{uuid.uuid4().hex}@mail.alpha.test>"
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content(body)
    return message.as_bytes()


async def _process(world: World, database: Database, raw: bytes) -> Outcome | None:
    tenant = world.a.tenant
    async with database.tenant_session(TenantContext(tenant)) as session:
        mailbox = await session.get(Mailbox, await _mailbox(world, database))
        assert mailbox is not None
        return await process(session, SETTINGS, mailbox, raw, own_addresses=OWN)


async def _mailbox(world: World, database: Database) -> uuid.UUID:
    rows = await world.sql("SELECT id FROM mailboxes WHERE tenant_id = $1", world.a.tenant)
    if rows:
        return uuid.UUID(str(rows[0]["id"]))
    async with database.tenant_session(TenantContext(world.a.tenant)) as session:
        box = Mailbox(
            tenant_id=world.a.tenant,
            address="it@alpha.test",
            host="imap.alpha.test",
            port=993,
            username="it@alpha.test",
            group_id=world.a.ga,
        )
        session.add(box)
        await session.flush()
        return box.id


async def test_mail_becomes_an_incident_and_the_requesters_replies_land_on_it(
    world: World,
) -> None:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        requester = await _email(world, world.a.requester)
        outcome = await _process(world, database, _mail(requester, "Printer jams on floor 2"))
        assert outcome is Outcome.CREATED
        (made,) = await world.sql(
            "SELECT id, display_id, channel, group_id, requester_id, subject, description"
            " FROM work_items WHERE tenant_id = $1 AND channel = 'email'",
            world.a.tenant,
        )
        assert (made["requester_id"], made["group_id"]) == (world.a.requester, world.a.ga)
        assert made["subject"] == "Printer jams on floor 2"
        assert "It jams." in made["description"]

        reply = _mail(requester, f"Re: [{made['display_id']}] Printer jams", body="Still.")
        assert await _process(world, database, reply) is Outcome.REPLIED
        auto = _mail(
            requester,
            f"Auto: [{made['display_id']}] away",
            body="I am away.",
            Auto_Submitted="auto-replied",
        )
        assert await _process(world, database, auto) is Outcome.AUTOMATIC
        entries = await world.sql(
            "SELECT kind, visibility, body FROM work_item_conversations"
            " WHERE work_item_id = $1 ORDER BY created_at",
            made["id"],
        )
        assert [(e["kind"], e["visibility"]) for e in entries] == [
            ("reply", "public"),
            ("reply", "public"),
        ]
        assert "Still." in entries[0]["body"]
        events = await world.sql(
            "SELECT envelope->'payload'->>'automatic' AS automatic FROM outbox_events"
            " WHERE tenant_id = $1 AND event_type = 'work_items.conversation.added'"
            " ORDER BY id",
            world.a.tenant,
        )
        assert [e["automatic"] for e in events][-2:] == ["false", "true"]

        # A technician's mail on the record is not a requester reply: held, they use the console.
        staff = await _email(world, world.a.tech_a)
        held = _mail(staff, f"Re: [{made['display_id']}] fixed?", body="On it.")
        assert await _process(world, database, held) is Outcome.HELD
        rows = await world.sql(
            "SELECT reason FROM mail_fetched WHERE tenant_id = $1 AND outcome = 'held'",
            world.a.tenant,
        )
        assert [r["reason"] for r in rows] == ["not_requester"]
    finally:
        await database.dispose()


async def test_a_refused_create_names_the_fields_it_needs() -> None:
    """A template or rule that asks for more: held with the fields, for the review queue."""
    refused = ValidationFailed(
        errors=[
            FieldError(
                field="body.category_id", code="required", message_key="errors.field.required"
            ),
            FieldError(field="body.site_id", code="required", message_key="errors.field.required"),
        ]
    )
    with pytest.raises(InboundRefused) as held:
        async with _refusals():
            raise refused
    assert (held.value.code, held.value.params) == (
        FIELDS_NEEDED,
        {"fields": "category_id,site_id"},
    )


async def test_an_outage_is_not_held_but_retried() -> None:
    """A 5xx from the incident side propagates: the message stays unseen and is fetched again."""

    class Down(Exception):
        pass

    with pytest.raises(Down):
        async with _refusals():
            raise Down
