"""Business rules, routing and auto-assignment over HTTP (WP-029; ADR-035; D-097).

Real PostgreSQL and Valkey, the incidents test world (two organisations, groups GA = {A, C} and
GB = {B, C}, sites, technicians). Each test names the requirement and criterion it proves.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from tests.db.test_incidents_api import BASE, Org, World, incidents_world, problem
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


async def add_rule(world: World, org: Org, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    payload = {
        "record_type": "incident",
        "name": "Rule",
        "events": ["create"],
        "state": "enabled",
        **body,
    }
    created = await world.call("POST", "/automation/rules", org, org.admin, json=payload)
    assert created.status_code == 201, created.text
    return dict(created.json())


def set_(field: str, value: Any, mode: str = "fill_empty") -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"kind": "set", "field": field, "value": value, "mode": mode}


async def category(world: World, org: Org, name: str, group: uuid.UUID | None = None) -> str:
    body: dict[str, Any] = {"labels": {"en": name}}
    if group is not None:
        body["default_group_id"] = str(group)
    created = await world.call("POST", f"{BASE}/categories", org, org.admin, json=body)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def automated(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [h for h in history if h.get("source") == "rule"]


# --- business rules ------------------------------------------------------------------------------


async def test_req_rul_001_ac1_a_rule_on_create_sets_priority_in_the_same_save(
    world: World,
) -> None:
    org = world.a
    email = await category(world, org, "Email")
    rule = await add_rule(
        world,
        org,
        name="Email is P2",
        conditions={"field": "category_id", "op": "eq", "value": email},
        actions=[set_("priority", "p2")],
    )
    item = await world.create(org, org.admin, category_id=email)
    assert (item["priority"], item["priority_source"]) == ("p2", "rule")
    history = automated(await world.history(org, item))
    assert len(history) == 1
    entry = history[0]
    assert entry["automation"]["kind"] == "business_rule"
    assert entry["automation"]["rule"] == "Email is P2"
    assert entry["automation"]["rule_id"] == rule["id"]


async def test_req_rul_001_ac4_and_029_drafts_and_disabled_rules_never_run(world: World) -> None:
    org = world.a
    for state in ("draft", "disabled"):
        await add_rule(world, org, name=f"{state} rule", state=state, actions=[set_("tags", ["x"])])
    item = await world.create(org, org.admin)
    assert item["tags"] == []


async def test_req_rul_003_fill_empty_keeps_what_a_person_entered_overwrite_replaces_it(
    world: World,
) -> None:
    org = world.a
    await add_rule(world, org, name="Fill", actions=[set_("impact", "team")])
    kept = await world.create(org, org.admin, impact="organisation")
    assert kept["impact"] == "organisation"
    filled = await world.create(org, org.admin)
    assert filled["impact"] == "team"


async def test_req_rul_003_ac2_overwrite_shows_both_values_and_the_rule(world: World) -> None:
    org = world.a
    await add_rule(world, org, name="Force", actions=[set_("impact", "team", "overwrite")])
    item = await world.create(org, org.admin, impact="organisation")
    assert item["impact"] == "team"
    entries = automated(await world.history(org, item))
    changes = {c["field"]: (c["old"], c["new"]) for c in entries[0]["changes"]}
    assert changes["impact"] == ("organisation", "team")


async def test_req_rul_004_a_refusal_creates_nothing_and_says_why_in_each_language(
    world: World,
) -> None:
    org = world.a
    await add_rule(
        world,
        org,
        name="Hardware needs an asset",
        conditions={"field": "subject", "op": "contains", "value": "laptop"},
        actions=[{"kind": "refuse", "message": {"en": "Name the asset", "ar": "حدد الأصل"}}],
    )
    before = await world.sql(
        "SELECT count(*) AS n FROM work_items WHERE tenant_id = $1", org.tenant
    )
    refused = await world.call(
        "POST",
        BASE,
        org,
        org.admin,
        json={"subject": "Broken laptop", "requester_id": str(org.requester)},
    )
    assert problem(refused) == (422, "rule_refused")
    params = refused.json()["params"]
    assert (params["message"], params["message_ar"], params["message_ur"]) == (
        "Name the asset",
        "حدد الأصل",
        "Name the asset",
    )
    after = await world.sql("SELECT count(*) AS n FROM work_items WHERE tenant_id = $1", org.tenant)
    assert after[0]["n"] == before[0]["n"]


async def test_req_rul_005_order_and_stop_after_this_rule(world: World) -> None:
    org = world.a
    first = await add_rule(world, org, name="First", actions=[set_("priority", "p2")])
    await add_rule(
        world,
        org,
        name="Second",
        conditions={"field": "priority", "op": "eq", "value": "p2"},
        actions=[set_("tags", ["seen"])],
    )
    both = await world.create(org, org.admin)
    assert (both["priority"], both["tags"]) == ("p2", ["seen"])
    stop = await world.call(
        "PATCH",
        f"/automation/rules/{first['id']}",
        org,
        org.admin,
        json={"stop_after": True},
        headers={"If-Match": f'"{first["version"]}"'},
    )
    assert stop.status_code == 200, stop.text
    only_first = await world.create(org, org.admin)
    assert (only_first["priority"], only_first["tags"]) == ("p2", [])
    runs = await world.call(
        "GET", "/automation/runs", org, org.admin, params={"record_id": only_first["id"]}
    )
    outcomes = {r["automation_name"]: r["outcome"] for r in runs.json()}
    assert outcomes == {"First": "applied", "Second": "stopped_before"}


async def test_req_rul_002_requester_attributes_and_updates_with_changed_to(world: World) -> None:
    org = world.a
    await world.sql(
        "UPDATE users SET vip = true WHERE id = $1", org.requester
    )  # the seeded requester becomes a VIP
    await add_rule(
        world,
        org,
        name="VIP",
        conditions={"field": "requester.vip", "op": "eq", "value": True},
        actions=[set_("tags", ["vip"])],
    )
    await add_rule(
        world,
        org,
        name="Raised",
        events=["update"],
        conditions={"field": "impact", "op": "changed_to", "value": "organisation"},
        actions=[set_("tags", ["vip", "escalated"], "overwrite")],
    )
    item = await world.create(org, org.admin)
    assert item["tags"] == ["vip"]
    edited = await world.patch(org, org.admin, item, impact="organisation")
    assert edited.status_code == 200, edited.text
    assert edited.json()["tags"] == ["vip", "escalated"]


async def test_req_rul_029_checked_when_saved(world: World) -> None:
    org = world.a
    bad = await world.call(
        "POST",
        "/automation/rules",
        org,
        org.admin,
        json={
            "record_type": "incident",
            "name": "Bad",
            "events": ["create"],
            "conditions": {"field": "nonsense", "op": "eq", "value": 1},
            "actions": [{"kind": "set", "field": "status", "value": "new"}],
        },
    )
    assert bad.status_code == 422
    codes = {(e["field"], e["code"]) for e in bad.json()["errors"]}
    assert ("body.conditions.field", "unknown_field") in codes
    assert ("body.actions.0.field", "field_not_settable") in codes
    gone = await world.call(
        "POST",
        "/automation/rules",
        org,
        org.admin,
        json={
            "record_type": "incident",
            "name": "Missing group",
            "events": ["create"],
            "actions": [set_("group_id", str(uuid.uuid4()))],
        },
    )
    assert gone.status_code == 422
    assert gone.json()["errors"][0]["code"] == "group_not_found"


async def test_req_rul_029_ac3_a_group_or_custom_field_a_rule_uses_cannot_be_removed(
    world: World,
) -> None:
    org = world.a
    group = await world.call("POST", "/organization/groups", org, org.admin, json={"name": "Night"})
    assert group.status_code == 201, group.text
    await add_routing(world, org, name="Nights", group_id=group.json()["id"])
    blocked = await world.call(
        "DELETE",
        f"/organization/groups/{group.json()['id']}",
        org,
        org.admin,
        headers={"If-Match": f'"{group.json()["version"]}"'},
    )
    assert problem(blocked) == (409, "group_in_use")
    assert blocked.json()["params"] == {"automation_rules": 1}
    field = await world.call(
        "POST",
        "/custom-fields",
        org,
        org.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Room"}},
    )
    assert field.status_code == 201, field.text
    await add_rule(world, org, name="Room rule", actions=[set_("custom.room", "B12")])
    refused = await world.call(
        "DELETE",
        f"/custom-fields/{field.json()['id']}?confirm=true",
        org,
        org.admin,
        headers={"If-Match": f'"{field.json()["version"]}"'},
    )
    assert problem(refused) == (409, "custom_field_used_by_rule")
    assert refused.json()["params"] == {"key": "room", "rules": "Room rule"}


async def test_rules_are_tenant_isolated_and_need_the_permission(world: World) -> None:
    await add_rule(world, world.a, name="Alpha only", actions=[set_("tags", ["alpha"])])
    beta = await world.create(world.b, world.b.admin)
    assert beta["tags"] == []
    listed = await world.call(
        "GET", "/automation/rules", world.b, world.b.admin, params={"record_type": "incident"}
    )
    assert listed.json() == []
    denied = await world.call(
        "GET", "/automation/rules", world.a, world.a.tech_a, params={"record_type": "incident"}
    )
    assert denied.status_code == 403


# --- routing (REQ-ASG-001) -----------------------------------------------------------------------


async def add_routing(world: World, org: Org, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    created = await world.call(
        "POST",
        "/automation/routing",
        org,
        org.admin,
        json={"record_type": "incident", "name": "Route", "state": "enabled", **body},
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


async def test_req_asg_001_ac1_a_routing_rule_sets_the_group_and_history_names_it(
    world: World,
) -> None:
    org = world.a
    printers = await category(world, org, "Printers")
    await add_routing(
        world,
        org,
        name="Printers to GA",
        conditions={"field": "category_id", "op": "eq", "value": printers},
        group_id=str(org.ga),
    )
    item = await world.create(org, org.admin, category_id=printers)
    assert item["group_id"] == str(org.ga)
    entry = automated(await world.history(org, item))[0]
    assert (entry["automation"]["kind"], entry["automation"]["rule"]) == (
        "routing",
        "Printers to GA",
    )


async def test_req_asg_001_category_suggestion_then_fallback_then_the_site_queue(
    world: World,
) -> None:
    org = world.a
    network = await category(world, org, "Network", org.gb)
    by_category = await world.create(org, org.admin, category_id=network)
    assert by_category["group_id"] == str(org.gb)
    # D-097: no fallback group by default; records stay in the site's unassigned queue.
    plain = await world.create(org, org.admin)
    assert plain["group_id"] is None
    settings = await world.call(
        "GET", "/automation/routing-settings", org, org.admin, params={"record_type": "incident"}
    )
    saved = await world.call(
        "PUT",
        "/automation/routing-settings",
        org,
        org.admin,
        params={"record_type": "incident"},
        json={"fallback_group_id": str(org.ga)},
        headers={"If-Match": settings.headers["ETag"]},
    )
    assert saved.status_code == 200, saved.text
    fallback = await world.create(org, org.admin)
    assert fallback["group_id"] == str(org.ga)


async def test_req_asg_001_ac3_a_chosen_group_stays(world: World) -> None:
    org = world.a
    await add_routing(world, org, name="Everything to GA", group_id=str(org.ga))
    item = await world.create(org, org.admin, group_id=str(org.gb))
    assert item["group_id"] == str(org.gb)


# --- auto-assignment (REQ-ASG-002..004, 006, 011) ------------------------------------------------


async def switch_on(world: World, org: Org, group: uuid.UUID, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    current = await world.call("GET", f"/automation/groups/{group}/assignment", org, org.admin)
    saved = await world.call(
        "PUT",
        f"/automation/groups/{group}/assignment",
        org,
        org.admin,
        json={"enabled": True, **body},
        headers={"If-Match": current.headers["ETag"]},
    )
    assert saved.status_code == 200, saved.text
    return saved


async def test_req_asg_002_ac2_off_by_default_leaves_records_in_the_queue(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga))
    assert item["technician_id"] is None


async def test_req_asg_003_round_robin_spreads_evenly_inside_the_group(world: World) -> None:
    org = world.a
    await switch_on(world, org, org.ga)  # GA = {tech A, tech C}
    given: dict[str, int] = {}
    for _ in range(6):
        item = await world.create(org, org.admin, group_id=str(org.ga))
        given[item["technician_id"]] = given.get(item["technician_id"], 0) + 1
    assert given == {str(org.tech_a): 3, str(org.tech_c): 3}
    entry = automated(await world.history(org, item))[-1]
    assert (entry["automation"]["kind"], entry["automation"]["method"]) == (
        "auto_assign",
        "round_robin",
    )


async def test_req_asg_004_load_balancing_names_the_loads(world: World) -> None:
    org = world.a
    await switch_on(world, org, org.gb, method="load_balancing")  # GB = {tech B, tech C}
    busy = await world.create(org, org.admin, group_id=str(org.gb))
    loaded = busy["technician_id"]
    item = await world.create(org, org.admin, group_id=str(org.gb))
    assert item["technician_id"] != loaded  # the other member had less load
    entry = automated(await world.history(org, item))[-1]
    assert set(entry["automation"]["loads"]) == {str(org.tech_b), str(org.tech_c)}


async def test_req_asg_006_away_people_are_never_auto_assigned(world: World) -> None:
    org = world.a
    await switch_on(world, org, org.ga)
    away = await world.call(
        "PUT", f"/automation/availability/{org.tech_a}", org, org.tech_a, json={"state": "away"}
    )
    assert away.status_code == 200, away.text
    for _ in range(3):
        item = await world.create(org, org.admin, group_id=str(org.ga))
        assert item["technician_id"] == str(org.tech_c)
    other = await world.call(
        "PUT", f"/automation/availability/{org.tech_c}", org, org.tech_a, json={"state": "away"}
    )
    assert other.status_code == 403  # someone else only with users.manage


async def test_req_asg_011_nobody_available_waits_in_the_queue_and_says_so(world: World) -> None:
    org = world.a
    await switch_on(world, org, org.ga)
    for person in (org.tech_a, org.tech_c):
        await world.call(
            "PUT", f"/automation/availability/{person}", org, org.admin, json={"state": "away"}
        )
    item = await world.create(org, org.admin, group_id=str(org.ga))
    assert item["technician_id"] is None
    runs = await world.call(
        "GET", "/automation/runs", org, org.admin, params={"record_id": item["id"]}
    )
    assert [r["outcome"] for r in runs.json() if r["kind"] == "assignment"] == ["nobody_available"]
    waiting = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE event_type = 'automation.assignment.waiting'"
        " AND tenant_id = $1",
        org.tenant,
    )
    assert waiting[0]["n"] == 1


async def test_req_asg_002_ac5_never_outside_the_group(world: World) -> None:
    org = world.a
    await switch_on(world, org, org.gb)  # GB = {tech B, tech C}
    seen = {
        (await world.create(org, org.admin, group_id=str(org.gb)))["technician_id"]
        for _ in range(4)
    }
    assert seen <= {str(org.tech_b), str(org.tech_c)}


async def test_req_asg_001_on_move_assigns_inside_the_new_group_and_names_why(
    world: World,
) -> None:
    org = world.a
    await switch_on(world, org, org.gb)  # GB = {tech B, tech C}; GA stays off
    item = await world.create(org, org.admin, group_id=str(org.ga))
    assert item["technician_id"] is None
    moved = await world.assign(org, org.admin, item, group=org.gb, reason_code="wrong_group")
    assert moved.status_code == 200, moved.text
    assert moved.json()["technician_id"] in {str(org.tech_b), str(org.tech_c)}
    history = await world.history(org, moved.json())
    entry = automated(history)[0]
    assert entry["automation"]["kind"] == "auto_assign"
    assert entry["automation"]["group_id"] == str(org.gb)
    # The person's own entry shows the group move only: the technician is the rule's.
    mine = next(h for h in history if h.get("source") != "rule" and h["kind"] == "updated")
    assert {c["field"] for c in mine["changes"]} >= {"group_id"}
    assert "technician_id" not in {c["field"] for c in mine["changes"]}


async def test_req_asg_001_on_move_off_or_a_named_technician_is_left_alone(world: World) -> None:
    org = world.a
    await switch_on(world, org, org.gb, on_move=False)
    item = await world.create(org, org.admin, group_id=str(org.ga))
    moved = await world.assign(org, org.admin, item, group=org.gb, reason_code="wrong_group")
    assert moved.status_code == 200, moved.text
    assert moved.json()["technician_id"] is None
    await switch_on(world, org, org.gb, on_move=True)
    other = await world.create(org, org.admin, group_id=str(org.ga))
    named = await world.assign(
        org, org.admin, other, group=org.gb, technician=org.tech_b, reason_code="wrong_group"
    )
    assert named.status_code == 200, named.text
    assert named.json()["technician_id"] == str(org.tech_b)


async def test_req_rul_001_rules_run_on_a_status_move(world: World) -> None:
    org = world.a
    await add_rule(
        world,
        org,
        name="Resolved",
        events=["update"],
        conditions={"field": "status", "op": "changed_to", "value": "resolved"},
        actions=[set_("tags", ["resolved-check"])],
    )
    item = await world.create(org, org.admin)
    resolved = await world.act(org, org.admin, item, "resolve")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["tags"] == ["resolved-check"]
    entry = automated(await world.history(org, resolved.json()))[0]
    assert entry["automation"]["rule"] == "Resolved"


async def test_routing_then_assignment_in_one_save(world: World) -> None:
    """REQ-RUL-006: rules, matrix, routing, then auto-assignment, each in the history."""
    org = world.a
    await switch_on(world, org, org.ga)
    await add_routing(world, org, name="All to GA", group_id=str(org.ga))
    await add_rule(world, org, name="Impact", actions=[set_("impact", "team")])
    item = await world.create(org, org.admin)
    assert item["group_id"] == str(org.ga)
    assert item["technician_id"] in {str(org.tech_a), str(org.tech_c)}
    # History is newest first; in save order the steps follow REQ-RUL-006.
    kinds = [h["automation"]["kind"] for h in automated(await world.history(org, item))]
    assert list(reversed(kinds)) == ["business_rule", "routing", "auto_assign"]


@pytest.mark.parametrize(
    "table",
    [
        "business_rules",
        "routing_rules",
        "routing_settings",
        "assignment_settings",
        "assignment_turns",
        "technician_availability",
        "automation_runs",
    ],
)
async def test_new_tables_are_tenant_isolated(world: World, table: str) -> None:
    """CLAUDE.md rule a: tenant A never reads or changes tenant B's automation rows."""
    for org in (world.a, world.b):
        await add_rule(world, org, name="R", actions=[set_("tags", ["x"])])
        await add_routing(world, org, name="To GA", group_id=str(org.ga))
        await switch_on(world, org, org.ga)
        await world.call(
            "PUT", f"/automation/availability/{org.tech_a}", org, org.admin, json={"state": "away"}
        )
        await world.create(org, org.admin)
    database = Database(
        create_engine(world.db.app_url, application_name="test", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            tenants = set(await session.scalars(text(f"SELECT DISTINCT tenant_id FROM {table}")))  # noqa: S608 - fixed table names
            assert tenants == {world.a.tenant}
            changed = await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :b"),  # noqa: S608 - fixed table names
                {"b": world.b.tenant},
            )
            assert changed.rowcount == 0  # type: ignore[attr-defined]  # CursorResult at runtime
    except ProgrammingError:
        pass  # no DELETE grant on this table: refused outright, which is isolation too
    finally:
        await database.dispose()


async def make_lead(world: World, org: Org, group: uuid.UUID, lead: uuid.UUID) -> None:
    listed = await world.call("GET", "/organization/groups", org, org.admin)
    (found,) = [g for g in listed.json() if g["id"] == str(group)]
    version = f'"{found["version"]}"'
    changed = await world.call(
        "PATCH",
        f"/organization/groups/{group}",
        org,
        org.admin,
        json={"lead_id": str(lead)},
        headers={"If-Match": version},
    )
    assert changed.status_code == 200, changed.text


async def test_follow_up_a_group_lead_sets_a_member_away_and_it_is_recorded(
    world: World,
) -> None:
    """Product owner, 2026-10-28: leads and admins set a member's availability, with history."""
    org = world.a
    await make_lead(world, org, org.ga, org.tech_c)
    away = await world.call(
        "PUT", f"/automation/availability/{org.tech_a}", org, org.tech_c, json={"state": "away"}
    )
    assert away.status_code == 200, away.text
    (state,) = (
        await world.call(
            "GET",
            "/automation/availability",
            org,
            org.tech_a,
            params={"user_ids": [str(org.tech_a)]},
        )
    ).json()
    assert (state["state"], state["changed_by"]) == ("away", "Alpha Tech C")
    assert state["changed_at"] is not None
    # Someone the lead does not lead (tech B is only in GB): refused.
    other = await world.call(
        "PUT", f"/automation/availability/{org.tech_b}", org, org.tech_c, json={"state": "away"}
    )
    assert other.status_code == 403
    # Back to Available by an admin; both changes are in the history, newest first.
    back = await world.call(
        "PUT", f"/automation/availability/{org.tech_a}", org, org.admin, json={"state": "available"}
    )
    assert back.status_code == 200, back.text
    history = await world.call(
        "GET", f"/automation/availability/{org.tech_a}/history", org, org.tech_c
    )
    assert history.status_code == 200, history.text
    assert [(h["state"], h["changed_by"]) for h in history.json()] == [
        ("available", "Alpha Admin"),
        ("away", "Alpha Tech C"),
    ]
