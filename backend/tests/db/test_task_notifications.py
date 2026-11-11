"""Task notifications and reminders (WP-046a S1 PR 2; REQ-INC-073 AC2, -076 AC1).

A task given to someone tells them; its reminder before the scheduled start and its overdue
notice are raised once each by the sweep; a reminder for a time that moved says nothing; someone
who cannot see the record hears nothing.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.work_items.service import task_reminders
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
            return await task_reminders.sweep(session, FrozenClock(now))
    finally:
        await database.dispose()


async def _task(world: World, org: Org, item: dict[str, Any], **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made = await world.call(
        "POST",
        f"{BASE}/{item['id']}/tasks",
        org,
        org.admin,
        json={"title": "Swap the PSU", **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_req_inc_076_ac1_a_task_given_to_someone_tells_them(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    await _task(world, a, item, owner_id=str(a.tech_a))
    await run_engine(world, a)
    told = [
        d for d in await sent(world, a, item["id"], "task.assigned") if d["user_id"] == a.tech_a
    ]
    assert {d["channel"] for d in told} >= {"in_app"}, told
    assert all(d["reason"] != "no_access" for d in told), told


async def test_req_inc_073_ac2_the_reminder_and_the_overdue_notice_go_once(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=30)
    await _task(
        world,
        a,
        item,
        owner_id=str(a.tech_a),
        scheduled_start=start.isoformat(),
        remind_before_minutes=60,
        due_at=(start + timedelta(hours=2)).isoformat(),
    )
    assert await _sweep(world, a, start - timedelta(hours=2)) == 0  # not yet
    assert await _sweep(world, a, start - timedelta(minutes=30)) == 1  # inside the hour
    assert await _sweep(world, a, start - timedelta(minutes=20)) == 0  # claimed once
    assert await _sweep(world, a, start + timedelta(hours=3)) == 1  # past due: overdue
    assert await _sweep(world, a, start + timedelta(hours=4)) == 0
    await run_engine(world, a)
    for code in ("task.starts_soon", "task.overdue"):
        told = [d for d in await sent(world, a, item["id"], code) if d["user_id"] == a.tech_a]
        assert told, code


async def test_a_reminder_for_a_moved_start_or_an_unseen_record_says_nothing(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.gb))  # tech_a does not see GB's
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=40)
    task = await _task(
        world,
        a,
        item,
        owner_id=str(a.tech_a),
        scheduled_start=start.isoformat(),
        remind_before_minutes=30,
    )
    assert await _sweep(world, a, start - timedelta(minutes=10)) == 1
    moved = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}/tasks/{task['id']}",
        a,
        a.admin,
        json={"scheduled_start": (start + timedelta(days=1)).isoformat()},
        headers={"If-Match": f'"{task["version"]}"', **CONSOLE},
    )
    assert moved.status_code == 200, moved.text
    await run_engine(world, a)
    told = await sent(world, a, item["id"], "task.starts_soon")
    # The start moved: nothing for the old time. And GB's record is not tech_a's to see.
    assert not [d for d in told if d["user_id"] == a.tech_a and d["state"] == "sent"], told
