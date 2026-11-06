"""Workflow commands on work items through the public services (WP-048b, ADR-043 §6; lane A).

Real PostgreSQL, the real incident services and the real policy layer:
- a workflow's move, field update and note each write history naming the workflow
  (`automation_ref` {kind: workflow, workflow_id, instance_id}) with source "workflow";
- its status event is `automatic`, as a rule's;
- the ref is scoped to the command: a change made after it, outside it, does not inherit it;
- a refusal comes back as the command's result, never raised.
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service import workflow_commands
from tests.db.test_incidents_api import CONSOLE, World, world

__all__ = ["world"]  # the fixture, re-used

REF = {"kind": "workflow", "workflow_id": str(uuid.uuid4()), "instance_id": str(uuid.uuid4())}


async def _run(world: World, record_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> Any:  # noqa: ANN401 - the result
    a = world.a
    run = workflow_commands.runner(INCIDENT)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        subject = await subject_for(session, a.tenant, a.admin)
        return await run(session, subject, record_id, kind, payload, REF)


async def _history(world: World, record_id: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT kind, field, source, automation_ref FROM field_changes "
        "WHERE record_id = $1 ORDER BY occurred_at, field",
        uuid.UUID(record_id),
    )
    return [dict(r) for r in rows]


def _refs(rows: list[dict[str, Any]], kind: str) -> set[tuple[str, str | None]]:
    """(source, automation kind) of the history rows of one kind; jsonb arrives as text."""
    return {
        (r["source"], json.loads(r["automation_ref"]).get("kind") if r["automation_ref"] else None)
        for r in rows
        if r["kind"] == kind
    }


async def test_a_workflow_s_update_move_and_note_name_the_workflow_in_history(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    record = uuid.UUID(item["id"])

    updated = await _run(world, record, "update_fields", {"values": {"subject": "Mail is slow"}})
    assert updated.ok, updated.error
    moved = await _run(world, record, "move", {"action": "start_work"})
    assert moved.ok, moved.error
    noted = await _run(world, record, "add_note", {"text": {"en": "Escalated"}, "private": True})
    assert noted.ok, noted.error

    rows = await _history(world, item["id"])
    assert _refs(rows, "updated") == {("workflow", "workflow")}
    assert _refs(rows, "status") == {("workflow", "workflow")}
    full = [json.loads(r["automation_ref"]) for r in rows if r["automation_ref"]]
    assert full
    assert all(ref == REF for ref in full)
    events = await world.sql(
        "SELECT envelope->'payload'->>'automatic' AS automatic FROM outbox_events "
        "WHERE event_type = 'work_items.work_item.status_changed' AND aggregate_id = $1",
        item["id"],
    )
    assert [e["automatic"] for e in events] == ["true"]  # like a rule's move


async def test_the_ref_ends_with_the_command(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    await _run(world, uuid.UUID(item["id"]), "update_fields", {"values": {"subject": "By flow"}})
    after = await world.call(
        "PATCH",
        f"/incidents/{item['id']}",
        a,
        a.admin,
        json={"subject": "By a person"},
        headers={"If-Match": '"2"', **CONSOLE},
    )
    assert after.status_code == 200, after.text
    rows = [r for r in await _history(world, item["id"]) if r["field"] == "subject"]
    assert [r["source"] for r in rows][-1] != "workflow"
    assert rows[-1]["automation_ref"] is None  # the person's change inherits nothing


async def test_a_refused_command_is_a_result_not_an_exception(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    refused = await _run(world, uuid.UUID(item["id"]), "move", {"action": "close"})
    assert not refused.ok
    assert refused.error  # a stable code, e.g. the action not offered from New
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        record = await items.automation_record(session, INCIDENT, uuid.UUID(item["id"]))
        assert record.status == item["status"]  # nothing moved
