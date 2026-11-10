"""D-154 "rules": escalations and automation move the record with the person they assign.

Haider, through the coordinator, 2026-11-10. A step that names a person also names the group to
move the record to with them (filled in when they are in one group, chosen when in several).
At run time someone inactive, Away or out of that group leaves the record with the group only,
and its history says why. One test per case (the plan's list).

Cast (tests/db/test_incidents_api.py): tech_a in GA, tech_b in GB, tech_c in both.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest

from tests.db import test_incidents_api
from tests.db.test_incidents_api import Org, World
from tests.db.test_sla_clock import POLICIES, _p1, _targets
from tests.db.test_sla_timers import _fire_all

pytestmark = [pytest.mark.db, pytest.mark.valkey]
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
