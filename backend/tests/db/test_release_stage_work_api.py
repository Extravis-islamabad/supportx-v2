"""A release's stage work over HTTP (WP-058b S3; REQ-REL-048; lane A's shared refusal).

Real PostgreSQL with RLS:
- leaving a stage with open tasks is refused, naming the first open task and how many more
  (never its description); the release setting turns it off; canceling is never held up;
- a worklog takes the staged record's stage when logged (never from the client); an incident's
  has none.
"""

import uuid
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE as INC
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_releases_api import REL, a_release, move, panel

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def task(world: World, org: Org, item: dict[str, Any], title: str) -> dict[str, Any]:
    made = await world.call(
        "POST",
        f"{REL}/{item['id']}/tasks",
        org,
        org.admin,
        json={"title": title, "description": "<p>Secret steps</p>"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def fresh(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.call("GET", f"{REL}/{item['id']}", org, org.admin)).json())


async def _leave(world: World, org: Org, item: dict[str, Any]) -> httpx.Response:
    """Accept the submission, then try the first offered move into another stage (not cancel).

    Accepting completes the stage; if the engine moves on by itself, that move is the answer.
    """
    accepted = await move(world, org, item, "submission_accepted")
    if accepted.status_code != 200:
        return accepted
    item = await fresh(world, org, item)
    shown = await panel(world, org, item)
    if shown["stage"] != "submission":
        return accepted
    target = next(
        m["to_status"]
        for m in shown["moves"]
        if m["to_stage"] != shown["stage"] and m["to_status"] != "closure_canceled"
    )
    return await move(world, org, item, target)


async def _setting(world: World, org: Org, *, on: bool) -> None:
    current = (await world.call("GET", f"{REL}/settings", org, org.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{REL}/settings",
        org,
        org.admin,
        json={"open_stage_tasks_block": on},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text


async def test_req_rel_048_ac1_open_tasks_hold_the_stage_and_are_named(world: World) -> None:
    a = world.a
    item = await a_release(world, a)
    first = await task(world, a, item, "Freeze the branch")
    await task(world, a, item, "Tag the build")
    assert first["stage"] == item["stage"]
    refused = await _leave(world, a, await fresh(world, a, item))
    assert refused.status_code != 200, refused.text
    assert problem(refused) == (409, "stage_move_refused"), refused.text
    params = refused.json()["params"]
    assert (params["reason"], params["task"], params["more"], params["tasks"]) == (
        "stage_tasks_open",
        "Freeze the branch",
        1,
        2,
    )
    assert "Secret steps" not in refused.text  # the title only, never the description
    # Canceling is never held up by open tasks.
    other = await a_release(world, a)
    await task(world, a, other, "Never mind")
    canceled = await move(
        world, a, await fresh(world, a, other), "closure_canceled", reason_text="Not needed"
    )
    assert canceled.status_code == 200, canceled.text


async def test_the_release_setting_lets_a_stage_be_left_with_open_tasks(world: World) -> None:
    a = world.a
    await _setting(world, a, on=False)
    try:
        item = await a_release(world, a)
        await task(world, a, item, "Optional check")
        left = await _leave(world, a, await fresh(world, a, item))
        assert left.status_code == 200, left.text
    finally:
        await _setting(world, a, on=True)
    # Changes cannot take it (releases only).
    current = (await world.call("GET", "/changes/settings", a, a.admin)).json()
    refused = await world.call(
        "PATCH",
        "/changes/settings",
        a,
        a.admin,
        json={"open_stage_tasks_block": False},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert problem(refused)[0] == 422, refused.text


async def test_a_worklog_takes_the_stage_of_a_staged_record_only(world: World) -> None:
    a = world.a
    item = await a_release(world, a)
    body = {
        "worklog_type": "fix",
        "started_at": "2027-01-04T09:00:00Z",
        "ended_at": "2027-01-04T10:00:00Z",
        "stage": "closure",  # never taken from the client
    }
    logged = await world.call(
        "POST",
        f"{REL}/{item['id']}/worklogs",
        a,
        a.admin,
        json={k: v for k, v in body.items() if k != "stage"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert logged.status_code == 201, logged.text
    assert logged.json()["stage"] == item["stage"]
    incident = await world.create(a, a.admin)
    plain = await world.call(
        "POST",
        f"{INC}/{incident['id']}/worklogs",
        a,
        a.admin,
        json={k: v for k, v in body.items() if k != "stage"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert plain.status_code == 201, plain.text
    assert plain.json()["stage"] is None
