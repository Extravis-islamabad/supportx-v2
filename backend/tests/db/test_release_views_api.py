"""The release list's own views (WP-058b S5a; REQ-REL-055).

- AC1: "My releases" lists every release where the person holds any release role (a role
  holder, or the manager or engineer field: both stores are read until they are one).
- AC2: "Unscheduled" lists open releases with no scheduled start; "Scheduled" the others.
- "Unassigned": open, with neither a manager nor an engineer in either store.
- "Deployed": the deployment done, not closed yet.
- Another tenant's releases never show.
"""

import uuid
from typing import Any

import asyncpg

from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_release_guards_api import release_workers
from tests.db.test_release_parts_api import put_role
from tests.db.test_releases_api import REL, a_release

__all__ = ["world"]  # the fixture, re-used


async def _view(world: World, org: Org, user: uuid.UUID, view: str) -> set[str]:
    listed = await world.call("GET", REL, org, user, params={"view": view, "limit": 100})
    assert listed.status_code == 200, listed.text
    return {row["id"] for row in listed.json()["items"]}


async def _details(world: World, org: Org, item: dict[str, Any], **values: Any) -> None:  # noqa: ANN401 - JSON
    current = (await world.call("GET", f"{REL}/{item['id']}", org, org.admin)).json()
    saved = await world.call(
        "PATCH",
        f"{REL}/{item['id']}/details",
        org,
        org.admin,
        json=values,
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert saved.status_code == 200, saved.text


async def test_req_rel_055_ac1_my_releases_lists_any_role_i_hold(world: World) -> None:
    a = world.a
    await release_workers(world, a)
    by_role = await a_release(world, a)
    held = await put_role(world, a, by_role, "qa_lead", users=[a.tech_a])
    assert held.status_code == 200, held.text
    by_field = await a_release(world, a)
    await _details(world, a, by_field, release_engineer_id=str(a.tech_a))
    other = await a_release(world, a)
    mine = await _view(world, a, a.tech_a, "my_releases")
    assert {by_role["id"], by_field["id"]} <= mine
    assert other["id"] not in mine


async def test_req_rel_055_ac2_scheduled_unscheduled_and_unassigned(world: World) -> None:
    a = world.a
    await release_workers(world, a)
    planned = await a_release(world, a)
    await _details(
        world,
        a,
        planned,
        scheduled_start="2027-03-10T09:00:00Z",
        scheduled_end="2027-03-11T09:00:00Z",
        release_manager_id=str(a.tech_b),
    )
    bare = await a_release(world, a)
    unscheduled = await _view(world, a, a.admin, "unscheduled")
    scheduled = await _view(world, a, a.admin, "scheduled")
    assert bare["id"] in unscheduled
    assert planned["id"] not in unscheduled
    assert planned["id"] in scheduled
    assert bare["id"] not in scheduled
    unassigned = await _view(world, a, a.admin, "release_unassigned")
    assert bare["id"] in unassigned
    assert planned["id"] not in unassigned


async def test_deployed_lists_releases_past_their_deployment_and_not_closed(world: World) -> None:
    a = world.a
    deployed, training, closed = [await a_release(world, a) for _ in range(3)]
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        for item, status, stage, category in (
            (deployed, "deployment_deployed", "deployment", "resolved"),
            (training, "training_in_progress", "training", "open"),
            (closed, "closure_closed", "closure", "closed"),
        ):
            await conn.execute(
                "UPDATE work_items SET status = $3, stage = $4, status_category = $5"
                " WHERE tenant_id = $1 AND id = $2",
                a.tenant,
                uuid.UUID(item["id"]),
                status,
                stage,
                category,
            )
    finally:
        await conn.close()
    found = await _view(world, a, a.admin, "deployed")
    assert {deployed["id"], training["id"]} <= found
    assert closed["id"] not in found
    # Another tenant sees none of them.
    assert not found & await _view(world, world.b, world.b.admin, "deployed")
