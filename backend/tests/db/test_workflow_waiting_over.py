"""Runs that have not moved for a while (WP-048b S5b; REQ-WF-025 AC3).

- `waiting_over_hours=` lists the live runs whose latest step is older than that; the others
  (moved recently, finished) are not listed.
- RLS holds: another tenant's admin gets none of them.
- The latest step is read on workflow_steps' primary key (tenant_id, instance_id, seq), which
  starts with tenant_id, backwards: the plan says so (the coordinator, S5 plan).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.test_incidents_api import World, world
from tests.db.test_workflow_events import WAIT_FOR_P1, _start, _workflow

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"


async def _age(world: World, instance: uuid.UUID, hours: int) -> None:
    """Make a run's steps that old (test data only; steps are insert-only for the app)."""
    await world.sql(
        "UPDATE workflow_steps SET at = $2 WHERE instance_id = $1",
        instance,
        datetime.now(UTC) - timedelta(hours=hours),
    )


async def test_req_wf_025_ac3_runs_waiting_longer_than_a_set_time(world: World) -> None:
    a, b = world.a, world.b
    flow = await _workflow(world, WAIT_FOR_P1)
    runs = [await _start(world, flow, (await world.create(a, a.admin))["id"]) for _ in range(3)]
    await _age(world, runs[0], 48)
    query = {"waiting_over_hours": "24", "workflow_id": str(flow)}
    listed = await world.call("GET", f"{BASE}/instances", a, a.admin, params=query)
    assert listed.status_code == 200, listed.text
    assert [r["id"] for r in listed.json()["items"]] == [str(runs[0])]
    within = await world.call(
        "GET", f"{BASE}/instances", a, a.admin, params={**query, "waiting_over_hours": "72"}
    )
    assert within.json()["items"] == []
    theirs = await world.call(
        "GET", f"{BASE}/instances", b, b.admin, params={"waiting_over_hours": "24"}
    )
    assert theirs.status_code in {200, 403}
    if theirs.status_code == 200:
        assert str(runs[0]) not in {r["id"] for r in theirs.json()["items"]}


async def test_the_latest_step_is_read_on_the_tenant_first_key(world: World) -> None:
    a = world.a
    flow = await _workflow(world, WAIT_FOR_P1)
    await _start(world, flow, (await world.create(a, a.admin))["id"])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        # Seq scans off: the plan shows the index the lookup can use, not the tiny table's scan.
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in await session.execute(
                text(
                    "EXPLAIN SELECT i.id FROM workflow_instances i WHERE i.status IN"
                    " ('running', 'waiting') AND (SELECT s.at FROM workflow_steps s"
                    " WHERE s.tenant_id = i.tenant_id AND s.instance_id = i.id"
                    " ORDER BY s.seq DESC LIMIT 1) < now() - interval '24 hours'"
                )
            )
        )
    assert "pk_workflow_steps" in plan, plan
    assert "Backward" in plan, plan
