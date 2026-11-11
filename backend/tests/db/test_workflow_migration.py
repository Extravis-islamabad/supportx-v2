"""Versions and the migration of running instances (WP-048b S3c; REQ-WF-021, -027).

- Publishing a new version leaves running instances on theirs (AC1).
- A migration with a mapping for every occupied node moves them all, and each record's history
  says so (AC2); a dry run reports what would move and changes nothing (AC3).
- A run whose node has no place in the new version stays on its version and is listed.
- The versions list shows who published each and how many runs are live on it; the preview
  counts a version's live runs per node.
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow, WorkflowVersion
from app.modules.automation.service.workflow_jobs import run_jobs
from tests.db.test_incidents_api import CONSOLE, World, world
from tests.db.test_workflow_events import WAIT_FOR_P1, _flow, _node, _start, _workflow

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"

# Version 2: the wait is renamed ("w" → "hold"), so its runs need a mapping.
V2 = _flow(
    _node("s", "start"),
    _node(
        "hold",
        "wait",
        events=["field_changed"],
        condition={"field": "priority", "op": "eq", "value": "p1"},
    ),
    _node("e", "end"),
    _node("over", "end"),
    links=[("s", "next", "hold"), ("hold", "next", "e"), ("hold", "overtaken", "over")],
)


async def _publish(world: World, flow: uuid.UUID, definition: dict[str, Any], number: int) -> None:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        session.add(
            WorkflowVersion(
                tenant_id=a.tenant,
                workflow_id=flow,
                number=number,
                definition=definition,
                published_by=a.admin,
            )
        )
        found = await session.get(Workflow, flow)
        assert found is not None
        found.published_version = number


async def _three_on_v1(world: World) -> tuple[uuid.UUID, list[uuid.UUID], list[dict[str, Any]]]:
    a = world.a
    flow = await _workflow(world, WAIT_FOR_P1)
    items = [await world.create(a, a.admin) for _ in range(3)]
    runs = [await _start(world, flow, item["id"]) for item in items]
    await _publish(world, flow, V2, 2)
    return flow, runs, items


async def _versions_of(world: World, runs: list[uuid.UUID]) -> list[int]:
    rows = await world.sql(
        "SELECT version_number FROM workflow_instances WHERE id = ANY($1) ORDER BY id", runs
    )
    return [r["version_number"] for r in rows]


async def _migrate(world: World, flow: uuid.UUID, runs: list[uuid.UUID], **body: Any) -> Any:  # noqa: ANN401 - JSON
    queued = await world.call(
        "POST",
        f"{BASE}/{flow}/jobs",
        world.a,
        world.a.admin,
        json={"kind": "migrate", "instance_ids": [str(r) for r in runs], "to_version": 2, **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert queued.status_code == 202, queued.text
    await run_jobs(world.app.state.db, world.app.state.settings)
    got = await world.call("GET", f"{BASE}/jobs/{queued.json()['id']}", world.a, world.a.admin)
    return got.json()


async def test_req_wf_021_ac1_publishing_v2_leaves_running_instances_on_v1(world: World) -> None:
    a = world.a
    flow, runs, _items = await _three_on_v1(world)
    assert await _versions_of(world, runs) == [1, 1, 1]
    listed = await world.call("GET", f"{BASE}/{flow}/versions", a, a.admin)
    assert listed.status_code == 200, listed.text
    assert [(v["number"], v["running"], v["published_by"]) for v in listed.json()] == [
        (2, 0, str(a.admin)),
        (1, 3, None),
    ]
    preview = await world.call("GET", f"{BASE}/{flow}/versions/1/occupancy", a, a.admin)
    assert preview.json() == {"w": 3}


async def test_req_wf_021_ac3_a_dry_run_says_what_would_move_and_changes_nothing(
    world: World,
) -> None:
    flow, runs, _items = await _three_on_v1(world)
    job = await _migrate(world, flow, runs, mapping={"w": "hold"}, dry_run=True)
    assert {r["outcome"] for r in job["results"]} == {"would_move"}
    assert await _versions_of(world, runs) == [1, 1, 1]


async def test_req_wf_021_ac2_a_mapped_migration_moves_them_all_and_history_says_so(
    world: World,
) -> None:
    a = world.a
    flow, runs, items = await _three_on_v1(world)
    job = await _migrate(world, flow, runs, mapping={"w": "hold"})
    assert (job["status"], job["done_count"]) == ("done", 3)
    assert await _versions_of(world, runs) == [2, 2, 2]
    for item in items:
        moved = [
            c
            for h in await world.history(a, item)
            for c in h["changes"]
            if c["field"] == "workflow_version"
        ]
        assert [(c["old"], c["new"]) for c in moved] == [(1, 2)]


async def test_a_run_whose_node_has_no_place_stays_and_is_listed(world: World) -> None:
    flow, runs, _items = await _three_on_v1(world)
    job = await _migrate(world, flow, runs)  # no mapping: "w" is not in version 2
    assert (job["done_count"], job["skipped_count"]) == (0, 3)
    assert {r["code"] for r in job["results"]} == {"node_not_mapped"}
    assert await _versions_of(world, runs) == [1, 1, 1]


async def test_a_version_s_steps_and_its_runs_for_the_move_dialog(world: World) -> None:
    """WP-048b S5c: the dialog reads the target version's steps and lists the runs still on
    the old version (the overview's version_number filter)."""
    a = world.a
    flow, runs, _items = await _three_on_v1(world)
    steps = await world.call("GET", f"{BASE}/{flow}/versions/2/steps", a, a.admin)
    assert steps.status_code == 200, steps.text
    assert [(s["id"], s["type"]) for s in steps.json()] == [
        ("s", "start"),
        ("hold", "wait"),
        ("e", "end"),
        ("over", "end"),
    ]
    missing = await world.call("GET", f"{BASE}/{flow}/versions/9/steps", a, a.admin)
    assert missing.status_code == 404
    on_v1 = await world.call(
        "GET",
        f"{BASE}/instances",
        a,
        a.admin,
        params={
            "filter": json.dumps(
                {
                    "and": [
                        {"field": "workflow_id", "op": "eq", "value": str(flow)},
                        {"field": "version_number", "op": "eq", "value": 1},
                    ]
                }
            )
        },
    )
    assert on_v1.status_code == 200, on_v1.text
    assert {r["id"] for r in on_v1.json()["items"]} == {str(r) for r in runs}
