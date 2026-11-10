"""Fulfilment from the catalog item's plan (WP-030 s3; REQ-SR-021 AC1, -046, -058, -060).

Real PostgreSQL with RLS. The plan becomes tasks at submission (no approval) or on approval,
never before and never after a rejection; the last required task done fulfils the request.
"""

import uuid
from typing import Any

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, decide, fresh, manager_of
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_service_requests_api import SR, an_item, raise_request

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

PLAN = [
    {"title": {"en": "Order the laptop", "ar": "طلب الحاسوب"}},
    {"title": {"en": "Install the software"}, "internal": True},
    {"title": {"en": "Send a welcome note"}, "required": False},
]


async def tasks(world: World, org: Org, record: dict[str, Any]) -> list[dict[str, Any]]:
    found = await world.call("GET", f"{SR}/{record['id']}/tasks", org, org.admin)
    assert found.status_code == 200, found.text
    return list(found.json()["items"])


async def done(world: World, org: Org, record: dict[str, Any], task: dict[str, Any]) -> None:
    changed = await world.call(
        "PATCH",
        f"{SR}/{record['id']}/tasks/{task['id']}",
        org,
        org.admin,
        json={"status": "done"},
        headers={"If-Match": f'"{task["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text


async def test_without_approval_the_plan_starts_at_once_and_fulfils(world: World) -> None:
    """REQ-SR-046 AC1, REQ-SR-058 AC1: in order; the last required one done fulfils it."""
    a = world.a
    item = await an_item(world, a, plan=PLAN)
    record = (
        await raise_request(world, a, a.admin, catalog_item_id=item["id"], answers={"model": "air"})
    ).json()
    made = await tasks(world, a, record)
    assert [(t["title"], t["from_plan"], t["required"], t["internal"]) for t in made] == [
        ("Order the laptop", True, True, False),
        ("Install the software", True, True, True),
        ("Send a welcome note", True, False, False),
    ]
    await done(world, a, record, made[0])
    assert (await fresh(world, a, record))["status"] != "fulfilled"
    await done(world, a, record, made[1])  # the optional one stays open
    assert (await fresh(world, a, record))["status"] == "fulfilled"


async def test_the_plan_waits_for_the_approval_and_a_rejection_makes_none(world: World) -> None:
    """REQ-SR-021 AC1, REQ-SR-060."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(
        world, a, plan=PLAN, approval={"approvers": [{"kind": "requested_for_manager"}]}
    )
    made = [
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
        for _ in range(2)
    ]
    first, second = (m.json() for m in made)
    for record in (first, second):
        assert await tasks(world, a, record) == []
    [entry] = await approvals(world, a, a.tech_a, first)
    assert (await decide(world, a, a.tech_a, first, entry, "approve")).status_code == 200
    assert len(await tasks(world, a, first)) == len(PLAN)
    [other] = await approvals(world, a, a.tech_a, second)
    rejected = await decide(world, a, a.tech_a, second, other, "reject", "No budget")
    assert rejected.status_code == 200, rejected.text
    assert await tasks(world, a, second) == []


async def test_an_item_that_does_not_fulfil_itself_waits_for_a_technician(world: World) -> None:
    """REQ-SR-058: per item; without auto-fulfil the request stays open when tasks are done."""
    a = world.a
    item = await an_item(world, a, plan=PLAN[:1], auto_fulfil=False)
    record = (
        await raise_request(world, a, a.admin, catalog_item_id=item["id"], answers={"model": "air"})
    ).json()
    [only] = await tasks(world, a, record)
    await done(world, a, record, only)
    assert (await fresh(world, a, record))["status"] == "new"
    assert uuid.UUID(only["id"])


async def tick(
    world: World, org: Org, user: uuid.UUID, record: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    changed = await world.call(
        "PATCH",
        f"{SR}/{record['id']}/tasks/{task['id']}",
        org,
        user,
        json={"status": "done"},
        headers={"If-Match": f'"{task["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    return dict(changed.json())


async def test_d154_the_first_task_its_group_ticks_starts_the_work_and_names_who(
    world: World,
) -> None:
    """D-154c/d: a New request moves to In progress when someone of its group ticks a task;
    nobody is assigned by it; the task says who did it, also once opened again."""
    a = world.a
    item = await an_item(world, a, plan=PLAN)
    record = (
        await raise_request(
            world,
            a,
            a.admin,
            catalog_item_id=item["id"],
            answers={"model": "air"},
            group_id=str(a.ga),
        )
    ).json()
    assert record["status"] == "new"
    first = (await tasks(world, a, record))[0]
    ticked = await tick(world, a, a.tech_a, record, first)  # tech_a is in GA
    assert ticked["done_by"] == str(a.tech_a)
    now = await fresh(world, a, record)
    assert (now["status"], now["technician_id"]) == ("in_progress", None)
    entries = (await world.call("GET", f"{SR}/{record['id']}/history", a, a.admin)).json()["items"]
    moved = [e for e in entries if any(c["field"] == "status" for c in e["changes"])]
    assert moved[0]["automation"] == {
        "kind": "auto_move",
        "rule": "first_task",
        "action": "start_work",
    }
    reopened = await world.call(
        "PATCH",
        f"{SR}/{record['id']}/tasks/{first['id']}",
        a,
        a.tech_a,
        json={"status": "open"},
        headers={"If-Match": f'"{ticked["version"]}"', **CONSOLE},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["done_by"] is None


async def test_d154_the_tenant_may_turn_the_first_task_move_off(world: World) -> None:
    """D-154c: the tenant switch (on by default) keeps a ticked task from moving the request."""
    a = world.a
    settings = (await world.call("GET", f"{SR}/settings", a, a.admin)).json()
    assert settings["first_task_starts_work"] is True
    off = await world.call(
        "PATCH",
        f"{SR}/settings",
        a,
        a.admin,
        json={"first_task_starts_work": False},
        headers={"If-Match": f'"{settings["version"]}"', **CONSOLE},
    )
    assert off.status_code == 200, off.text
    item = await an_item(world, a, plan=PLAN)
    record = (
        await raise_request(
            world,
            a,
            a.admin,
            catalog_item_id=item["id"],
            answers={"model": "air"},
            group_id=str(a.ga),
        )
    ).json()
    await tick(world, a, a.tech_a, record, (await tasks(world, a, record))[0])
    assert (await fresh(world, a, record))["status"] == "new"
