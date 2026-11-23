"""Personal reminders (WP-046a S2; REQ-INC-082).

Real PostgreSQL with RLS: a reminder is its owner's alone, administrators included (AC2, the
coordinator); it alerts once at its time minus its lead (AC1); completing it leaves the open
list and keeps it on the record as done (AC3); if its owner loses access to the record, no alert
is sent and it reads "no longer available" (the coordinator).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.work_items.service import reminders
from app.shared.clock import FrozenClock
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_change_notifications import sent
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World
from tests.db.test_notifications_api import run_engine

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _sweep(world: World, org: Org, now: datetime) -> int:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            return await reminders.sweep(session, FrozenClock(now))
    finally:
        await database.dispose()


async def _remind(
    world: World, org: Org, user: uuid.UUID, item: dict[str, Any], at: datetime, lead: int = 15
) -> dict[str, Any]:
    made = await world.call(
        "POST",
        f"{BASE}/{item['id']}/reminders",
        org,
        user,
        json={"note": "Call the vendor back", "remind_at": at.isoformat(), "alert_minutes": lead},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_req_inc_082_ac2_a_reminder_is_its_owner_s_alone_admins_included(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=5)
    mine = await _remind(world, a, a.tech_a, item, at)
    for viewer in (a.admin, a.lead):
        on_record = (await world.call("GET", f"{BASE}/{item['id']}/reminders", a, viewer)).json()
        assert mine["id"] not in {r["id"] for r in on_record}, viewer
        theirs = (await world.call("GET", "/my-reminders", a, viewer)).json()
        assert mine["id"] not in {r["id"] for r in theirs}, viewer
        changed = await world.call(
            "PATCH",
            f"/my-reminders/{mine['id']}",
            a,
            viewer,
            json={"done": True},
            headers={"If-Match": f'"{mine["version"]}"'},
        )
        assert changed.status_code == 404, changed.text
    listed = (await world.call("GET", "/my-reminders", a, a.tech_a)).json()
    assert mine["id"] in {r["id"] for r in listed}


async def test_req_inc_082_ac1_ac3_it_alerts_once_at_its_lead_and_completes(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=6)
    mine = await _remind(world, a, a.tech_a, item, at, lead=15)
    assert await _sweep(world, a, at - timedelta(minutes=16)) == 0  # not yet
    assert await _sweep(world, a, at - timedelta(minutes=15)) == 1  # 15:00 alerts at 14:45
    assert await _sweep(world, a, at - timedelta(minutes=5)) == 0  # once
    await run_engine(world, a)
    told = [d for d in await sent(world, a, item["id"], "reminder.due") if d["user_id"] == a.tech_a]
    assert told, "the owner was not alerted"
    fresh = (await world.call("GET", f"{BASE}/{item['id']}/reminders", a, a.tech_a)).json()
    [row] = [r for r in fresh if r["id"] == mine["id"]]
    done = await world.call(
        "PATCH",
        f"/my-reminders/{mine['id']}",
        a,
        a.tech_a,
        json={"done": True},
        headers={"If-Match": f'"{row["version"]}"'},
    )
    assert done.status_code == 200, done.text
    open_list = (await world.call("GET", "/my-reminders", a, a.tech_a)).json()
    assert mine["id"] not in {r["id"] for r in open_list}  # AC3: out of the open list
    on_record = (await world.call("GET", f"{BASE}/{item['id']}/reminders", a, a.tech_a)).json()
    assert [r["done_at"] is not None for r in on_record if r["id"] == mine["id"]] == [True]


async def test_a_reminder_on_a_record_its_owner_lost_is_not_sent_and_says_so(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=7)
    mine = await _remind(world, a, a.tech_a, item, at, lead=0)
    moved = await world.call(
        "POST",
        f"{BASE}/{item['id']}/assign",
        a,
        a.admin,
        json={"group_id": str(a.gb), "reason_code": "wrong_group"},  # tech_a is not in GB
        headers={"If-Match": f'"{(await world.fresh(a, item))["version"]}"', **CONSOLE},
    )
    assert moved.status_code == 200, moved.text
    listed = (await world.call("GET", "/my-reminders", a, a.tech_a)).json()
    [row] = [r for r in listed if r["id"] == mine["id"]]
    assert (row["available"], row["display_id"], row["subject"]) == (False, None, None)
    assert await _sweep(world, a, at) == 1
    await run_engine(world, a)
    told = [d for d in await sent(world, a, item["id"], "reminder.due") if d["user_id"] == a.tech_a]
    assert not [d for d in told if d["state"] == "sent"], told
