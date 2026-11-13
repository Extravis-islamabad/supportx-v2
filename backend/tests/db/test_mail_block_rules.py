"""Block rules and quarantine for unwanted mail (WP-046a S6; REQ-INC-026).

AC1: mail matching a rule creates nothing and appears in the review queue as blocked.
AC2: an admin releases it, and the incident is made. Blocked mail past the mailbox's quarantine
days loses its copy (the ledger row stays, discarded). Rules stay in their tenant.
"""

import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx
import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.integrations.domain.mailboxes import Outcome
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.service.inbound import expire_quarantine, process
from conftest import make_settings
from tests.db.per_test_world import MODULE_LOOP, module_world, shared_world  # has sync tests
from tests.db.test_incidents_api import World, problem

__all__ = ["module_world", "shared_world"]  # fixture, re-used

pytestmark = [pytest.mark.db, MODULE_LOOP]

SETTINGS = make_settings()
OWN = ("help@alpha.test",)
RULES = "/integrations/mail-block-rules"


def _mail(sender: str, subject: str = "Hello", body: str = "Please help.") -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = OWN[0]
    message["Subject"] = subject
    message["Message-ID"] = f"<{uuid.uuid4().hex}@mail.test>"
    message.set_content(body)
    return message.as_bytes()


async def _mailbox(world: World) -> uuid.UUID:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            box = Mailbox(
                tenant_id=world.a.tenant,
                address=OWN[0],
                host="imap.alpha.test",
                port=993,
                username=OWN[0],
                group_id=world.a.ga,
                unknown_senders="create",
            )
            session.add(box)
            await session.flush()
            return box.id
    finally:
        await database.dispose()


async def _send(world: World, mailbox_id: uuid.UUID, raw: bytes) -> Outcome | None:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            mailbox = await session.get(Mailbox, mailbox_id)
            assert mailbox is not None
            return await process(session, SETTINGS, mailbox, raw, own_addresses=OWN)
    finally:
        await database.dispose()


async def _add(
    world: World, kind: str, value: str, user: uuid.UUID | None = None
) -> httpx.Response:
    return await world.call(
        "POST",
        RULES,
        world.a,
        user or world.a.admin,
        json={"kind": kind, "value": value},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )


async def test_rules_are_checked_unique_versioned_and_stay_in_their_tenant(world: World) -> None:
    org = world.a
    assert (await _add(world, "domain", "spam.test", org.tech_a)).status_code == 403
    bad = await _add(world, "domain", "not a domain")
    assert bad.status_code == 422
    made = await _add(world, "domain", "@Spam.Test.")
    assert made.status_code == 201, made.text
    rule = made.json()
    assert (rule["kind"], rule["value"], rule["enabled"]) == ("domain", "spam.test", True)
    assert problem(await _add(world, "domain", "SPAM.test")) == (409, "mail_block_rule_exists")
    path = f"{RULES}/{rule['id']}"
    stale = await world.call(
        "PATCH", path, org, org.admin, json={"enabled": False}, headers={"If-Match": '"9"'}
    )
    assert problem(stale) == (409, "version_conflict")
    off = await world.call(
        "PATCH", path, org, org.admin, json={"enabled": False}, headers={"If-Match": '"1"'}
    )
    assert (off.status_code, off.json()["enabled"]) == (200, False)
    other = await world.call("GET", RULES, world.b, world.b.admin)
    assert other.json() == []
    rows = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND action LIKE 'mail_block_rule.%'"
        " AND outcome = 'done'",
        org.tenant,
    )
    assert {r["action"] for r in rows} == {"mail_block_rule.created", "mail_block_rule.changed"}
    gone = await world.call("DELETE", path, org, org.admin, headers={"If-Match": '"2"'})
    assert gone.status_code == 204
    assert (await world.call("GET", RULES, org, org.admin)).json() == []


async def test_blocked_mail_creates_nothing_waits_and_an_admin_lets_it_through(
    world: World,
) -> None:
    org = world.a
    mailbox_id = await _mailbox(world)
    assert (await _add(world, "subject", "win a prize")).status_code == 201
    raw = _mail("stranger@elsewhere.test", subject="You WIN A PRIZE today")
    assert await _send(world, mailbox_id, raw) is Outcome.BLOCKED
    made = await world.sql(
        "SELECT 1 FROM work_items WHERE tenant_id = $1 AND channel = 'email'", org.tenant
    )
    assert made == []
    waiting = await world.call(
        "GET", f"/integrations/mailboxes/{mailbox_id}/waiting", org, org.admin
    )
    (entry,) = waiting.json()
    assert (entry["outcome"], entry["reason"], entry["releasable"]) == (
        "blocked",
        "block_rule",
        True,
    )
    released = await world.call(
        "POST",
        f"/integrations/mailboxes/{mailbox_id}/waiting/release",
        org,
        org.admin,
        json={"message_id": entry["message_id"]},
    )
    assert released.status_code == 200, released.text
    assert released.json()["outcome"] == "created"
    made = await world.sql(
        "SELECT 1 FROM work_items WHERE tenant_id = $1 AND channel = 'email'", org.tenant
    )
    assert len(made) == 1
    # Mail that matches no rule goes on as before.
    assert await _send(world, mailbox_id, _mail("stranger@elsewhere.test")) is Outcome.CREATED


async def test_blocked_mail_past_its_quarantine_loses_its_copy(world: World) -> None:
    org = world.a
    mailbox_id = await _mailbox(world)
    assert (await _add(world, "sender", "pest@elsewhere.test")).status_code == 201
    assert await _send(world, mailbox_id, _mail("Pest@Elsewhere.test")) is Outcome.BLOCKED
    (row,) = await world.sql(
        "SELECT message_id, raw IS NOT NULL AS kept FROM mail_fetched WHERE tenant_id = $1"
        " AND outcome = 'blocked'",
        org.tenant,
    )
    assert row["kept"]
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            mailbox = await session.get(Mailbox, mailbox_id)
            assert mailbox is not None
            now = datetime.now(UTC)
            assert await expire_quarantine(session, mailbox, now) == 0  # 14 days not passed
            later = now + timedelta(days=mailbox.quarantine_days, minutes=1)
            assert await expire_quarantine(session, mailbox, later) == 1
    finally:
        await database.dispose()
    (after,) = await world.sql(
        "SELECT outcome, reason, raw IS NULL AS cleared FROM mail_fetched WHERE tenant_id = $1"
        " AND message_id = $2",
        org.tenant,
        row["message_id"],
    )
    assert (after["outcome"], after["reason"], after["cleared"]) == (
        "discarded",
        "quarantine_expired",
        True,
    )
