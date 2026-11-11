"""D-157 item 4: e-mails given up for want of outgoing mail tell the admins once per run.

The incident world (tests/db/test_incidents_api.py): org A's admin may set mail up
(`integrations.manage_email`, every permission); the technicians may not. Replies made while
mail is not set up wait (D-116); 7 days on, the waiting schedule gives them up. Each run that
gives any up sends ONE in-app notice to each person who may set mail up, with a link to the
mail settings; a run that gives none up sends nothing.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.notifications.service.engine import expire_waiting
from tests.db import test_incidents_api
from tests.db.test_conversation_api import say
from tests.db.test_incidents_api import Org, World
from tests.db.test_notifications_api import NO_MAIL, run_engine

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused

SUMMARY = "notifications.mail.not_sent_summary"


async def _expire(world: World, org: Org, now: datetime | None = None) -> int:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            return await expire_waiting(session, now)
    finally:
        await database.dispose()


async def _summaries(world: World, org: Org) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2 ORDER BY id",
        org.tenant,
        SUMMARY,
    )
    return [json.loads(r["envelope"])["payload"] for r in rows]


async def _notices(world: World, org: Org) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT user_id, title, link FROM notifications"
        " WHERE tenant_id = $1 AND record_type = 'outgoing_mail' ORDER BY created_at",
        org.tenant,
    )
    return [dict(r) for r in rows]


async def test_a_run_that_gives_up_three_emails_tells_each_admin_once(world: World) -> None:
    a = world.a
    for subject in ("Printer jams", "VPN drops", "Laptop slow"):
        item = await world.create(a, a.admin, subject=subject)
        made = await say(world, a, a.admin, item, kind="reply", body="<p>On it.</p>")
        assert made.status_code == 201, made.text
    await run_engine(world, a, settings=NO_MAIL)
    waiting = await world.sql(
        "SELECT id FROM notification_deliveries WHERE tenant_id = $1 AND state = 'waiting'"
        " ORDER BY created_at",
        a.tenant,
    )
    assert len(waiting) >= 3, waiting
    old = [r["id"] for r in waiting[:3]]
    await world.sql(
        "UPDATE notification_deliveries SET created_at = now() - interval '8 days'"
        " WHERE id = ANY($1::uuid[])",
        old,
    )
    assert await _expire(world, a) == 3
    (summary,) = await _summaries(world, a)
    assert summary["count"] == 3
    assert set(summary) >= {"summary_id", "count", "oldest_at"}
    assert "@" not in json.dumps(summary)  # counts and a time only
    await run_engine(world, a, settings=NO_MAIL)
    notices = await _notices(world, a)
    assert [n["user_id"] for n in notices] == [a.admin]  # the one who may set mail up, once
    assert notices[0]["link"] == "/admin/mail"
    assert "3" in notices[0]["title"]
    # In the app only: no e-mail was made for the summary (none could be sent).
    emails = await world.sql(
        "SELECT count(*) AS n FROM notification_deliveries WHERE tenant_id = $1"
        " AND record_type = 'outgoing_mail' AND channel = 'email'",
        a.tenant,
    )
    assert emails[0]["n"] == 0
    # The next run gives none up: no summary, no notice.
    assert await _expire(world, a) == 0
    await run_engine(world, a, settings=NO_MAIL)
    assert len(await _summaries(world, a)) == 1
    assert len(await _notices(world, a)) == 1


async def test_a_run_that_gives_up_nothing_sends_nothing(world: World) -> None:
    b = world.b
    assert await _expire(world, b) == 0
    await run_engine(world, b, settings=NO_MAIL)
    assert await _summaries(world, b) == []
    assert await _notices(world, b) == []


async def test_a_retried_run_tells_the_admins_once(world: World) -> None:
    """Lane A: the run's summary is claimed once (tenant + cut-off minute, processed_events)."""
    a = world.a
    item = await world.create(a, a.admin, subject="Scanner offline")
    made = await say(world, a, a.admin, item, kind="reply", body="<p>Looking.</p>")
    assert made.status_code == 201, made.text
    await run_engine(world, a, settings=NO_MAIL)
    waiting = [
        r["id"]
        for r in await world.sql(
            "SELECT id FROM notification_deliveries WHERE tenant_id = $1 AND state = 'waiting'",
            a.tenant,
        )
    ]
    assert waiting

    async def backdate() -> None:
        await world.sql(
            "UPDATE notification_deliveries SET state = 'waiting', reason = NULL,"
            " created_at = now() - interval '8 days' WHERE id = ANY($1::uuid[])",
            waiting,
        )

    moment = datetime.now(UTC)
    await backdate()
    assert await _expire(world, a, moment) == len(waiting)
    await backdate()  # the same run again, as a retry would
    assert await _expire(world, a, moment) == len(waiting)
    assert len(await _summaries(world, a)) == 1
    await run_engine(world, a, settings=NO_MAIL)
    assert [n["user_id"] for n in await _notices(world, a)] == [a.admin]
