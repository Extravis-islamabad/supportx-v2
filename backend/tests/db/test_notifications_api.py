"""Notification engine and centre on real PostgreSQL (WP-023).

Incidents are made through the incidents API (the cast of tests/db/test_incidents_api.py); their
committed outbox events are then handed to the engine exactly as the consumers worker does
(`dispatch` in a tenant session of the event), so every rule below runs against real rows:

- REQ-INC-130 AC1: a new incident acknowledges the requester with no set-up; AC3: never the
  person who made the change; REQ-NTF-009 AC1: one message per person reached by two paths;
- REQ-NTF-010: a requester never gets a private note; someone who cannot see the record gets
  nothing, and the log says why;
- REQ-NTF-008: rules are listed with defaults, saved with If-Match, audited, and conditions hold;
- REQ-NTF-016: preferences per category and channel; required events stay on;
- REQ-INC-131: the centre (own entries only, unread count, read one or all);
- REQ-NTF-020 AC3: without outgoing mail, e-mails wait (and are counted) and in-app ones go out;
  once mail works, the waiting ones are handed to the mail sender;
- REQ-INC-133: the recipient's language;
- REQ-INC-134: the record's delivery log, for staff only;
- RLS: no tenant reads or writes another's notification rows.
"""

import json
import uuid
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.notifications.service.engine import dispatch, send_waiting
from app.shared.events import EventEnvelope
from conftest import make_settings
from tests.db.test_conversation_api import mention, say
from tests.db.test_incidents_api import Org, World, world

pytestmark = pytest.mark.db

__all__ = ["world"]  # the incidents fixture, re-used

NO_MAIL = make_settings()
DISPATCHED: dict[int, set[int]] = {}  # outbox rows already handed to the engine, per world
MAIL = make_settings(mail_smtp_host="mail.invalid", mail_from_address="support@supportx.test")


async def run_engine(world: World, org: Org, *, settings: Any = NO_MAIL) -> int:  # noqa: ANN401 - Settings
    """Hand every not-yet-dispatched event of the tenant to the engine, in order."""
    rows = await world.sql(
        "SELECT id, envelope FROM outbox_events WHERE tenant_id = $1 ORDER BY id", org.tenant
    )
    done = DISPATCHED.setdefault(id(world), set())
    database = Database(create_engine(world.db.app_url, application_name="test"))
    total = 0
    try:
        for row in rows:
            if row["id"] in done:
                continue
            done.add(row["id"])
            envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
            async with database.tenant_session(TenantContext(org.tenant)) as session:
                total += await dispatch(session, settings, envelope)
    finally:
        await database.dispose()
    return total


async def deliveries(world: World, org: Org, item: dict[str, Any]) -> list[asyncpg.Record]:
    return await world.sql(
        "SELECT event_code, user_id, channel, state, reason, text_body, reasons"
        " FROM notification_deliveries WHERE tenant_id = $1 AND record_id = $2 ORDER BY created_at",
        org.tenant,
        uuid.UUID(item["id"]),
    )


async def centre(world: World, org: Org, user: uuid.UUID, query: str = "") -> dict[str, Any]:
    response = await world.call("GET", f"/notifications{query}", org, user)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_new_incident_acknowledges_the_requester_never_the_actor(world: World) -> None:
    org = world.a
    item = await world.create(org, org.lead)
    await run_engine(world, org)
    rows = await deliveries(world, org, item)
    reached = {(r["event_code"], r["user_id"], r["channel"], r["state"]) for r in rows}
    assert ("incident.created", org.requester, "in_app", "sent") in reached
    # No outgoing mail: the e-mail waits, rendered (REQ-NTF-020 AC3).
    assert ("incident.created", org.requester, "email", "waiting") in reached
    assert all(r["user_id"] != org.tech_a for r in rows)  # REQ-INC-130 AC3
    mine = await centre(world, org, org.requester)
    assert mine["unread"] == 1
    entry = mine["items"][0]
    assert entry["display_id"] == item["display_id"]
    assert item["display_id"] in entry["title"]
    assert "Mail is down" in entry["title"]
    assert entry["link"] == f"/incidents/{item['id']}"
    # Nobody else sees the requester's entry.
    assert (await centre(world, org, org.tech_b))["items"] == []
    status = await world.call("GET", "/notifications/status", org, org.admin)
    assert status.json() == {"mail_configured": False, "waiting": 1}


async def test_assignment_is_required_and_one_message_per_person(world: World) -> None:
    org = world.a
    item = await world.create(org, org.lead, group_id=str(org.gb))
    await run_engine(world, org)
    # tech_b follows the incident and becomes its assignee: one message, not two.
    followed = await world.call(
        "PUT", f"/incidents/{item['id']}/followers/{org.tech_b}", org, org.admin
    )
    assert followed.status_code in {200, 204}, followed.text
    rule = await world.call("GET", "/notifications/rules", org, org.admin)
    assigned = next(r for r in rule.json() if r["event_code"] == "incident.assigned")
    assert assigned["required"]
    assert assigned["is_default"]
    assert assigned["version"] == 0
    saved = await world.call(
        "PUT",
        "/notifications/rules/incident.assigned",
        org,
        org.admin,
        json={**_rule(assigned), "recipients": ["assignee", "followers"]},
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200, saved.text
    item = await world.fresh(org, item)
    moved = await world.assign(org, org.lead, item, group=org.gb, technician=org.tech_b)
    assert moved.status_code == 200, moved.text
    await run_engine(world, org)
    rows = [r for r in await deliveries(world, org, item) if r["event_code"] == "incident.assigned"]
    in_app = [r for r in rows if r["channel"] == "in_app"]
    assert [r["user_id"] for r in in_app] == [org.tech_b]
    assert list(in_app[0]["reasons"]) == ["assignee", "followers"]


def _rule(view: dict[str, Any]) -> dict[str, Any]:
    keys = ("enabled", "recipients", "channels", "user_ids", "group_ids", "conditions")
    return {k: view[k] for k in keys} | {"notify_actor": view["notify_actor"]}


async def test_requesters_never_get_private_notes_and_lost_access_is_logged(world: World) -> None:
    org = world.a
    item = await world.create(org, org.tech_a, group_id=str(org.ga))
    await run_engine(world, org)
    rules = (await world.call("GET", "/notifications/rules", org, org.admin)).json()
    private = next(r for r in rules if r["event_code"] == "incident.private_note")
    # Even a rule that names the requester and someone outside the group.
    saved = await world.call(
        "PUT",
        "/notifications/rules/incident.private_note",
        org,
        org.admin,
        json={
            **_rule(private),
            "enabled": True,
            "recipients": ["requester"],
            "user_ids": [str(org.tech_b)],
        },
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200, saved.text
    secret = "<p>Root password is hunter2</p>"
    note = await say(world, org, org.tech_a, item, body=secret, visibility="private")
    assert note.status_code == 201, note.text
    await run_engine(world, org)
    rows = [
        r for r in await deliveries(world, org, item) if r["event_code"] == "incident.private_note"
    ]
    by_user = {(r["user_id"], r["channel"]): r for r in rows}
    # The requester sees only the public side: not even word of a private note, and the log says so.
    for channel in ("in_app", "email"):
        assert by_user[(org.requester, channel)]["state"] == "suppressed"
        assert by_user[(org.requester, channel)]["reason"] == "no_access"
        assert by_user[(org.requester, channel)]["text_body"] is None
    assert all(
        "hunter2" not in e["title"] for e in (await centre(world, org, org.requester))["items"]
    )
    # tech_b is in neither the group nor the site: nothing, and the log says why.
    assert by_user[(org.tech_b, "in_app")]["state"] == "suppressed"
    assert by_user[(org.tech_b, "in_app")]["reason"] == "no_access"
    # A public note does reach the requester, with its text.
    public = await say(
        world, org, org.tech_a, item, body="<p>Restart fixed it</p>", visibility="public"
    )
    assert public.status_code == 201, public.text
    await run_engine(world, org)
    rows = [
        r for r in await deliveries(world, org, item) if r["event_code"] == "incident.public_note"
    ]
    mail = next(r for r in rows if r["user_id"] == org.requester and r["channel"] == "email")
    assert "Restart fixed it" in mail["text_body"]


async def test_mentions_are_required_and_preferences_hold_back_the_rest(world: World) -> None:
    org = world.a
    item = await world.create(org, org.tech_a, group_id=str(org.ga))
    await run_engine(world, org)
    prefs = await world.call("GET", "/notifications/preferences", org, org.tech_c)
    assert prefs.status_code == 200
    assert prefs.headers["etag"] == '"0"'
    choices = {(c["category"], c["channel"]): c for c in prefs.json()["choices"]}
    assert choices[("mention", "email")]["locked"]
    assert not choices[("conversation", "email")]["locked"]
    saved = await world.call(
        "PUT",
        "/notifications/preferences",
        org,
        org.tech_c,
        json={
            "off": [
                {"category": "mention", "channel": "email"},  # required: stays on
                {"category": "conversation", "channel": "email"},
            ]
        },
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200, saved.text
    after = {(c["category"], c["channel"]): c["on"] for c in saved.json()["choices"]}
    assert after[("mention", "email")]
    assert not after[("conversation", "email")]
    stale = await world.call(
        "PUT",
        "/notifications/preferences",
        org,
        org.tech_c,
        json={"off": []},
        headers={"If-Match": '"0"'},
    )
    assert stale.status_code == 409
    # tech_c follows and is mentioned in one note.
    await world.call("PUT", f"/incidents/{item['id']}/followers/{org.tech_c}", org, org.admin)
    note = await say(
        world,
        org,
        org.tech_a,
        item,
        body=f"<p>{mention(org.tech_c, 'C')} look</p>",
        visibility="public",
    )
    assert note.status_code == 201, note.text
    await run_engine(world, org)
    rows = {
        (r["event_code"], r["channel"]): r
        for r in await deliveries(world, org, item)
        if r["user_id"] == org.tech_c
    }
    assert rows[("incident.mentioned", "email")]["state"] == "waiting"
    assert rows[("incident.public_note", "email")]["state"] == "suppressed"
    assert rows[("incident.public_note", "email")]["reason"] == "preference"
    assert rows[("incident.public_note", "in_app")]["state"] == "sent"  # REQ-NTF-016 AC1


async def test_rules_switch_off_conditions_audit_and_reset(world: World) -> None:
    org = world.b
    rules = (await world.call("GET", "/notifications/rules", org, org.admin)).json()
    created = next(r for r in rules if r["event_code"] == "incident.created")
    assert created["enabled"]
    assert created["default_recipients"] == ["requester"]
    assert "requester" in created["recipient_kinds"]
    assert "priority" in created["condition_fields"]
    refused = await world.call(
        "PUT",
        "/notifications/rules/incident.created",
        org,
        org.tech_a,
        json=_rule(created),
        headers={"If-Match": '"0"'},
    )
    assert refused.status_code == 403
    bad = await world.call(
        "PUT",
        "/notifications/rules/incident.created",
        org,
        org.admin,
        json={**_rule(created), "recipients": ["nobody"]},
        headers={"If-Match": '"0"'},
    )
    assert bad.status_code == 422
    only_p1 = await world.call(
        "PUT",
        "/notifications/rules/incident.created",
        org,
        org.admin,
        json={
            **_rule(created),
            "conditions": [{"field": "priority", "operator": "in", "values": ["p1"]}],
        },
        headers={"If-Match": '"0"'},
    )
    assert only_p1.status_code == 200, only_p1.text
    assert only_p1.headers["etag"] == '"1"'
    low = await world.create(org, org.lead)
    high = await world.create(org, org.lead, priority="p1", priority_reason="outage")
    await run_engine(world, org)
    assert await deliveries(world, org, low) == []
    assert {r["user_id"] for r in await deliveries(world, org, high)} == {org.requester}
    audit = await world.sql(
        "SELECT action, outcome FROM audit_entries WHERE tenant_id = $1 AND action LIKE"
        " 'notification.%' ORDER BY occurred_at",
        org.tenant,
    )
    # The refused and the invalid attempts are audited too; one change went through.
    assert [r["outcome"] for r in audit].count("done") == 1
    assert {r["action"] for r in audit} == {"notification.rule_changed"}
    stale = await world.call(
        "DELETE",
        "/notifications/rules/incident.created",
        org,
        org.admin,
        headers={"If-Match": '"0"'},
    )
    assert stale.status_code == 409
    reset = await world.call(
        "DELETE",
        "/notifications/rules/incident.created",
        org,
        org.admin,
        headers={"If-Match": '"1"'},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["is_default"]
    assert reset.json()["conditions"] == []
    # Saved again after a reset: the event's key is free.
    again = await world.call(
        "PUT",
        "/notifications/rules/incident.created",
        org,
        org.admin,
        json={**_rule(created), "enabled": False},
        headers={"If-Match": '"0"'},
    )
    assert again.status_code == 200, again.text


async def test_centre_reads_one_or_all_and_only_ones_own(world: World) -> None:
    org = world.a
    for _ in range(3):
        await world.create(org, org.lead)
    await run_engine(world, org)
    mine = await centre(world, org, org.requester)
    assert mine["unread"] == 3
    first = mine["items"][0]["id"]
    # Someone else's IDs change nothing.
    other = await world.call("POST", "/notifications/read", org, org.tech_b, json={"ids": [first]})
    assert other.json() == {"changed": 0, "unread": 0}
    one = await world.call("POST", "/notifications/read", org, org.requester, json={"ids": [first]})
    assert one.json() == {"changed": 1, "unread": 2}
    page = await centre(world, org, org.requester, "?limit=2")
    assert len(page["items"]) == 2
    assert page["next_cursor"] is not None
    rest = await centre(world, org, org.requester, f"?limit=2&cursor={page['next_cursor']}")
    assert len(rest["items"]) == 1
    every = await world.call("POST", "/notifications/read", org, org.requester, json={})
    assert every.json() == {"changed": 2, "unread": 0}
    read_events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type ="
        " 'notifications.notification.read'",
        org.tenant,
    )
    assert len(read_events) == 2


async def test_language_of_the_recipient_and_waiting_mail_goes_out_later(world: World) -> None:
    org = world.b
    await world.sql("UPDATE users SET ui_locale = 'ar' WHERE id = $1", org.requester)
    item = await world.create(org, org.lead)
    await run_engine(world, org)
    entry = (await centre(world, org, org.requester))["items"][0]
    assert entry["title"].startswith("استلمنا")
    waiting = [r for r in await deliveries(world, org, item) if r["state"] == "waiting"]
    assert waiting
    assert "مرحبًا" in waiting[0]["text_body"]
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            assert await send_waiting(session, NO_MAIL) == 0
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            assert await send_waiting(session, MAIL) == 1
    finally:
        await database.dispose()
    after = [r for r in await deliveries(world, org, item) if r["channel"] == "email"]
    assert after[0]["state"] == "queued"
    assert after[0]["text_body"] is None
    mail = await world.sql(
        "SELECT language, kind, subject FROM mail_messages WHERE tenant_id = $1", org.tenant
    )
    assert [(m["language"], m["kind"]) for m in mail] == [("ar", "notification")]
    assert item["display_id"] in mail[0]["subject"]


async def test_delivery_log_for_staff_only(world: World) -> None:
    org = world.a
    item = await world.create(org, org.lead)
    await run_engine(world, org)
    query = f"/notifications/deliveries?record_type=incident&record_id={item['id']}"
    staff = await world.call("GET", query, org, org.tech_a)
    assert staff.status_code == 200, staff.text
    entries = staff.json()
    assert {(e["channel"], e["state"]) for e in entries} == {
        ("in_app", "sent"),
        ("email", "waiting"),
    }
    assert {e["recipient_name"] for e in entries} == {"Alpha Requester"}
    assert (await world.call("GET", query, org, org.requester)).status_code == 404
    assert (await world.call("GET", query, world.b, world.b.admin)).status_code == 404


async def test_rls_keeps_notification_rows_in_their_tenant(world: World) -> None:
    item = await world.create(world.a, world.a.lead)
    await run_engine(world, world.a)
    await world.call(
        "PUT",
        "/notifications/preferences",
        world.a,
        world.a.requester,
        json={"off": []},
        headers={"If-Match": '"0"'},
    )
    rules = (await world.call("GET", "/notifications/rules", world.a, world.a.admin)).json()
    created = next(r for r in rules if r["event_code"] == "incident.created")
    await world.call(
        "PUT",
        "/notifications/rules/incident.created",
        world.a,
        world.a.admin,
        json=_rule(created),
        headers={"If-Match": '"0"'},
    )
    database = Database(create_engine(world.db.app_url, application_name="test"))
    tables = (
        "notifications",
        "notification_deliveries",
        "notification_preferences",
        "notification_rules",
    )
    try:
        for table in tables:
            async with database.tenant_session(TenantContext(world.b.tenant)) as session:
                seen = await session.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608 - fixed names
                assert seen == 0, table
                changed = await session.execute(text(f"UPDATE {table} SET updated_at = now()"))  # noqa: S608
                assert getattr(changed, "rowcount", 0) == 0, table
            async with database.tenant_session(TenantContext(world.a.tenant)) as session:
                assert ((await session.scalar(text(f"SELECT count(*) FROM {table}"))) or 0) > 0  # noqa: S608
        async with database.tenant_session(TenantContext(world.b.tenant)) as session:
            with pytest.raises(Exception, match="row-level security"):
                await session.execute(
                    text(
                        "INSERT INTO notifications (id, tenant_id, user_id, event_code,"
                        " record_type, record_id, display_id, title, link) VALUES"
                        " (gen_random_uuid(), :t, :u, 'incident.created', 'incident', :r,"
                        " 'INC-1', 'x', '/x')"
                    ),
                    {"t": world.a.tenant, "u": world.a.requester, "r": uuid.UUID(item["id"])},
                )
    finally:
        await database.dispose()


async def test_an_incident_created_already_assigned_tells_its_technician(world: World) -> None:
    """Created with a technician, the incident emits no separate assignment: CI's e2e found it."""
    org = world.a
    item = await world.create(org, org.lead, group_id=str(org.ga), technician_id=str(org.tech_a))
    await run_engine(world, org)
    rows = [r for r in await deliveries(world, org, item) if r["event_code"] == "incident.assigned"]
    assert {(r["user_id"], r["channel"], r["state"]) for r in rows} == {
        (org.tech_a, "in_app", "sent"),
        (org.tech_a, "email", "waiting"),
    }
