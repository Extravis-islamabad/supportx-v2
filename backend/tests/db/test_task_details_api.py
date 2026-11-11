"""Task details, dependencies, templates and "my tasks" (WP-046a S1; REQ-INC-040, 073..076).

Real PostgreSQL with RLS. An end before its start is refused; a task whose predecessor is
open cannot start or complete (named in the 409) unless the type warns; a loop or another
record's task is refused; task templates add their tasks ready to edit and a disabled one is not
offered; a record template's tasks are added when their condition matches, recorded as the
template's; "my tasks" lists tasks on every type, never on a record the person can no longer see.
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, problem

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

START = "2026-12-01T09:00:00Z"
BEFORE_START = "2026-12-01T08:00:00Z"


async def _task(
    world: World,
    org: Org,
    item: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/tasks",
        org,
        org.admin,
        json={"title": "A task", **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def _made(world: World, org: Org, item: dict[str, Any], **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made = await _task(world, org, item, **body)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _patch(
    world: World,
    org: Org,
    user: uuid.UUID,
    task: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "PATCH",
        f"{BASE}/{task['work_item_id']}/tasks/{task['id']}",
        org,
        user,
        json=body,
        headers={"If-Match": f'"{task["version"]}"', **CONSOLE},
    )


async def _waits(
    world: World, org: Org, task: dict[str, Any], *on: dict[str, Any]
) -> httpx.Response:
    return await world.call(
        "PUT",
        f"{BASE}/{task['work_item_id']}/tasks/{task['id']}/dependencies",
        org,
        org.admin,
        json={"depends_on": [t["id"] for t in on]},
        headers=CONSOLE,
    )


async def test_req_inc_073_details_are_kept_and_an_end_before_its_start_is_refused(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    backwards = await _task(world, a, item, scheduled_start=START, scheduled_end=BEFORE_START)
    assert problem(backwards)[0] == 422, backwards.text
    assert "end_before_start" in backwards.text
    lonely = await _task(world, a, item, remind_before_minutes=30)
    assert "needs_scheduled_start" in lonely.text
    task = await _made(
        world,
        a,
        item,
        task_type="backup",
        scheduled_start=START,
        scheduled_end="2026-12-01T11:00:00Z",
        estimated_minutes=90,
        percent_complete=20,
        extra_cost="125.50",
        remind_before_minutes=30,
    )
    assert (task["task_type"], task["estimated_minutes"], task["percent_complete"]) == (
        "backup",
        90,
        20,
    )
    assert task["extra_cost"] == "125.50"
    # A later end before the kept start is refused too (the details checked together).
    moved = await _patch(world, a, a.admin, task, scheduled_end=BEFORE_START)
    assert problem(moved)[0] == 422, moved.text


async def test_req_inc_075_an_open_predecessor_blocks_naming_it_until_done(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    first = await _made(world, a, item, title="Back up the switch")
    second = await _made(world, a, item, title="Upgrade the firmware")
    set_ = await _waits(world, a, second, first)
    assert set_.status_code == 200, set_.text
    listed = {t["id"]: t for t in set_.json()["items"]}
    assert listed[second["id"]]["blocked_by"] == [first["id"]]
    refused = await _patch(world, a, a.admin, second, status="in_progress")
    assert problem(refused) == (409, "task_blocked"), refused.text
    assert refused.json()["params"]["task"] == "Back up the switch"
    done = await _patch(world, a, a.admin, first, status="done")
    assert done.status_code == 200, done.text
    started = await _patch(world, a, a.admin, second, status="in_progress")
    assert started.status_code == 200, started.text
    assert started.json()["blocked_by"] == []


async def test_req_inc_075_ac3_a_loop_or_another_record_s_task_is_refused(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    one, two = await _made(world, a, item), await _made(world, a, item)
    assert (await _waits(world, a, two, one)).status_code == 200
    loop = await _waits(world, a, one, two)
    assert problem(loop)[0] == 422, loop.text
    assert "dependency_loop" in loop.text
    other = await _made(world, a, await world.create(a, a.admin))
    elsewhere = await _waits(world, a, one, other)
    assert problem(elsewhere)[0] == 422, elsewhere.text


async def test_req_inc_074_a_template_adds_its_tasks_and_a_disabled_one_is_not_offered(
    world: World,
) -> None:
    a = world.a
    made = await world.call(
        "POST",
        f"{BASE}/task-templates",
        a,
        a.admin,
        json={
            "name": f"Laptop set-up {uuid.uuid4().hex[:6]}",
            "tasks": [{"title": "Image the laptop"}, {"title": "Hand it over", "priority": "high"}],
        },
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    template = made.json()
    item = await world.create(a, a.admin)
    added = await world.call(
        "POST",
        f"{BASE}/{item['id']}/tasks/from-template",
        a,
        a.admin,
        json={"template_id": template["id"]},
        headers=CONSOLE,
    )
    assert added.status_code == 201, added.text
    titles = [t["title"] for t in added.json()["items"]]
    assert titles[-2:] == ["Image the laptop", "Hand it over"]
    off = await world.call(
        "PATCH",
        f"{BASE}/task-templates/{template['id']}",
        a,
        a.admin,
        json={"disabled": True},
        headers={"If-Match": f'"{template["version"]}"', **CONSOLE},
    )
    assert off.status_code == 200, off.text
    offered = await world.call("GET", f"{BASE}/task-templates", a, a.tech_a)
    assert template["id"] not in {t["id"] for t in offered.json()}
    again = await world.call(
        "POST",
        f"{BASE}/{item['id']}/tasks/from-template",
        a,
        a.admin,
        json={"template_id": template["id"]},
        headers=CONSOLE,
    )
    assert problem(again) == (404, "task_template_not_found"), again.text
    # A technician cannot keep templates.
    refused = await world.call(
        "POST",
        f"{BASE}/task-templates",
        a,
        a.tech_a,
        json={"name": "Mine", "tasks": [{"title": "x"}]},
        headers=CONSOLE,
    )
    assert refused.status_code == 403, refused.text


async def test_req_inc_076_my_tasks_cover_every_type_but_never_a_record_i_cannot_see(
    world: World,
) -> None:
    a = world.a
    seen = await world.create(a, a.admin, group_id=str(a.ga))
    mine = await _made(world, a, seen, owner_id=str(a.tech_a), due_at="2020-01-01T00:00:00Z")
    hidden = await world.create(a, a.admin, group_id=str(a.gb))  # tech_a is not in GB
    gone = await _made(world, a, hidden, owner_id=str(a.tech_a))
    listed = await world.call("GET", "/my-tasks", a, a.tech_a)
    assert listed.status_code == 200, listed.text
    by_id = {row["task"]["id"]: row for row in listed.json()}
    assert mine["id"] in by_id
    assert by_id[mine["id"]]["record_type"] == "incident"
    assert by_id[mine["id"]]["task"]["overdue"] is True  # AC2
    assert by_id[mine["id"]]["task"]["extra_cost"] is None  # cost stays on the record
    assert gone["id"] not in by_id  # the coordinator's check


async def test_the_new_task_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    item = await world.create(a, a.admin)
    one, two = await _made(world, a, item), await _made(world, a, item)
    assert (await _waits(world, a, two, one)).status_code == 200
    made = await world.call(
        "POST",
        f"{BASE}/task-templates",
        a,
        a.admin,
        json={"name": f"A only {uuid.uuid4().hex[:6]}", "tasks": [{"title": "x"}]},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table, column, value in (
            ("work_item_task_templates", "id", made.json()["id"]),
            ("work_item_task_dependencies", "task_id", two["id"]),
        ):
            rows = await session.execute(
                text(f"SELECT 1 FROM {table} WHERE {column} = :v"),  # noqa: S608 - fixed names
                {"v": value},
            )
            assert rows.all() == [], table
        written = await session.execute(
            text("UPDATE work_item_task_templates SET name = 'x' WHERE id = :v"),
            {"v": made.json()["id"]},
        )
        assert written.rowcount == 0
    offered = await world.call("GET", f"{BASE}/task-templates", b, b.admin)
    assert made.json()["id"] not in {t["id"] for t in offered.json()}


async def test_req_inc_075_the_type_may_make_an_open_predecessor_only_warn(world: World) -> None:
    a = world.a

    async def mode(value: str) -> None:
        current = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
        changed = await world.call(
            "PATCH",
            f"{BASE}/settings/closure",
            a,
            a.admin,
            json={"task_dependency_mode": value},
            headers={"If-Match": f'"{current["version"]}"'},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["closure"]["task_dependency_mode"] == value

    item = await world.create(a, a.admin)
    first, second = await _made(world, a, item), await _made(world, a, item)
    assert (await _waits(world, a, second, first)).status_code == 200
    await mode("warn")
    try:
        started = await _patch(world, a, a.admin, second, status="in_progress")
        assert started.status_code == 200, started.text
        assert started.json()["blocked_by"] == [first["id"]]  # still shown as blocked
    finally:
        await mode("block")


async def test_req_inc_040_a_record_template_adds_its_tasks_when_they_match(world: World) -> None:
    a = world.a
    made = await world.call(
        "POST",
        f"{BASE}/templates",
        a,
        a.admin,
        json={
            "labels": {"en": f"Server outage {uuid.uuid4().hex[:6]}"},
            "tasks": [
                {"title": "Tell the service owner"},
                {
                    "title": "Open a bridge call",
                    "condition": {"field": "priority", "op": "eq", "value": "p1"},
                },
            ],
        },
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    template = made.json()
    assert [t["title"] for t in template["tasks"]] == [
        "Tell the service owner",
        "Open a bridge call",
    ]
    bad = await world.call(
        "POST",
        f"{BASE}/templates",
        a,
        a.admin,
        json={
            "labels": {"en": f"Bad {uuid.uuid4().hex[:6]}"},
            "tasks": [{"title": "x", "condition": {"field": "nope", "op": "eq", "value": 1}}],
        },
        headers=CONSOLE,
    )
    assert problem(bad)[0] == 422, bad.text

    async def tasks_of(**fields: str) -> list[str]:
        item = await world.create(a, a.admin, template_id=template["id"], **fields)
        listed = await world.call("GET", f"{BASE}/{item['id']}/tasks", a, a.admin)
        return [t["title"] for t in listed.json()["items"]]

    assert await tasks_of(priority="p1", priority_reason="Major outage") == [
        "Tell the service owner",
        "Open a bridge call",
    ]
    assert await tasks_of(priority="p4", priority_reason="Minor") == ["Tell the service owner"]
