"""Skip a failed step (WP-048b S5; REQ-WF-024 AC2).

- A failed run moves on from its failed step on that step's "next" output and runs to its end;
  the log says skipped, and the audit names who, the step and the record.
- Only for those who may edit the record; a step that decides its own path is never skipped
  (the domain tests cover the refusal).
"""

import json
import uuid

from tests.db.test_incidents_api import World, role, world
from tests.db.test_workflow_events import _start, _workflow
from tests.db.test_workflow_jobs import _bad_set
from tests.db.test_workflow_operations import _instance, _post, _steps

__all__ = ["world"]  # the fixture, re-used


async def _failed_run(world: World) -> tuple[dict[str, object], uuid.UUID]:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, _bad_set()), item["id"])
    assert (await _instance(world, instance))["status"] == "failed"
    return item, instance


async def test_req_wf_024_ac2_skip_moves_on_and_is_audited(world: World) -> None:
    a = world.a
    item, instance = await _failed_run(world)
    skipped = await _post(world, a, a.admin, instance, "skip")
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["status"] == "finished"  # set was skipped; the end was reached
    assert "set:skipped" in await _steps(world, instance)
    rows = await world.sql(
        "SELECT actor_id, details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "automation.workflow_skipped",
    )
    [entry] = rows
    details = (
        entry["details"] if isinstance(entry["details"], dict) else json.loads(entry["details"])
    )
    assert (str(entry["actor_id"]), details["node"], details["record_id"]) == (
        str(a.admin),
        "set",
        item["id"],
    )


async def test_skip_needs_the_right_to_edit_the_record(world: World) -> None:
    a = world.a
    _item, instance = await _failed_run(world)
    runner = await role(world, a, "Workflow runner", [("workflows.run", "all")])
    assigned = await world.call("PUT", f"/users/{a.requester}/roles/{runner}", a, a.admin)
    assert assigned.status_code in {200, 204}, assigned.text
    refused = await _post(world, a, a.requester, instance, "skip")
    assert refused.status_code == 403
    assert refused.json()["code"] == "record_not_editable"
    assert (await _instance(world, instance))["status"] == "failed"
