"""The workflow overview and its bulk jobs (WP-048b S3b; REQ-WF-025).

- The overview lists runs by workflow, state and node, failed ones with their node and error.
- Bulk retry and cancel run as background jobs: each run's result is kept, a run the action
  does not apply to is skipped with the code why, and the others go on.
- Only workflows.manage holders see the overview or queue a job (ADR-043 §10).
"""

import json
import uuid
from typing import Any

from app.modules.automation.service.workflow_jobs import run_jobs
from tests.db.test_incidents_api import CONSOLE, World, world
from tests.db.test_workflow_events import WAIT_FOR_P1, _node, _start, _workflow

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"


def _bad_set() -> dict[str, Any]:
    """A field step the record refuses at run time, with no error output: the run fails."""
    return {
        "format": 1,
        "nodes": [
            _node("s", "start"),
            _node("set", "field_update", values={"impact": "not_an_impact"}),
            _node("e", "end"),
        ],
        "links": [
            {"from": "s", "port": "next", "to": "set"},
            {"from": "set", "port": "next", "to": "e"},
        ],
        "variables": [],
    }


async def _runs(
    world: World, definition: dict[str, Any], count: int
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    a = world.a
    flow = await _workflow(world, definition)
    found = []
    for _ in range(count):
        item = await world.create(a, a.admin)
        found.append(await _start(world, flow, item["id"]))
    return flow, found


async def _queue(world: World, flow: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        f"{BASE}/{flow}/jobs",
        world.a,
        world.a.admin,
        json=body,
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def _job(world: World, job_id: str) -> dict[str, Any]:
    got = await world.call("GET", f"{BASE}/jobs/{job_id}", world.a, world.a.admin)
    assert got.status_code == 200, got.text
    return dict(got.json())


async def test_req_wf_025_the_overview_lists_failed_runs_with_their_node_and_error(
    world: World,
) -> None:
    a = world.a
    flow, failed = await _runs(world, _bad_set(), 2)
    other, _waiting = await _runs(world, WAIT_FOR_P1, 1)
    listed = await world.call(
        "GET",
        f"{BASE}/instances",
        a,
        a.admin,
        params={"status": "failed", "workflow_id": str(flow)},
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["items"]
    assert {r["id"] for r in rows} == {str(i) for i in failed}
    assert {r["failure"]["node"] for r in rows} == {"set"}
    at_wait = await world.call(
        "GET", f"{BASE}/instances", a, a.admin, params={"node": "w", "workflow_id": str(other)}
    )
    assert [r["status"] for r in at_wait.json()["items"]] == ["waiting"]
    refused = await world.call("GET", f"{BASE}/instances", a, a.tech_a)
    assert refused.status_code == 403  # the overview is the admins' (workflows.manage)


async def test_req_wf_025_ac2_bulk_retry_runs_as_a_job_and_reports_each_result(
    world: World,
) -> None:
    flow, failed = await _runs(world, _bad_set(), 2)
    queued = await _queue(world, flow, kind="retry", instance_ids=[str(i) for i in failed])
    assert queued.status_code == 202, queued.text
    assert queued.json()["status"] == "queued"
    await run_jobs(world.app.state.db, world.app.state.settings)
    job = await _job(world, queued.json()["id"])
    assert (job["status"], job["processed"], job["done_count"]) == ("done", 2, 2)
    assert {r["instance_id"] for r in job["results"]} == {str(i) for i in failed}
    steps = await world.sql(
        "SELECT count(*) AS n FROM workflow_steps"
        " WHERE result = 'retried' AND instance_id = ANY($1)",
        failed,
    )
    assert steps[0]["n"] == 2


async def test_a_run_the_action_does_not_fit_is_skipped_and_the_job_goes_on(world: World) -> None:
    flow, waiting = await _runs(world, WAIT_FOR_P1, 2)
    queued = await _queue(world, flow, kind="retry", instance_ids=[str(i) for i in waiting])
    await run_jobs(world.app.state.db, world.app.state.settings)
    job = await _job(world, queued.json()["id"])
    assert (job["status"], job["done_count"], job["skipped_count"]) == ("done", 0, 2)
    assert {r["code"] for r in job["results"]} == {"instance_not_failed"}


async def test_bulk_cancel_needs_a_reason_and_stops_each_run(world: World) -> None:
    flow, waiting = await _runs(world, WAIT_FOR_P1, 2)
    ids = [str(i) for i in waiting]
    no_reason = await _queue(world, flow, kind="cancel", instance_ids=ids)
    assert no_reason.status_code == 422
    queued = await _queue(world, flow, kind="cancel", instance_ids=ids, reason="Old process")
    assert queued.status_code == 202, queued.text
    await run_jobs(world.app.state.db, world.app.state.settings)
    rows = await world.sql(
        "SELECT status, stopped_reason FROM workflow_instances WHERE id = ANY($1)", waiting
    )
    assert {(r["status"], r["stopped_reason"]) for r in rows} == {("cancelled", "Old process")}
    # The audit keeps what was done to how many runs, and why (WP-048b S5).
    rows = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        world.a.tenant,
        "automation.workflow_job_queued",
    )
    found = [
        r["details"] if isinstance(r["details"], dict) else json.loads(r["details"]) for r in rows
    ]
    assert {"kind": "cancel", "runs": 2, "reason": "Old process"}.items() <= next(
        d for d in found if d.get("reason") == "Old process"
    ).items()


async def test_a_job_takes_only_runs_of_its_own_workflow(world: World) -> None:
    flow, _mine = await _runs(world, WAIT_FOR_P1, 1)
    _other, theirs = await _runs(world, WAIT_FOR_P1, 1)
    refused = await _queue(world, flow, kind="retry", instance_ids=[str(theirs[0])])
    assert refused.status_code == 422
    assert refused.json()["code"] == "instances_not_in_workflow"
