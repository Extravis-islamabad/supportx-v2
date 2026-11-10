"""D-154 "rules": escalations and automation move the record with the person they assign.

Haider, through the coordinator, 2026-11-10. A step that names a person also names the group to
move the record to with them (filled in when they are in one group, chosen when in several).
At run time someone inactive, Away or out of that group leaves the record with the group only,
and its history says why. One test per case (the plan's list).

Cast (tests/db/test_incidents_api.py): tech_a in GA, tech_b in GB, tech_c in both.
"""

import importlib.util
import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.work_items.events import WorkItemAssigneeUnavailable
from app.modules.work_items.service.notifications import (
    STEP_OWNER,
    UNAVAILABLE,
    IncidentNotifications,
)
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import LabelRef
from tests.db import test_incidents_api
from tests.db.test_automation_triggers_api import drain
from tests.db.test_incidents_api import Org, World
from tests.db.test_sla_clock import POLICIES, _p1, _targets
from tests.db.test_sla_timers import _fire_all

pytestmark = [pytest.mark.db, pytest.mark.valkey]


def _migration_fill() -> str:
    """Migration 0126's data step, run as is (its file is not a package module)."""
    path = Path(__file__).parents[2] / "migrations" / "versions" / "0126_d154_escalation_groups.py"
    spec = importlib.util.spec_from_file_location("migration_0126", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.FILL)


world = test_incidents_api.world  # the incident world fixture, reused


async def _save_levels(world: World, org: Org, actions: list[dict[str, Any]]) -> Any:  # noqa: ANN401 - the response
    (default,) = (await world.call("GET", POLICIES, org, org.admin)).json()
    return await world.call(
        "PATCH",
        f"/sla/policies/{default['id']}",
        org,
        org.admin,
        json={"levels": [{"kind": "resolution", "notify": False, "actions": actions}]},
        headers={"If-Match": f'"{default["version"]}"'},
    )


def _codes(response: Any) -> list[str]:  # noqa: ANN401 - an httpx response
    assert response.status_code == 422, response.text
    return sorted({e["code"] for e in response.json()["errors"]})


async def test_the_editor_needs_the_group_for_someone_in_several_and_fills_it_for_one(
    world: World,
) -> None:
    a = world.a
    person = {"kind": "reassign_person"}
    several = await _save_levels(world, a, [{**person, "target_id": str(a.tech_c)}])
    assert _codes(several) == ["reassign_group_required"]
    wrong = await _save_levels(
        world, a, [{**person, "target_id": str(a.tech_a), "group_id": str(a.gb)}]
    )
    assert _codes(wrong) == ["person_not_in_group"]
    one = await _save_levels(world, a, [{**person, "target_id": str(a.tech_b)}])
    assert one.status_code == 200, one.text
    (action,) = one.json()["levels"][0]["actions"]
    assert action["group_id"] == str(a.gb)  # their only group, filled in
    chosen = await _save_levels(
        world, a, [{**person, "target_id": str(a.tech_c), "group_id": str(a.gb)}]
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["levels"][0]["actions"][0]["group_id"] == str(a.gb)


async def _escalate_to(world: World, org: Org, person: uuid.UUID, group: uuid.UUID) -> Any:  # noqa: ANN401 - JSON
    saved = await _save_levels(
        world,
        org,
        [{"kind": "reassign_person", "target_id": str(person), "group_id": str(group)}],
    )
    assert saved.status_code == 200, saved.text
    item = await _p1(world, org)  # in GA with tech_a
    due = (await _targets(world, item))["resolution:1"]["due_at"]
    await _fire_all(world, org, item, due + timedelta(seconds=5))
    return item


def _why(history: list[dict[str, Any]]) -> list[Any]:
    return [
        (h["automation"] or {}).get("unavailable")
        for h in history
        if any(c["field"] == "technician_id" for c in h["changes"])
        and (h["automation"] or {}).get("kind") == "sla_escalation"
    ]


async def test_an_escalation_moves_the_record_to_the_persons_group_with_them(
    world: World,
) -> None:
    a = world.a
    item = await _escalate_to(world, a, a.tech_b, a.gb)
    moved = await world.fresh(a, item)
    assert (moved["group_id"], moved["technician_id"]) == (str(a.gb), str(a.tech_b))
    assert _why(await world.history(a, item)) == [None]


async def test_someone_away_leaves_the_record_with_the_group_only_and_history_says_why(
    world: World,
) -> None:
    a = world.a
    away = await world.call(
        "PUT", f"/automation/availability/{a.tech_b}", a, a.admin, json={"state": "away"}
    )
    assert away.status_code == 200, away.text
    item = await _escalate_to(world, a, a.tech_b, a.gb)
    moved = await world.fresh(a, item)
    assert (moved["group_id"], moved["technician_id"]) == (str(a.gb), None)
    assert _why(await world.history(a, item)) == ["away"]
    # Never skipped silently: one notice, to the SLA's managers (an SLA level has no owner).
    (envelope,) = await _unavailable_events(world, item)
    assert envelope.payload["reason"] == "away"
    assert envelope.payload["owner_id"] is None
    source = IncidentNotifications()
    assert source.events_for(envelope) == (UNAVAILABLE,)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        context = await source.context(session, UNAVAILABLE, envelope)
    assert context is not None
    assert a.admin in context.relatives[STEP_OWNER]
    assert a.tech_b not in context.relatives[STEP_OWNER]
    assert context.variables["unavailable.reason"] == LabelRef("assignee_unavailable.away")


async def _unavailable_events(world: World, item: dict[str, Any]) -> list[EventEnvelope]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 AND event_type = $2",
        item["id"],
        WorkItemAssigneeUnavailable.event_type,
    )
    return [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]


async def test_someone_who_left_the_group_leaves_the_record_with_the_group_only(
    world: World,
) -> None:
    a = world.a
    saved = await _save_levels(
        world,
        a,
        [{"kind": "reassign_person", "target_id": str(a.tech_c), "group_id": str(a.gb)}],
    )
    assert saved.status_code == 200, saved.text
    # tech_c leaves GB after the level was saved (explicit tenant: the admin URL skips RLS).
    await world.sql(
        "DELETE FROM group_members WHERE tenant_id = $1 AND group_id = $2 AND user_id = $3",
        a.tenant,
        a.gb,
        a.tech_c,
    )
    item = await _p1(world, a)
    due = (await _targets(world, item))["resolution:1"]["due_at"]
    await _fire_all(world, a, item, due + timedelta(seconds=5))
    moved = await world.fresh(a, item)
    assert (moved["group_id"], moved["technician_id"]) == (str(a.gb), None)
    assert _why(await world.history(a, item)) == ["not_in_group"]


async def test_an_inactive_person_leaves_the_record_with_the_group_only(world: World) -> None:
    a = world.a
    saved = await _save_levels(
        world,
        a,
        [{"kind": "reassign_person", "target_id": str(a.tech_b), "group_id": str(a.gb)}],
    )
    assert saved.status_code == 200, saved.text
    await world.sql(
        "UPDATE users SET status = 'disabled' WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_b
    )
    item = await _p1(world, a)
    due = (await _targets(world, item))["resolution:1"]["due_at"]
    await _fire_all(world, a, item, due + timedelta(seconds=5))
    moved = await world.fresh(a, item)
    assert (moved["group_id"], moved["technician_id"]) == (str(a.gb), None)
    assert _why(await world.history(a, item)) == ["inactive"]


async def _rule_sets(world: World, org: Org, person: uuid.UUID) -> None:
    created = await world.call(
        "POST",
        "/automation/rules",
        org,
        org.admin,
        json={
            "record_type": "incident",
            "name": "Send to Bilal",
            "events": ["create"],
            "state": "enabled",
            "actions": [
                {"kind": "set", "field": "technician_id", "value": str(person), "mode": "overwrite"}
            ],
        },
    )
    assert created.status_code == 201, created.text


async def test_a_business_rule_moves_the_record_with_the_technician_it_sets(world: World) -> None:
    a = world.a
    await _rule_sets(world, a, a.tech_b)
    item = await world.create(a, a.admin, group_id=str(a.ga))
    assert (item["group_id"], item["technician_id"]) == (str(a.gb), str(a.tech_b))


async def test_a_business_rule_naming_someone_away_assigns_the_group_only(world: World) -> None:
    a = world.a
    away = await world.call(
        "PUT", f"/automation/availability/{a.tech_b}", a, a.admin, json={"state": "away"}
    )
    assert away.status_code == 200, away.text
    await _rule_sets(world, a, a.tech_b)
    item = await world.create(a, a.admin, group_id=str(a.ga))
    assert (item["group_id"], item["technician_id"]) == (str(a.gb), None)
    reasons = [(h["automation"] or {}).get("unavailable") for h in await world.history(a, item)]
    assert "away" in reasons
    # The rule's owner hears it (the admin made the rule).
    (envelope,) = await _unavailable_events(world, item)
    assert envelope.payload["step"] == "business_rule"
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        context = await IncidentNotifications().context(session, UNAVAILABLE, envelope)
    assert context is not None
    assert context.relatives[STEP_OWNER] == frozenset({a.admin})


async def test_a_rule_or_trigger_naming_someone_in_several_groups_needs_the_group(
    world: World,
) -> None:
    a = world.a
    for path in ("/automation/rules", "/automation/triggers"):
        body: dict[str, Any] = {
            "record_type": "incident",
            "name": "Send to Sara",
            "events": ["create"] if path.endswith("rules") else ["created"],
            "state": "enabled",
        }
        person = {"kind": "set", "field": "technician_id", "value": str(a.tech_c)}
        refused = await world.call(
            "POST", path, a, a.admin, json={**body, "actions": [{**person, "mode": "overwrite"}]}
        )
        assert refused.status_code == 422, refused.text
        assert {e["code"] for e in refused.json()["errors"]} == {"reassign_group_required"}
        group = {"kind": "set", "field": "group_id", "value": str(a.gb), "mode": "overwrite"}
        saved = await world.call(
            "POST",
            path,
            a,
            a.admin,
            json={**body, "actions": [group, {**person, "mode": "overwrite"}]},
        )
        assert saved.status_code == 201, saved.text
        other = {**group, "value": str(a.gb)}
        wrong = await world.call(
            "POST",
            path,
            a,
            a.admin,
            json={
                **body,
                "actions": [other, {**person, "value": str(a.tech_a), "mode": "overwrite"}],
            },
        )
        assert wrong.status_code == 422, wrong.text
        assert {e["code"] for e in wrong.json()["errors"]} == {"person_not_in_group"}


async def test_a_trigger_moves_the_record_with_the_technician_it_sets(world: World) -> None:
    a = world.a
    created = await world.call(
        "POST",
        "/automation/triggers",
        a,
        a.admin,
        json={
            "record_type": "incident",
            "name": "Send to Bilal",
            "events": ["created"],
            "state": "enabled",
            "actions": [
                {
                    "kind": "set",
                    "field": "technician_id",
                    "value": str(a.tech_b),
                    "mode": "overwrite",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    item = await world.create(a, a.admin, group_id=str(a.ga))
    await drain(world, a)
    moved = await world.fresh(a, item)
    assert (moved["group_id"], moved["technician_id"]) == (str(a.gb), str(a.tech_b))


async def test_migration_0126_fills_the_only_group_and_leaves_several_for_a_choice(
    world: World,
) -> None:
    a, b = world.a, world.b
    for org in (a, b):
        saved = await _save_levels(
            world,
            org,
            [
                {"kind": "reassign_person", "target_id": str(org.tech_b), "group_id": str(org.gb)},
                {"kind": "add_note", "text": "Escalated"},
            ],
        )
        assert saved.status_code == 200, saved.text
    several = await _save_levels(
        world,
        a,
        [{"kind": "reassign_person", "target_id": str(a.tech_c), "group_id": str(a.ga)}],
    )
    assert several.status_code == 200, several.text
    # As saved before D-154: no group on the person's action (both tenants, explicitly).
    await world.sql(
        "UPDATE sla_escalation_levels SET actions = ("
        "  SELECT jsonb_agg(x.a - 'group_id' ORDER BY x.n)"
        "    FROM jsonb_array_elements(actions) WITH ORDINALITY AS x(a, n))"
        " WHERE tenant_id = ANY($1::uuid[])",
        [a.tenant, b.tenant],
    )
    await world.sql(_migration_fill())
    rows = await world.sql(
        "SELECT tenant_id, actions FROM sla_escalation_levels WHERE tenant_id = ANY($1::uuid[])",
        [a.tenant, b.tenant],
    )
    by_tenant: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in rows:
        by_tenant.setdefault(row["tenant_id"], []).extend(json.loads(row["actions"]))
    # Org A's policy now holds tech_c's level only (the later save replaced it): left alone.
    assert [x.get("group_id") for x in by_tenant[a.tenant]] == [None]
    filled = [x for x in by_tenant[b.tenant] if x["kind"] == "reassign_person"]
    assert [x["group_id"] for x in filled] == [str(b.gb)]  # tech_b's only group
    notes = [x for x in by_tenant[b.tenant] if x["kind"] == "add_note"]
    assert [x["text"] for x in notes] == ["Escalated"]  # other actions untouched
    assert all("group_id" not in x for x in notes)
