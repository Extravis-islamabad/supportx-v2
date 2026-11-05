"""Dismissing a banner on every device, and following an announcement (WP-032 D7; REQ-PRT-009).

Only what is live for the person; idempotent; the feed says it back; the change goes through
the outbox to that person's channel only; tenant isolation (RLS) on both tables.
"""

import json
import uuid

import asyncpg
from sqlalchemy import text

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.notifications.service.engine import dispatch
from app.shared.events import EventEnvelope
from tests.db.test_announcements_api import BASE, World, problem, world
from tests.db.test_notifications_api import NO_MAIL

__all__ = ["world"]  # the fixture, re-used


async def test_dismiss_and_follow_what_is_live_for_you(world: World) -> None:
    a = world.a
    live = await world.published(a, title="Mail is slow today", show_as_banner=True)
    elsewhere = await world.published(a, title="For S2", audience="sites", site_ids=[str(a.s2)])
    path = f"{BASE}/{live['id']}"
    for _ in range(2):  # idempotent
        assert (await world.call("PUT", f"{path}/dismissal", a, a.requester)).status_code == 204
        assert (await world.call("PUT", f"{path}/follow", a, a.requester)).status_code == 204
    feed = (await world.call("GET", f"{BASE}/feed", a, a.requester)).json()
    [item] = [i for i in feed["items"] if i["id"] == live["id"]]
    assert (item["dismissed"], item["following"]) == (True, True)
    # Someone else's view is their own.
    other = (await world.call("GET", f"{BASE}/feed", a, a.tech)).json()
    [theirs] = [i for i in other["items"] if i["id"] == live["id"]]
    assert (theirs["dismissed"], theirs["following"]) == (False, False)
    # Not live for them: nothing to dismiss or follow.
    refused = await world.call("PUT", f"{BASE}/{elsewhere['id']}/dismissal", a, a.requester)
    assert problem(refused) == (404, "announcement_not_found")
    assert (
        problem(await world.call("PUT", f"{BASE}/{uuid.uuid4()}/follow", a, a.requester))[0] == 404
    )
    # Unfollow, twice is fine too.
    for _ in range(2):
        assert (await world.call("DELETE", f"{path}/follow", a, a.requester)).status_code == 204
    again = (await world.call("GET", f"{BASE}/feed", a, a.requester)).json()
    [item] = [i for i in again["items"] if i["id"] == live["id"]]
    assert (item["dismissed"], item["following"]) == (True, False)
    # One event per real change (dismissed, followed, unfollowed), for the person's channel.
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        events = await conn.fetch(
            "SELECT envelope->'payload'->>'change' AS change FROM outbox_events"
            " WHERE envelope->>'event_type' = 'announcements.personal.changed'"
            " AND envelope->'payload'->>'user_id' = $1 ORDER BY id",
            str(a.requester),
        )
    finally:
        await conn.close()
    assert [e["change"] for e in events] == ["dismissed", "followed", "unfollowed"]


async def test_dismissals_and_follows_stay_in_their_tenant(world: World) -> None:
    a, b = world.a, world.b
    live = await world.published(a, title="Office closed Friday")
    await world.call("PUT", f"{BASE}/{live['id']}/dismissal", a, a.requester)
    await world.call("PUT", f"{BASE}/{live['id']}/follow", a, a.requester)
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("announcement_dismissals", "announcement_follows"):
            rows = (await session.execute(text(f"SELECT tenant_id FROM {table}"))).all()  # noqa: S608 - fixed names
            assert rows == [], table
            gone = await session.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - fixed names
            assert gone.rowcount == 0, table
    assert (
        problem(await world.call("PUT", f"{BASE}/{live['id']}/dismissal", b, b.requester))[0] == 404
    )


async def _deliveries(
    world: World, org_tenant: uuid.UUID, record_id: str
) -> list[tuple[str, uuid.UUID]]:
    """Hand the tenant's events to the notification engine, then read what it delivered."""
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        rows = await conn.fetch(
            "SELECT id, envelope FROM outbox_events WHERE tenant_id = $1 ORDER BY id", org_tenant
        )
        database = Database(create_engine(world.db.app_url, application_name="test"))
        try:
            for row in rows:
                envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
                async with database.tenant_session(TenantContext(org_tenant)) as session:
                    await dispatch(session, NO_MAIL, envelope)
        finally:
            await database.dispose()
        found = await conn.fetch(
            "SELECT DISTINCT event_code, user_id FROM notification_deliveries"
            " WHERE tenant_id = $1 AND record_id = $2 AND channel = 'in_app'",
            org_tenant,
            uuid.UUID(record_id),
        )
    finally:
        await conn.close()
    return sorted((r["event_code"], r["user_id"]) for r in found)


async def test_followers_hear_of_an_update_and_of_the_end(world: World) -> None:
    """REQ-PRT-009 AC3, through the one notification engine; nobody else is told."""
    a = world.a
    live = await world.published(a, title="Mail is slow today")
    await world.call("PUT", f"{BASE}/{live['id']}/follow", a, a.requester)
    changed = await world.call(
        "PATCH",
        f"{BASE}/{live['id']}",
        a,
        a.admin,
        json={"body": "Mail is slow today. A fix is on its way."},
        headers={"If-Match": f'"{live["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    taken_down = await world.act(a, a.admin, changed.json(), "unpublish")
    assert taken_down.status_code == 200, taken_down.text
    told = await _deliveries(world, a.tenant, live["id"])
    assert told == [
        ("announcement.ended", a.requester),
        ("announcement.updated", a.requester),
    ]
