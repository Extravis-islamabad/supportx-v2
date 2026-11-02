"""SLA policies and settings over HTTP, WP-025 session 2 (REQ-SLA-001..005, D-115 D2/D7).

The incident world of test_incidents_api.py: org A has an admin (every permission) and
technicians; org B is there for isolation. Incidents register with sla at import, so the
`incident` record type exists in every test.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db import test_incidents_api
from tests.db.test_incidents_api import CONSOLE, Org, World, field_codes, problem

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused

POLICIES = "/sla/record-types/incident/policies"
SETTINGS = "/sla/record-types/incident/settings"
TABLES = ("sla_policies", "sla_policy_targets", "sla_settings")


def _new() -> dict[str, str]:
    return {**CONSOLE, "Idempotency-Key": str(uuid.uuid4())}


def _match(version: int) -> dict[str, str]:
    return {**CONSOLE, "If-Match": f'"{version}"'}


def _row(kind: str, amount: int | None, priority: str | None = None, **extra: Any) -> Any:  # noqa: ANN401 - JSON
    return {"kind": kind, "priority": priority, "amount": amount, **extra}


async def _policy(world: World, org: Org, name: str = "VIP", **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    body = {
        "name": name,
        "conditions": {"field": "priority", "op": "eq", "value": "p1"},
        "targets": [_row("first_response", 10, unit="minutes"), _row("resolution", 2)],
        **extra,
    }
    response = await world.call("POST", POLICIES, org, org.admin, json=body, headers=_new())
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_req_sla_001_every_tenant_starts_with_the_default_policy_and_settings(
    world: World,
) -> None:
    a = world.a
    listed = (await world.call("GET", POLICIES, a, a.tech_a)).json()
    assert len(listed) == 1
    (default,) = listed
    assert default["fallback"] is True
    assert default["conditions"] is None
    assert default["can_manage"] is False  # a technician reads, never changes
    # wp-025-plan.md §2: P1 15 min / 4 h around the clock, P4 8 h / 5 business days.
    rows = {(t["kind"], t["priority"]): t for t in default["targets"]}
    assert len(rows) == 8
    assert rows["first_response", "p1"] | {} == _row(
        "first_response",
        15,
        "p1",
        unit="minutes",
        source="around_the_clock",
        fixed_calendar_id=None,
    )
    assert rows["resolution", "p4"]["unit"] == "business_days"
    assert rows["resolution", "p4"]["source"] == "site"
    settings = (await world.call("GET", SETTINGS, a, a.tech_a)).json()
    assert settings == {
        "record_type": "incident",
        "warning_percent": 75,
        "priority_rule": "recalculate",
        "reopen_rule": "resume",
        "version": 1,
    }
    again = (await world.call("GET", POLICIES, a, a.admin)).json()
    assert [p["id"] for p in again] == [default["id"]]


async def test_req_sla_002_policies_go_above_the_default_in_order_and_reorder(
    world: World,
) -> None:
    a = world.a
    vip = await _policy(world, a, "VIP")
    network = await _policy(
        world, a, "Network", conditions={"field": "channel", "op": "eq", "value": "email"}
    )
    listed = (await world.call("GET", POLICIES, a, a.admin)).json()
    assert [p["name"] for p in listed] == ["VIP", "Network", "Default policy"]
    assert listed[-1]["fallback"] is True
    order = [network["id"], vip["id"]]
    moved = await world.call(
        "PUT", f"{POLICIES}/order", a, a.admin, json={"policy_ids": order}, headers=CONSOLE
    )
    assert moved.status_code == 200, moved.text
    assert [p["name"] for p in moved.json()] == ["Network", "VIP", "Default policy"]
    # Every policy but the default, each once.
    partial = await world.call(
        "PUT", f"{POLICIES}/order", a, a.admin, json={"policy_ids": [vip["id"]]}, headers=CONSOLE
    )
    assert field_codes(partial) == {"policy_ids": "order_incomplete"}


async def test_req_sla_001_a_policy_behind_a_catch_all_is_flagged_never_matches(
    world: World,
) -> None:
    a = world.a
    await _policy(world, a, "Everything", conditions=None)
    late = await _policy(world, a, "Late")
    assert late["never_matches"] is True
    listed = (await world.call("GET", POLICIES, a, a.admin)).json()
    # The default policy is never flagged: it is the safety net, not a choice an admin made.
    assert [p["never_matches"] for p in listed] == [False, True, False]


async def test_bad_policies_are_refused_with_field_codes(world: World) -> None:
    a = world.a
    calendar = (await world.call("GET", "/sla/calendars", a, a.admin)).json()[0]
    cases: list[tuple[dict[str, Any], dict[str, str]]] = [
        (
            {"name": "x", "targets": [_row("resolution", 4, "p9")]},
            {"targets.0.priority": "unknown_priority"},
        ),
        (
            {"name": "x", "targets": [_row("resolution", 4), _row("resolution", 5)]},
            {"targets.1": "target_duplicate"},
        ),
        (
            {"name": "x", "targets": [_row("resolution", 4, source="fixed")]},
            {"targets.0": "fixed_calendar_required"},
        ),
        (
            {
                "name": "x",
                "targets": [_row("resolution", 4, fixed_calendar_id=calendar["id"])],
            },
            {"targets.0": "fixed_calendar_unused"},
        ),
        (
            {
                "name": "x",
                "targets": [
                    _row("resolution", 4, source="fixed", fixed_calendar_id=str(uuid.uuid4()))
                ],
            },
            {"targets.0.fixed_calendar_id": "calendar_not_found"},
        ),
        (
            {"name": "x", "conditions": {"field": "resolution_due_at", "op": "is_empty"}},
            {"conditions.field": "unknown_field"},
        ),
    ]
    for body, expected in cases:
        refused = await world.call("POST", POLICIES, a, a.admin, json=body, headers=_new())
        codes = field_codes(refused)
        assert set(expected.items()) <= set(codes.items()), (body, codes)


async def test_req_sla_005_the_default_policy_cannot_get_conditions_be_disabled_or_go(
    world: World,
) -> None:
    a = world.a
    (default,) = (await world.call("GET", POLICIES, a, a.admin)).json()
    url = f"/sla/policies/{default['id']}"
    refused = await world.call(
        "PATCH",
        url,
        a,
        a.admin,
        json={"enabled": False, "conditions": {"field": "priority", "op": "eq", "value": "p1"}},
        headers=_match(default["version"]),
    )
    assert field_codes(refused) == {"conditions": "fallback_fixed", "enabled": "fallback_fixed"}
    gone = await world.call("DELETE", url, a, a.admin, headers=_match(default["version"]))
    assert problem(gone) == (409, "sla_fallback_required")
    # Its targets and name can change.
    changed = await world.call(
        "PATCH",
        url,
        a,
        a.admin,
        json={"targets": [_row("resolution", 6)]},
        headers=_match(default["version"]),
    )
    assert changed.status_code == 200, changed.text
    assert [t["amount"] for t in changed.json()["targets"]] == [6]
    assert changed.headers["ETag"] == f'"{default["version"] + 1}"'


async def test_edits_need_if_match_and_admins_change_technicians_cannot(world: World) -> None:
    a = world.a
    vip = await _policy(world, a)
    url = f"/sla/policies/{vip['id']}"
    by_tech = await world.call(
        "PATCH", url, a, a.tech_a, json={"name": "y"}, headers=_match(vip["version"])
    )
    assert by_tech.status_code == 403
    created = await world.call("POST", POLICIES, a, a.tech_a, json={"name": "t"}, headers=_new())
    assert created.status_code == 403
    renamed = await world.call(
        "PATCH", url, a, a.admin, json={"name": "Gold"}, headers=_match(vip["version"])
    )
    assert renamed.status_code == 200, renamed.text
    stale = await world.call(
        "PATCH", url, a, a.admin, json={"name": "Silver"}, headers=_match(vip["version"])
    )
    assert stale.status_code == 409
    deleted = await world.call("DELETE", url, a, a.admin, headers=_match(vip["version"] + 1))
    assert deleted.status_code == 204, deleted.text
    assert problem(await world.call("GET", url, a, a.admin)) == (404, "sla_policy_not_found")


async def test_settings_change_with_if_match_and_refuse_bad_values(world: World) -> None:
    a = world.a
    settings = (await world.call("GET", SETTINGS, a, a.admin)).json()
    changed = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"warning_percent": 80, "reopen_rule": "restart"},
        headers=_match(settings["version"]),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["warning_percent"] == 80
    assert changed.json()["reopen_rule"] == "restart"
    for body in ({"warning_percent": 0}, {"warning_percent": 100}, {"priority_rule": "x"}):
        refused = await world.call(
            "PATCH", SETTINGS, a, a.admin, json=body, headers=_match(settings["version"] + 1)
        )
        assert refused.status_code == 422, body
    stale = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"warning_percent": 60},
        headers=_match(settings["version"]),
    )
    assert stale.status_code == 409
    unknown = await world.call("GET", "/sla/record-types/nothing/settings", a, a.admin)
    assert problem(unknown) == (404, "sla_record_type_not_found")


async def test_every_policy_change_writes_its_event_and_audit_entry(world: World) -> None:
    a = world.a
    vip = await _policy(world, a)
    await world.call(
        "PATCH",
        f"/sla/policies/{vip['id']}",
        a,
        a.admin,
        json={"enabled": False},
        headers=_match(vip["version"]),
    )
    settings = (await world.call("GET", SETTINGS, a, a.admin)).json()
    await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"warning_percent": 90},
        headers=_match(settings["version"]),
    )
    events = await world.sql(
        "SELECT event_type FROM outbox_events WHERE tenant_id = $1"
        " AND event_type LIKE 'sla.%' ORDER BY id",
        a.tenant,
    )
    assert [r["event_type"] for r in events] == [
        "sla.policy.saved",
        "sla.policy.saved",
        "sla.settings.saved",
    ]
    actions = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND action LIKE 'sla.%'"
        " ORDER BY occurred_at",
        a.tenant,
    )
    assert [r["action"] for r in actions] == [
        "sla.policy_created",
        "sla.policy_changed",
        "sla.settings_changed",
    ]


# --- RLS: every new table of 0047 used here ------------------------------------------------------


async def test_sla_policy_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    vip = await _policy(world, a)
    await world.call("GET", SETTINGS, a, a.admin)
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in TABLES:
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed names
                {"a": a.tenant},
            )
            assert count == 0, table
        for statement in (
            "UPDATE sla_policies SET name = 'x'",
            "UPDATE sla_settings SET warning_percent = 50",
            "DELETE FROM sla_policy_targets",  # rows are replaced on save: no UPDATE grant
        ):
            assert (await session.execute(text(statement))).rowcount == 0, statement
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO sla_settings (tenant_id, record_type) VALUES (:other, 'incident')"
                ),
                {"other": a.tenant},
            )
    url = f"/sla/policies/{vip['id']}"
    assert problem(await world.call("GET", url, b, b.admin)) == (404, "sla_policy_not_found")
    edit = await world.call("PATCH", url, b, b.admin, json={"name": "x"}, headers=_match(1))
    assert problem(edit) == (404, "sla_policy_not_found")
    # B cannot point a target at A's calendar.
    theirs = (await world.call("GET", "/sla/calendars", a, a.admin)).json()[1]
    refused = await world.call(
        "POST",
        POLICIES,
        b,
        b.admin,
        json={
            "name": "x",
            "targets": [_row("resolution", 4, source="fixed", fixed_calendar_id=theirs["id"])],
        },
        headers=_new(),
    )
    assert field_codes(refused) == {"targets.0.fixed_calendar_id": "calendar_not_found"}
    assert [p["fallback"] for p in (await world.call("GET", POLICIES, b, b.admin)).json()] == [True]
