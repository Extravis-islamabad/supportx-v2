"""Commands written at the top of a mail (WP-046a S6; REQ-INC-025), through the real inbound path.

The coordinator's conditions: off by default; only for a sender the mailbox's trusted server
vouched for (a forged From is never believed); each line through the API's own checks as the
sender; a line that fails is skipped, the incident made, and the sender told.
"""

import json
import uuid
from email.message import EmailMessage

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.integrations.domain.mailboxes import Outcome
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.service.inbound import process
from conftest import make_settings
from tests.db.per_test_world import MODULE_LOOP, module_world, shared_world  # has sync tests
from tests.db.test_incidents_api import World

__all__ = ["module_world", "shared_world"]  # fixture, re-used

pytestmark = [pytest.mark.db, MODULE_LOOP]

# Mail set up, so the answer to the sender is queued (mail_configured).
SETTINGS = make_settings(mail_smtp_host="mail.invalid", mail_from_address="support@supportx.test")
OWN = ("help@alpha.test",)
MX = "mx.alpha.test"


async def _email(world: World, user: uuid.UUID) -> str:
    rows = await world.sql("SELECT email FROM users WHERE id = $1", user)
    return str(rows[0]["email"])


def _mail(sender: str, body: str, *, results: str | None = None) -> bytes:
    message = EmailMessage()
    if results is not None:
        message["Authentication-Results"] = results
    message["From"] = sender
    message["To"] = OWN[0]
    message["Subject"] = "Printer down"
    message["Message-ID"] = f"<{uuid.uuid4().hex}@mail.alpha.test>"
    message.set_content(body)
    return message.as_bytes()


def _vouched(sender: str) -> str:
    return f"{MX}; dmarc=pass header.from={sender.rsplit('@', 1)[1]}"


async def _setup(
    world: World,
    *,
    commands: bool,
    trusted: bool = True,
    fields: list[str] | None = None,
) -> None:
    org = world.a
    # Through the settings API, as an admin would (incidents only; If-Match on its version).
    current = await world.call("GET", "/incidents/settings", org, org.admin)
    saved = await world.call(
        "PATCH",
        "/incidents/settings",
        org,
        org.admin,
        json={
            "mail_commands": commands,
            "mail_command_fields": fields or ["category", "priority", "group"],
        },
        headers={"If-Match": f'"{current.json()["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["mail_commands"] is commands
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            session.add(
                Mailbox(
                    tenant_id=org.tenant,
                    address=OWN[0],
                    host="imap.alpha.test",
                    port=993,
                    username=OWN[0],
                    group_id=org.ga,
                    trusted_servers=[MX] if trusted else [],
                )
            )
    finally:
        await database.dispose()


async def _send(world: World, raw: bytes) -> Outcome | None:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            mailbox_id = (
                await world.sql(
                    "SELECT id FROM mailboxes WHERE tenant_id = $1 AND address = $2",
                    world.a.tenant,
                    OWN[0],
                )
            )[0]["id"]
            mailbox = await session.get(Mailbox, mailbox_id)
            assert mailbox is not None
            return await process(session, SETTINGS, mailbox, raw, own_addresses=OWN)
    finally:
        await database.dispose()


async def _made(world: World) -> dict[str, object]:
    rows = await world.sql(
        "SELECT id, priority, group_id FROM work_items WHERE tenant_id = $1 AND channel = 'email'"
        " ORDER BY created_at DESC LIMIT 1",
        world.a.tenant,
    )
    return dict(rows[0])


async def _ledger(world: World) -> dict[str, str]:
    rows = await world.sql(
        "SELECT reason_params FROM mail_fetched WHERE tenant_id = $1 ORDER BY created_at DESC"
        " LIMIT 1",
        world.a.tenant,
    )
    params = rows[0]["reason_params"]
    return dict(json.loads(params) if isinstance(params, str) else params)


async def _answers(world: World) -> list[str]:
    rows = await world.sql(
        "SELECT text_body FROM mail_messages WHERE tenant_id = $1 AND kind = 'mailbox_answer'"
        " ORDER BY created_at",
        world.a.tenant,
    )
    return [str(r["text_body"]) for r in rows]


async def test_commands_are_plain_text_while_the_type_has_them_off(world: World) -> None:
    await _setup(world, commands=False)
    sender = await _email(world, world.a.tech_a)
    raw = _mail(sender, "priority = p2\n\nIt is down.", results=_vouched(sender))
    assert await _send(world, raw) is Outcome.CREATED
    made = await _made(world)
    assert made["priority"] != "p2"
    assert await _ledger(world) == {}


async def test_a_sender_nobody_vouched_for_changes_nothing_and_history_says_why(
    world: World,
) -> None:
    await _setup(world, commands=True)
    sender = await _email(world, world.a.tech_a)
    # A forged From: no Authentication-Results from the trusted server at all.
    assert await _send(world, _mail(sender, "priority = p2\n\nIt is down.")) is Outcome.CREATED
    made = await _made(world)
    assert made["priority"] != "p2"
    assert await _ledger(world) == {"commands": "not_verified"}
    notes = await world.sql(
        "SELECT new_value, source FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'mail_commands'",
        world.a.tenant,
        made["id"],
    )
    assert [(json.loads(n["new_value"]), n["source"]) for n in notes] == [("not_verified", "email")]
    # A header claiming our server, from someone else's server further down, is no better.
    forged = _mail(sender, "priority = p2", results=f"mx.attacker.test; {_vouched(sender)}")
    assert await _send(world, forged) is Outcome.CREATED
    assert (await _made(world))["priority"] != "p2"


async def test_a_vouched_technician_sets_fields_and_hears_of_the_lines_that_failed(
    world: World,
) -> None:
    await _setup(world, commands=True)
    org = world.a
    sender = await _email(world, org.tech_a)
    group = (await world.sql("SELECT name FROM support_groups WHERE id = $1", org.ga))[0]["name"]
    body = f"priority = p2\ngroup = {group}\ncolour = red\ncategory = No such thing\n\nIt is down."
    assert await _send(world, _mail(sender, body, results=_vouched(sender))) is Outcome.CREATED
    made = await _made(world)
    assert (made["priority"], made["group_id"]) == ("p2", org.ga)
    changed = await world.sql(
        "SELECT field, source FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'priority'",
        org.tenant,
        made["id"],
    )
    assert {c["source"] for c in changed} == {"email"}
    assert await _ledger(world) == {"commands_applied": "2", "commands_not_applied": "2"}
    (answer,) = await _answers(world)
    assert "Line 3: colour = red" in answer
    assert "Line 4: category = No such thing (nothing by that name)" in answer


async def test_a_requester_cannot_do_by_mail_what_they_cannot_do_in_the_app(
    world: World,
) -> None:
    await _setup(world, commands=True)
    org = world.a
    sender = await _email(world, org.requester)
    group = (await world.sql("SELECT name FROM support_groups WHERE id = $1", org.gb))[0]["name"]
    raw = _mail(sender, f"group = {group}\n\nPlease route this.", results=_vouched(sender))
    assert await _send(world, raw) is Outcome.CREATED
    made = await _made(world)
    assert made["group_id"] == org.ga  # the mailbox's group: the requester may not reassign
    (answer,) = await _answers(world)
    assert "you cannot make this change" in answer


async def test_a_requester_learns_nothing_about_who_exists(world: World) -> None:
    """Lane B's #485 review: no lookup before the rights check, so a real person and a nobody
    come back the same, and so do a real group and a made-up one."""
    await _setup(world, commands=True, fields=["category", "priority", "group", "technician"])
    org = world.a
    sender = await _email(world, org.requester)
    real = await _email(world, org.tech_a)
    group = (await world.sql("SELECT name FROM support_groups WHERE id = $1", org.gb))[0]["name"]
    for named in (f"technician = {real}", "technician = nobody@alpha.test",
                  f"group = {group}", "group = No such group"):  # fmt: skip
        raw = _mail(sender, f"{named}\n\nHelp.", results=_vouched(sender))
        assert await _send(world, raw) is Outcome.CREATED
    answers = await _answers(world)
    assert len(answers) == 4
    assert all("you cannot make this change" in a for a in answers)
    assert not any("nothing by that name" in a for a in answers)
