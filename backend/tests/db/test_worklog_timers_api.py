"""Personal timers over HTTP (WP-046a S3; REQ-INC-069).

Real PostgreSQL, the incidents test world. A timer is its owner's own; stopping prefills a
worklog and logs nothing; resolving or closing with one running saves a draft that counts once
its owner confirms it; auto-start (off by default) starts once for the record's technician.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, Org, World, problem

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, used by name


async def _backdate(world: World, org: Org, item: dict[str, Any], minutes: int) -> None:
    """The running timer started `minutes` ago (the test's clock), tenant explicit."""
    await world.sql(
        "UPDATE work_item_timers SET started_at = $3"
        " WHERE tenant_id = $1 AND work_item_id = $2 AND deleted_at IS NULL",
        org.tenant,
        uuid.UUID(item["id"]),
        datetime.now(UTC) - timedelta(minutes=minutes, seconds=10),
    )


async def _worklogs(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{BASE}/{item['id']}/worklogs", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def test_req_inc_069_ac1_stopping_prefills_the_time_and_logs_nothing(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    path = f"{BASE}/{item['id']}/timer"
    assert (await world.call("GET", path, a, a.tech_a)).json() is None
    started = await world.call("POST", path, a, a.tech_a, json={"comment": "Swapping the fuser"})
    assert started.status_code == 201, started.text
    again = await world.call("POST", path, a, a.tech_a, json={})
    assert problem(again) == (409, "timer_running")  # one running per person per record
    # Someone else's timer is their own, and never shown to the first person.
    other = await world.call("POST", path, a, a.admin, json={})
    assert other.status_code == 201, other.text
    mine = (await world.call("GET", "/my-timers", a, a.tech_a)).json()
    assert [(t["display_id"], t["timer"]["comment"]) for t in mine] == [
        (item["display_id"], "Swapping the fuser")
    ]
    await _backdate(world, a, item, 25)
    stopped = await world.call("POST", f"{path}/stop", a, a.tech_a)
    assert stopped.status_code == 200, stopped.text
    assert (stopped.json()["minutes"], stopped.json()["comment"]) == (25, "Swapping the fuser")
    assert (await world.call("GET", path, a, a.tech_a)).json() is None
    assert (await _worklogs(world, a, item))["items"] == []  # nothing logged until saved
    gone = await world.call("POST", f"{path}/stop", a, a.tech_a)
    assert problem(gone) == (409, "timer_not_running")


async def test_req_inc_069_ac2_resolving_saves_running_timers_as_drafts(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    path = f"{BASE}/{item['id']}/timer"
    assert (
        await world.call("POST", path, a, a.tech_a, json={"comment": "Cable"})
    ).status_code == 201
    await _backdate(world, a, item, 40)
    item = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    resolved = await world.act(a, a.admin, item, "resolve")
    assert resolved.status_code == 200, resolved.text
    found = await _worklogs(world, a, item)
    [draft] = found["items"]
    assert (draft["draft"], draft["owner_id"], draft["minutes"]) == (True, str(a.tech_a), 40)
    assert found["minutes"] == 0  # a draft counts nowhere until confirmed
    assert (await world.call("GET", path, a, a.tech_a)).json() is None  # the timer ended
    # A resolved record takes no new timer: log the time instead.
    late = await world.call("POST", path, a, a.tech_a, json={})
    assert problem(late) == (409, "timer_record_done")
    confirmed = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}/worklogs/{draft['id']}",
        a,
        a.tech_a,
        json={"draft": False, "worklog_type": "fix"},
        headers={"If-Match": f'"{draft["version"]}"'},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert (await _worklogs(world, a, item))["minutes"] == 40


async def _auto_start(world: World, org: Org, *, on: bool) -> None:
    current = (await world.call("GET", f"{BASE}/settings", org, org.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{BASE}/settings/closure",
        org,
        org.admin,
        json={"timer_auto_start": on},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert changed.status_code == 200, changed.text


async def test_req_inc_069_auto_start_once_for_the_technician_and_off_by_default(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    auto = f"{BASE}/{item['id']}/timer/auto"
    assert (await world.call("POST", auto, a, a.tech_a)).json() is None  # off by default
    await _auto_start(world, a, on=True)
    try:
        assert (await world.call("POST", auto, a, a.admin)).json() is None  # not the technician
        first = (await world.call("POST", auto, a, a.tech_a)).json()
        assert first is not None
        assert first["auto_started"] is True
        stop = await world.call("POST", f"{BASE}/{item['id']}/timer/stop", a, a.tech_a)
        assert stop.status_code == 200, stop.text
        assert (await world.call("POST", auto, a, a.tech_a)).json() is None  # never again
    finally:
        await _auto_start(world, a, on=False)  # the shared world: back to the default


async def test_timers_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    assert (
        await world.call("POST", f"{BASE}/{item['id']}/timer", a, a.tech_a, json={})
    ).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (await session.execute(text("SELECT id FROM work_item_timers"))).all()
        assert rows == []
        changed = await session.execute(text("UPDATE work_item_timers SET comment = 'x'"))
        assert changed.rowcount == 0
    assert (await world.call("GET", "/my-timers", b, b.admin)).json() == []


async def test_audit_19_a_retried_start_with_its_key_starts_one_timer(world: World) -> None:
    """A lost answer retried with the same key replays the first, never `timer_running`."""
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    path = f"{BASE}/{item['id']}/timer"
    key = {"Idempotency-Key": uuid.uuid4().hex}
    first = await world.call("POST", path, a, a.tech_a, json={}, headers=key)
    again = await world.call("POST", path, a, a.tech_a, json={}, headers=key)
    assert first.status_code == 201, first.text
    assert again.status_code == 201, again.text
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert again.json() == first.json()
