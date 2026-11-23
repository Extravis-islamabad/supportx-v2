"""People kept informed by e-mail (WP-046a S6; REQ-INC-066) and their stop link (lane B's terms).

AC1: an address in the incident's list gets public replies, never private notes.
The stop link: a page asks first (peek never acts), the button stops once; unknown, used and
another tenant's tokens get one answer; the change is versioned, in history and audited.
"""

import json
import re
import uuid
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.work_items.service.kept_informed import on_conversation_added
from app.shared.events import EventEnvelope
from conftest import make_settings
from tests.db.per_test_world import MODULE_LOOP, module_world, shared_world  # has sync tests
from tests.db.test_branding_api import slug_of
from tests.db.test_conversation_api import say
from tests.db.test_incidents_api import BASE, CONSOLE, World

__all__ = ["module_world", "shared_world"]  # fixture, re-used

pytestmark = [pytest.mark.db, MODULE_LOOP]

PUBLIC = "/api/v1/public/notify-links"
TOKEN = re.compile(r"#([A-Za-z0-9_-]{43})")


MAIL = make_settings(mail_smtp_host="mail.invalid", mail_from_address="support@supportx.test")
DONE: set[int] = set()  # outbox rows already handed to the consumer


async def _deliver(world: World, org: Any, settings: Any = MAIL) -> None:  # noqa: ANN401 - Org, Settings
    """Hand the tenant's new conversation events to the consumer, as the worker would."""
    rows = await world.sql(
        "SELECT id, envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.conversation.added' ORDER BY id",
        org.tenant,
    )
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        for row in rows:
            if row["id"] in DONE:
                continue
            DONE.add(row["id"])
            envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
            async with database.tenant_session(TenantContext(org.tenant)) as session:
                await on_conversation_added(envelope, session, settings)
    finally:
        await database.dispose()


async def _mails(world: World, org: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - Org
    await _deliver(world, org)
    rows = await world.sql(
        "SELECT recipients, subject, text_body FROM mail_messages WHERE tenant_id = $1"
        " AND kind = 'kept_informed' ORDER BY created_at",
        org.tenant,
    )
    return [dict(r) for r in rows]


async def _post(world: World, path: str, token: str, tenant: str | None) -> Any:  # noqa: ANN401 - a response
    return await world.client.post(f"{PUBLIC}/{path}", json={"token": token, "tenant": tenant})


async def test_public_replies_reach_people_kept_informed_and_notes_never_do(
    world: World,
) -> None:
    org = world.a
    refused = await world.call(
        "POST",
        BASE,
        org,
        org.admin,
        json={"subject": "Mail down", "requester_id": str(org.requester), "notify_emails": ["x"]},
        headers=CONSOLE,
    )
    assert refused.status_code == 422
    item = await world.create(org, org.admin, notify_emails=[" Boss@Acme.test ", "boss@acme.test"])
    assert item["notify_emails"] == ["boss@acme.test"]
    # Without outgoing mail set up, a reply still saves; the consumer sends nothing.
    assert (await say(world, org, org.tech_a, item, kind="reply", body="Early")).status_code == 201
    await _deliver(world, org, make_settings())
    assert await _mails(world, org) == []
    assert (await say(world, org, org.tech_a, item, kind="note")).status_code == 201
    assert await _mails(world, org) == []
    reply = await say(world, org, org.tech_a, item, kind="reply", body="<p>Fixed it.</p>")
    assert reply.status_code == 201, reply.text
    (mail,) = await _mails(world, org)
    assert mail["recipients"] == ["boss@acme.test"]
    assert item["display_id"] in mail["subject"]
    assert "Fixed it." in mail["text_body"]
    assert TOKEN.search(mail["text_body"]) is not None
    # Only the hash is stored, bound to the record and the address.
    (link,) = await world.sql(
        "SELECT work_item_id, address, octet_length(token_digest) AS n FROM work_item_notify_links"
        " WHERE tenant_id = $1",
        org.tenant,
    )
    assert (link["work_item_id"], link["address"], link["n"]) == (
        uuid.UUID(item["id"]),
        "boss@acme.test",
        32,
    )


async def test_the_stop_link_asks_first_stops_once_and_tells_nothing_else(world: World) -> None:
    org, other = world.a, world.b
    item = await world.create(org, org.admin, notify_emails=["boss@acme.test"])
    assert (await say(world, org, org.tech_a, item, kind="reply", body="Update")).status_code == 201
    (mail,) = await _mails(world, org)
    found = TOKEN.search(mail["text_body"])
    assert found is not None
    token, slug = found.group(1), await slug_of(world, org)

    seen = await _post(world, "peek", token, slug)
    assert seen.status_code == 200, seen.text
    assert seen.json() == {"display_id": item["display_id"], "address": "b***@acme.test"}
    assert seen.headers["referrer-policy"] == "no-referrer"
    assert (await world.fresh(org, item))["notify_emails"] == ["boss@acme.test"]  # peek: nothing

    wrong_tenant = await _post(world, "stop", token, await slug_of(world, other))
    unknown = await _post(world, "stop", "A" * 43, slug)
    assert (wrong_tenant.status_code, unknown.status_code) == (404, 404)
    assert wrong_tenant.json()["code"] == unknown.json()["code"] == "notify_link_not_found"

    before = (await world.fresh(org, item))["version"]
    stopped = await _post(world, "stop", token, slug)
    assert stopped.status_code == 204, stopped.text
    after = await world.fresh(org, item)
    assert after["notify_emails"] == []
    assert after["version"] == before + 1
    used = await _post(world, "stop", token, slug)
    assert (used.status_code, used.json()["code"]) == (404, "notify_link_not_found")
    peeked = await _post(world, "peek", token, slug)
    assert peeked.status_code == 404
    # A used link's answer is as public as a success: never cached, no referrer (lane A, #501).
    for answer in (used, peeked, unknown, wrong_tenant):
        assert answer.headers["cache-control"] == "no-store"
        assert answer.headers["referrer-policy"] == "no-referrer"

    history = await world.sql(
        "SELECT source, new_value FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'notify_emails' ORDER BY occurred_at DESC LIMIT 1",
        org.tenant,
        uuid.UUID(item["id"]),
    )
    assert (history[0]["source"], json.loads(history[0]["new_value"])) == ("portal", [])
    audit = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = 'notify_link.used'",
        org.tenant,
    )
    details = json.loads(audit[0]["details"])
    assert details == {"address": "b***@acme.test", "via": "public_link"}
    # A further reply goes to nobody: the address was taken off.
    assert (await say(world, org, org.tech_a, item, kind="reply", body="More")).status_code == 201
    assert len(await _mails(world, org)) == 1


async def test_the_first_mails_cc_joins_only_from_a_vouched_sender(world: World) -> None:
    """AC2, behind lane B's guard: a forged From with an attacker in Cc keeps nobody informed; a
    vouched sender's Cc join (never our own address or the requester's)."""
    from email.message import EmailMessage  # noqa: PLC0415 - one test

    from app.modules.integrations.domain.mailboxes import Outcome  # noqa: PLC0415
    from app.modules.integrations.infra.models import Mailbox  # noqa: PLC0415
    from tests.db.test_mail_block_rules import _send  # noqa: PLC0415 - its helper

    org = world.a
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            box = Mailbox(
                tenant_id=org.tenant, address="help@alpha.test", host="imap.alpha.test",
                port=993, username="help@alpha.test", group_id=org.ga,
                trusted_servers=["mx.alpha.test"],
            )  # fmt: skip
            session.add(box)
            await session.flush()
            mailbox_id = box.id
    finally:
        await database.dispose()
    requester = str((await world.sql("SELECT email FROM users WHERE id = $1", org.requester))[0][0])

    def mail(*, vouched: bool, subject: str) -> bytes:
        message = EmailMessage()
        if vouched:
            domain = requester.rsplit("@", 1)[1]
            message["Authentication-Results"] = f"mx.alpha.test; dmarc=pass header.from={domain}"
        message["From"] = requester
        message["To"] = "help@alpha.test"
        message["Cc"] = f"Boss@Acme.test, help@alpha.test, {requester}"
        message["Subject"] = subject
        message["Message-ID"] = f"<{uuid.uuid4().hex}@mail.test>"
        message.set_content("It is down.")
        return message.as_bytes()

    assert await _send(world, mailbox_id, mail(vouched=False, subject="Forged")) is Outcome.CREATED
    (forged,) = await world.sql(
        "SELECT id, notify_emails FROM work_items WHERE tenant_id = $1 AND subject = 'Forged'",
        org.tenant,
    )
    assert list(forged["notify_emails"]) == []
    notes = await world.sql(
        "SELECT new_value FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'mail_cc'",
        org.tenant,
        forged["id"],
    )
    assert [json.loads(n["new_value"]) for n in notes] == ["not_verified"]  # no address named

    assert await _send(world, mailbox_id, mail(vouched=True, subject="Real")) is Outcome.CREATED
    (real,) = await world.sql(
        "SELECT notify_emails FROM work_items WHERE tenant_id = $1 AND subject = 'Real'",
        org.tenant,
    )
    assert list(real["notify_emails"]) == ["boss@acme.test"]


async def test_a_token_of_any_length_gets_the_same_answer(world: World) -> None:
    slug = await slug_of(world, world.a)
    for token in ("short", "A" * 43, "A" * 100):
        answer = await _post(world, "stop", token, slug)
        assert (answer.status_code, answer.json()["code"]) == (404, "notify_link_not_found")
