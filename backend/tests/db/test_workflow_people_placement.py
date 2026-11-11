"""A workflow field step that sets a technician follows D-154 "rules", as triggers (WP-048b S2).

- At run time it moves the record to the person's group with them; someone Away, inactive or
  out of that group leaves the record with the group only, the history says why, and the
  workflow's owner is told (one notice per save).
- At save, a technician in several groups needs the step's group too (the trigger editor's rule).

Cast (tests/db/test_incidents_api.py): tech_a in GA, tech_b in GB, tech_c in both.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import update

from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow
from app.modules.automation.service.workflow_admin import problems_of
from app.modules.work_items.events import WorkItemAssigneeUnavailable
from app.shared.events import EventEnvelope
from tests.db import test_incidents_api
from tests.db.test_incidents_api import World
from tests.db.test_workflow_events import _node, _start, _status, _workflow

pytestmark = [pytest.mark.db, pytest.mark.valkey]

world = test_incidents_api.world  # the incident world fixture, reused


def _set(**values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {
        "format": 1,
        "nodes": [
            _node("s", "start"),
            _node("set", "field_update", values=values),
            _node("e", "end"),
            _node("x", "end"),
        ],
        "links": [
            {"from": "s", "port": "next", "to": "set"},
            {"from": "set", "port": "next", "to": "e"},
            {"from": "set", "port": "error", "to": "x"},
        ],
        "variables": [],
    }


async def _owned_by(world: World, flow: uuid.UUID, owner: uuid.UUID) -> None:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await session.execute(update(Workflow).where(Workflow.id == flow).values(owner_id=owner))


def _why(history: list[dict[str, Any]]) -> list[Any]:
    return [
        (h["automation"] or {}).get("unavailable")
        for h in history
        if any(c["field"] in {"group_id", "technician_id"} for c in h["changes"])
        and (h["automation"] or {}).get("kind") == "workflow"
    ]


async def _unavailable(world: World, item: dict[str, Any]) -> list[EventEnvelope]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 AND event_type = $2",
        item["id"],
        WorkItemAssigneeUnavailable.event_type,
    )
    return [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]


async def test_a_workflow_that_sets_a_technician_moves_the_record_to_their_group(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    flow = await _workflow(world, _set(technician_id=str(a.tech_b)))
    instance = await _start(world, flow, item["id"])
    assert await _status(world, instance) == "finished"
    moved = await world.fresh(a, item)
    assert (moved["group_id"], moved["technician_id"]) == (str(a.gb), str(a.tech_b))
    assert _why(await world.history(a, item)) == [None]
    assert await _unavailable(world, item) == []


async def test_someone_away_leaves_the_record_with_the_group_and_tells_the_workflow_s_owner(
    world: World,
) -> None:
    a = world.a
    away = await world.call(
        "PUT", f"/automation/availability/{a.tech_b}", a, a.admin, json={"state": "away"}
    )
    assert away.status_code == 200, away.text
    item = await world.create(a, a.admin)
    flow = await _workflow(world, _set(technician_id=str(a.tech_b), group_id=str(a.gb)))
    await _owned_by(world, flow, a.tech_a)
    instance = await _start(world, flow, item["id"])
    assert await _status(world, instance) == "finished"  # the step went on, never stuck
    moved = await world.fresh(a, item)
    assert (moved["group_id"], moved["technician_id"]) == (str(a.gb), None)
    assert _why(await world.history(a, item)) == ["away"]
    (envelope,) = await _unavailable(world, item)  # one notice, never skipped silently
    assert envelope.payload["reason"] == "away"
    assert envelope.payload["step"] == "workflow"
    assert envelope.payload["owner_id"] == str(a.tech_a)


async def test_the_editor_needs_the_group_for_a_technician_in_several(world: World) -> None:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        several = await problems_of(session, "incident", _set(technician_id=str(a.tech_c)))
        wrong = await problems_of(
            session, "incident", _set(technician_id=str(a.tech_a), group_id=str(a.gb))
        )
        chosen = await problems_of(
            session, "incident", _set(technician_id=str(a.tech_c), group_id=str(a.gb))
        )
    assert ("node:set", "reassign_group_required", {"field": "technician_id"}) in several
    assert ("node:set", "person_not_in_group", {"field": "technician_id"}) in wrong
    assert not [p for p in chosen if p[0] == "node:set"]
