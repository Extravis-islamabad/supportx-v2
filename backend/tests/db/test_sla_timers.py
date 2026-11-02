"""SLA warnings, breaches and escalation levels, WP-025 session 3 (wp-025-plan.md §3.5).

`sla.fire` is what the Temporal waker and the safety net call; here the test calls it at chosen
moments, so time never has to pass. P1 targets of the default policy run around the clock
(4 hours to resolve, warning at 75 %), so every moment follows from the stored rows.
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules import sla
from app.modules.sla.service.timers import overdue_records
from app.modules.work_items.service.notifications import (
    ESCALATION_RECIPIENTS,
    IncidentNotifications,
)
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import LabelRef
from tests.db import test_incidents_api
from tests.db.test_incidents_api import Org, World
from tests.db.test_sla_clock import POLICIES, _events, _p1, _targets

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused


async def _fire_all(world: World, org: Org, item: dict[str, Any], at: datetime) -> list[str]:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        result = await sla.fire(session, uuid.UUID(item["id"]), now=at)
    return [f"{f.what}:{f.kind}:{f.position or ''}" for f in result.fired]


async def _runs(world: World, item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = await world.sql(
        "SELECT r.* FROM sla_escalation_runs r JOIN sla_targets t ON t.id = r.target_id"
        " WHERE t.record_id = $1 ORDER BY r.level_key",
        uuid.UUID(item["id"]),
    )
    return {r["level_key"]: dict(r) for r in rows}


async def _levels(world: World, org: Org, levels: list[dict[str, Any]]) -> None:
    (default,) = (await world.call("GET", POLICIES, org, org.admin)).json()
    saved = await world.call(
        "PATCH",
        f"/sla/policies/{default['id']}",
        org,
        org.admin,
        json={"levels": levels},
        headers={"If-Match": f'"{default["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["levels"]) == len(levels)


async def test_req_sla_019_the_warning_point_turns_the_record_to_warning_once(
    world: World,
) -> None:
    a = world.a
    item = await _p1(world, a)
    resolution = (await _targets(world, item))["resolution:1"]
    warning = resolution["warning_at"]

    def mine(fired: list[str]) -> list[str]:
        return [f for f in fired if ":resolution:" in f]

    assert mine(await _fire_all(world, a, item, warning - timedelta(seconds=1))) == []
    fired = await _fire_all(world, a, item, warning + timedelta(seconds=1))
    assert mine(fired) == ["warning:resolution:"]
    # A second wake for the same moment (worker restart, the safety net) does nothing.
    assert await _fire_all(world, a, item, warning + timedelta(seconds=2)) == []
    fresh = await world.fresh(a, item)
    assert fresh["resolution_sla_state"] == "warning"
    assert fresh["first_response_sla_state"] == "breached"  # 15 minutes passed long before
    assert fresh["version"] == item["version"] + 2  # the response's firing, then this one
    row = (await _targets(world, item))["resolution:1"]
    assert row["warned_at"] == warning
    assert row["state"] == "running"
    events = await _events(world, item)
    # One warning per target: the response's (with its breach, in one wake), then this one.
    assert events.count("sla.target.warning") == 2
    history = (await world.history(a, item))[0]  # the newest entry
    assert history["source"] == "sla"
    assert {c["field"] for c in history["changes"]} == {"resolution_sla_state"}


async def test_req_sla_020_a_breach_is_stamped_at_the_due_moment_and_stays(world: World) -> None:
    a = world.a
    item = await _p1(world, a)
    due = (await _targets(world, item))["resolution:1"]["due_at"]
    # The waker comes late (90 s): the stamp is still the due moment itself.
    fired = await _fire_all(world, a, item, due + timedelta(seconds=90))
    assert "breached:resolution:" in fired
    row = (await _targets(world, item))["resolution:1"]
    assert (row["state"], row["breached_at"], row["breach_reason"]) == (
        "breached",
        due,
        "time_passed",
    )
    fresh = await world.fresh(a, item)
    assert (fresh["resolution_sla_state"], fresh["resolution_breached"]) == ("breached", True)
    assert fresh["first_response_breached"] is True  # 15 minutes passed long before
    # REQ-SLA-020 AC2: resolving later keeps the flag and records how long after due.
    resolved = await world.act(a, a.tech_a, fresh, "resolve")
    assert resolved.status_code == 200, resolved.text
    row = (await _targets(world, item))["resolution:1"]
    assert (row["state"], row["met_how"]) == ("met", "late")
    assert row["breached_at"] == due
    assert row["breach_seconds"] is not None
    assert row["breach_seconds"] >= 0
    assert resolved.json()["resolution_breached"] is True
    assert resolved.json()["resolution_sla_state"] == "met"


async def test_req_sla_022_levels_run_once_each_at_their_moment_and_stop_when_resolved(
    world: World,
) -> None:
    a = world.a
    await _levels(
        world,
        a,
        [
            {
                "kind": "resolution",
                "offset_seconds": -3600,
                "recipients": [{"kind": "assignee"}],
            },
            {
                "kind": "resolution",
                "offset_seconds": 0,
                "recipients": [{"kind": "group_head"}],
                "actions": [{"kind": "reassign_group", "target_id": str(a.gb)}],
            },
            {"kind": "resolution", "offset_seconds": 7200, "recipients": [{"kind": "assignee"}]},
        ],
    )
    item = await _p1(world, a)
    due = (await _targets(world, item))["resolution:1"]["due_at"]
    runs = await _runs(world, item)
    assert {k: (r["state"], r["due_at"]) for k, r in runs.items()} == {
        "resolution:1": ("waiting", due - timedelta(hours=1)),
        "resolution:2": ("waiting", due),
        "resolution:3": ("waiting", due + timedelta(hours=2)),
    }
    first = await _fire_all(world, a, item, due - timedelta(minutes=59))
    assert "escalated:resolution:1" in first
    again = await _fire_all(world, a, item, due - timedelta(minutes=58))
    assert not [f for f in again if f.startswith("escalated")]  # never twice (AC3)
    at_due = await _fire_all(world, a, item, due + timedelta(seconds=5))
    assert "breached:resolution:" in at_due
    assert "escalated:resolution:2" in at_due
    moved = await world.fresh(a, item)
    assert moved["group_id"] == str(a.gb)  # the level's action (REQ-SLA-024 AC1)
    runs = await _runs(world, item)
    assert json.loads(runs["resolution:2"]["outcome"]) == {
        "actions": [{"kind": "reassign_group", "ok": True, "code": None}]
    }
    sources = {h["source"] for h in await world.history(a, item)}
    assert "sla" in sources
    escalated = [
        c
        for h in await world.history(a, item)
        for c in h["changes"]
        if c["field"] == "sla_escalation"
    ]
    assert sorted(c["new"] for c in escalated) == ["resolution:1", "resolution:2"]
    # REQ-SLA-025 AC1: resolved before the last level: it never runs.
    resolved = await world.act(a, a.tech_b, moved, "resolve")
    assert resolved.status_code == 200, resolved.text
    runs = await _runs(world, item)
    assert runs["resolution:3"]["state"] == "cancelled"
    assert await _fire_all(world, a, item, due + timedelta(hours=3)) == []
    assert (await _events(world, item)).count("sla.target.escalated") == 2


async def test_req_sla_025_a_pause_holds_waiting_levels_and_a_resume_moves_them(
    world: World,
) -> None:
    a = world.a
    await _levels(
        world,
        a,
        [{"kind": "resolution", "offset_seconds": 0, "recipients": [{"kind": "assignee"}]}],
    )
    item = await _p1(world, a)
    waiting = await world.act(a, a.tech_a, item, "wait_requester", "more_information", "Logs")
    assert waiting.status_code == 200, waiting.text
    run = (await _runs(world, item))["resolution:1"]
    assert (run["state"], run["due_at"]) == ("waiting", None)  # held
    resumed = await world.act(a, a.tech_a, waiting.json(), "resume")
    assert resumed.status_code == 200, resumed.text
    target = (await _targets(world, item))["resolution:1"]
    run = (await _runs(world, item))["resolution:1"]
    assert run["due_at"] == target["due_at"]  # "at breach" follows the moved due moment


async def test_levels_are_checked_when_saved(world: World) -> None:
    a = world.a
    (default,) = (await world.call("GET", POLICIES, a, a.admin)).json()

    async def save(levels: list[dict[str, Any]]) -> list[str]:
        response = await world.call(
            "PATCH",
            f"/sla/policies/{default['id']}",
            a,
            a.admin,
            json={"levels": levels},
            headers={"If-Match": f'"{default["version"]}"'},
        )
        assert response.status_code == 422, response.text
        return sorted({e["code"] for e in response.json()["errors"]})

    assert await save([{"kind": "resolution", "recipients": []}]) == ["required"]
    assert await save([{"kind": "resolution", "notify": False}]) == ["level_does_nothing"]
    assert await save(
        [{"kind": "resolution", "recipients": [{"kind": "user", "id": str(uuid.uuid4())}]}]
    ) == ["unknown_reference"]
    other_group = str(world.b.ga)  # another tenant's group is unknown here
    assert await save(
        [
            {
                "kind": "resolution",
                "notify": False,
                "actions": [{"kind": "reassign_group", "target_id": other_group}],
            }
        ]
    ) == ["unknown_reference"]
    same = {"kind": "resolution", "recipients": [{"kind": "assignee"}]}
    assert await save([same, same]) == ["levels_same_moment"]
    nine = [{**same, "offset_seconds": i * 60} for i in range(9)]
    assert await save(nine) == ["too_many_levels"]


async def test_the_safety_net_finds_what_is_late_and_next_wake_the_earliest(
    world: World,
) -> None:
    a = world.a
    item = await _p1(world, a)
    rows = await _targets(world, item)
    response_due = rows["first_response:1"]["due_at"]
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (
            await sla.next_wake(session, uuid.UUID(item["id"]))
            == (rows["first_response:1"]["warning_at"])
        )
        assert uuid.UUID(item["id"]) not in await overdue_records(
            session, response_due - timedelta(minutes=12)
        )
        assert uuid.UUID(item["id"]) in await overdue_records(
            session, response_due + timedelta(seconds=1)
        )
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        assert uuid.UUID(item["id"]) not in await overdue_records(
            session, response_due + timedelta(days=1)
        )


async def test_escalation_tables_are_isolated_by_tenant(world: World) -> None:
    a, b = world.a, world.b
    await _levels(
        world,
        a,
        [{"kind": "resolution", "offset_seconds": 0, "recipients": [{"kind": "assignee"}]}],
    )
    await _p1(world, a)
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("sla_escalation_levels", "sla_escalation_runs"):
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed names
                {"a": a.tenant},
            )
            assert count == 0, table
        for statement in (
            "UPDATE sla_escalation_runs SET state = 'cancelled'",
            "DELETE FROM sla_escalation_levels",
        ):
            assert (await session.execute(text(statement))).rowcount == 0, statement


async def test_req_sla_023_an_unset_assignee_falls_back_and_the_level_notifies_them(
    world: World,
) -> None:
    a = world.a
    await _levels(
        world,
        a,
        [
            {
                "kind": "resolution",
                "offset_seconds": 0,
                "recipients": [{"kind": "assignee"}],
                "fallback": [{"kind": "user", "id": str(a.lead)}],
            }
        ],
    )
    item = await world.create(a, a.admin, priority="p1", priority_reason="Whole floor down")
    assert item["technician_id"] is None
    due = (await _targets(world, item))["resolution:1"]["due_at"]
    await _fire_all(world, a, item, due + timedelta(seconds=1))
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1"
        " AND event_type = 'sla.target.escalated'",
        item["id"],
    )
    (envelope,) = [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]
    source = IncidentNotifications()
    assert source.events_for(envelope) == ("incident.sla_escalated",)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        context = await source.context(session, "incident.sla_escalated", envelope)
    assert context is not None
    assert context.relatives[ESCALATION_RECIPIENTS] == frozenset({a.lead})
    assert context.urgent  # never held for a digest
    assert context.variables["sla.target"] == LabelRef("sla_target_kind.resolution")
