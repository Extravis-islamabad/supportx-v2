"""The task node on a real incident (WP-048b S2; REQ-WF-015; migration 0106).

- The node opens its checklist at the end of the record's tasks, each naming the instance and
  the node's command; the instance waits.
- Ticking the last task done continues the node (through the outbox, as an approval does); a
  canceled task takes its error output.
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.automation.service import workflow_events
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import CONSOLE, World, world
from tests.db.test_workflow_events import _flow, _node, _start, _status, _workflow

__all__ = ["world"]  # the fixture, re-used


CHECKLIST = _flow(
    _node("s", "start"),
    _node("do", "tasks", titles=[{"en": "Back up the mailbox"}, {"en": "Apply the patch"}]),
    _node("e", "end"),
    _node("bad", "end"),
    links=[("s", "next", "do"), ("do", "next", "e"), ("do", "error", "bad")],
)


async def _tasks(world: World, record: str) -> list[dict[str, Any]]:
    a = world.a
    listed = await world.call("GET", f"/incidents/{record}/tasks", a, a.admin)
    assert listed.status_code == 200, listed.text
    return list(listed.json()["items"])


async def _set(world: World, record: str, task: dict[str, Any], status: str) -> None:
    a = world.a
    done = await world.call(
        "PATCH",
        f"/incidents/{record}/tasks/{task['id']}",
        a,
        a.admin,
        json={"status": status},
        headers={"If-Match": f'"{task["version"]}"', **CONSOLE},
    )
    assert done.status_code == 200, done.text


async def _results(world: World, instance_id: uuid.UUID) -> list[dict[str, Any]]:
    """Each result the outbox holds for the instance, handed to automation's consumer."""
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = $1 AND aggregate_id = $2"
        " ORDER BY id",
        "automation.workflow.command_finished",
        str(instance_id),  # the outbox keeps aggregate ids as text
    )
    found = []
    for row in rows:
        envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await workflow_events.on_command_finished(envelope, session)
        found.append(dict(envelope.payload))
    return found


async def test_req_wf_015_the_checklist_opens_and_its_last_task_done_continues_the_node(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, CHECKLIST), item["id"])
    tasks = await _tasks(world, item["id"])
    assert [t["title"] for t in tasks] == ["Back up the mailbox", "Apply the patch"]
    rows = await world.sql(
        "SELECT workflow_instance_id, workflow_command FROM work_item_tasks"
        " WHERE work_item_id = $1",
        uuid.UUID(item["id"]),
    )
    assert {r["workflow_instance_id"] for r in rows} == {instance}
    assert len({r["workflow_command"] for r in rows}) == 1
    assert await _status(world, instance) == "waiting"

    await _set(world, item["id"], tasks[0], "done")
    assert await _results(world, instance) == []  # one of two: still waiting
    assert await _status(world, instance) == "waiting"

    await _set(world, item["id"], (await _tasks(world, item["id"]))[1], "done")
    [result] = await _results(world, instance)
    assert result["ok"] is True
    assert await _status(world, instance) == "finished"


async def test_req_wf_015_a_canceled_task_takes_the_error_output(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, CHECKLIST), item["id"])
    first = (await _tasks(world, item["id"]))[0]
    await _set(world, item["id"], first, "canceled")
    [result] = await _results(world, instance)
    assert (result["ok"], result["error"]) == (False, "task_canceled")
    assert await _status(world, instance) == "finished"  # by its error output, to "bad"
    steps = await world.sql(
        "SELECT node, result FROM workflow_steps WHERE instance_id = $1", instance
    )
    assert ("do", "error") in {(s["node"], s["result"]) for s in steps}
