"""SLA clocks on incidents, WP-025 session 2 (REQ-SLA-015..020, 029; wp-025-plan.md §3.4).

The incident world of test_incidents_api.py. P1 targets of the default policy run around the
clock (15 minutes to respond, 4 hours to resolve), so due moments follow from the stored rows
whatever time the test runs at.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db import test_incidents_api
from tests.db.test_incidents_api import CONSOLE, Org, World

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused

POLICIES = "/sla/record-types/incident/policies"
SETTINGS = "/sla/record-types/incident/settings"


async def _p1(world: World, org: Org, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return await world.create(
        org,
        org.admin,
        priority="p1",
        priority_reason="Whole floor down",
        technician_id=str(org.tech_a),
        group_id=str(org.ga),
        **values,
    )


async def _targets(world: World, item: dict[str, Any]) -> dict[str, Any]:
    rows = await world.sql(
        "SELECT * FROM sla_targets WHERE record_id = $1 ORDER BY kind, round", uuid.UUID(item["id"])
    )
    return {f"{r['kind']}:{r['round']}": dict(r) for r in rows}


async def _events(world: World, item: dict[str, Any]) -> list[str]:
    rows = await world.sql(
        "SELECT event_type FROM outbox_events WHERE aggregate_id = $1"
        " AND aggregate_type = 'sla_record' ORDER BY id",
        item["id"],
    )
    return [r["event_type"] for r in rows]


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def test_req_sla_015_a_new_incident_gets_the_policy_and_its_due_dates(world: World) -> None:
    a = world.a
    item = await _p1(world, a)
    (default,) = (await world.call("GET", POLICIES, a, a.admin)).json()
    assert item["sla_policy_id"] == default["id"]
    rows = await _targets(world, item)
    response, resolution = rows["first_response:1"], rows["resolution:1"]
    assert (response["target_seconds"], resolution["target_seconds"]) == (15 * 60, 4 * 3600)
    assert response["state"] == resolution["state"] == "running"
    assert resolution["due_at"] == resolution["running_since"] + timedelta(hours=4)
    assert _iso(item["resolution_due_at"]) == resolution["due_at"]
    assert _iso(item["first_response_due_at"]) == response["due_at"]
    # The warning point (75 % by default) of a running clock.
    assert resolution["warning_at"] == resolution["running_since"] + timedelta(hours=3)
    applied = await world.sql(
        "SELECT reason, policy_id, current FROM sla_applications WHERE record_id = $1",
        uuid.UUID(item["id"]),
    )
    assert [(r["reason"], str(r["policy_id"]), r["current"]) for r in applied] == [
        ("created", default["id"], True)
    ]
    assert await _events(world, item) == ["sla.record.applied"]
    history = (await world.history(a, item))[-1]  # the oldest save
    assert history["kind"] == "created"


async def test_req_sla_016_on_hold_pauses_and_resuming_moves_the_due_date(world: World) -> None:
    a = world.a
    item = await _p1(world, a)
    started = (await _targets(world, item))["resolution:1"]["running_since"]
    waiting = await world.act(a, a.tech_a, item, "wait_requester", "more_information", "Logs")
    assert waiting.status_code == 200, waiting.text
    assert waiting.json()["resolution_due_at"] is None  # paused: no due moment
    rows = await _targets(world, item)
    assert rows["resolution:1"]["state"] == "paused"
    pauses = await world.sql(
        "SELECT cause, ended_at FROM sla_pauses WHERE target_id = $1",
        rows["resolution:1"]["id"],
    )
    assert [(p["cause"], p["ended_at"]) for p in pauses] == [("awaiting_requester", None)]
    resumed = await world.act(a, a.tech_a, waiting.json(), "resume")
    assert resumed.status_code == 200, resumed.text
    after = (await _targets(world, item))["resolution:1"]
    assert after["state"] == "running"
    # What was left when it paused, counted from the resume.
    left = after["target_seconds"] - after["used_seconds"]
    assert after["due_at"] == after["running_since"] + timedelta(seconds=left)
    assert after["due_at"] >= started + timedelta(hours=4)
    ended = await world.sql(
        "SELECT ended_at, business_seconds FROM sla_pauses WHERE target_id = $1", after["id"]
    )
    assert ended[0]["ended_at"] is not None
    assert ended[0]["business_seconds"] >= 0
    assert await _events(world, item) == [
        "sla.record.applied",
        "sla.target.paused",
        "sla.target.paused",
        "sla.target.resumed",
        "sla.target.resumed",
    ]


async def test_req_sla_017_resolving_meets_both_and_the_response_counts_at_resolution(
    world: World,
) -> None:
    a = world.a
    item = await _p1(world, a)
    resolved = await world.act(a, a.tech_a, item, "resolve")
    assert resolved.status_code == 200, resolved.text
    rows = await _targets(world, item)
    assert (rows["resolution:1"]["state"], rows["resolution:1"]["met_how"]) == ("met", "on_time")
    assert (rows["first_response:1"]["state"], rows["first_response:1"]["met_how"]) == (
        "met",
        "at_resolution",
    )
    # REQ-SLA-029, resume (the default): the reopened target goes on from where it was.
    reopened = await world.act(a, a.tech_a, resolved.json(), "reopen", "not_fixed", "Again")
    assert reopened.status_code == 200, reopened.text
    rows = await _targets(world, item)
    assert rows["resolution:1"]["state"] == "running"
    assert "resolution:2" not in rows
    assert rows["first_response:1"]["state"] == "met"  # a met response stays met


async def test_req_sla_029_reopen_with_restart_starts_a_new_round(world: World) -> None:
    a = world.a
    settings = (await world.call("GET", SETTINGS, a, a.admin)).json()
    changed = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"reopen_rule": "restart"},
        headers={**CONSOLE, "If-Match": f'"{settings["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    item = await _p1(world, a)
    resolved = await world.act(a, a.tech_a, item, "resolve")
    reopened = await world.act(a, a.tech_a, resolved.json(), "reopen", "not_fixed", "Again")
    assert reopened.status_code == 200, reopened.text
    rows = await _targets(world, item)
    assert rows["resolution:1"]["state"] == "met"  # the first round keeps its stamps
    assert rows["resolution:2"]["state"] == "running"
    assert rows["resolution:2"]["used_seconds"] == 0
    assert _iso(reopened.json()["resolution_due_at"]) == rows["resolution:2"]["due_at"]


async def test_closing_or_canceling_stops_open_clocks_without_a_breach(world: World) -> None:
    a = world.a
    item = await _p1(world, a)
    canceled = await world.act(a, a.tech_a, item, "cancel", "duplicate", "Same as another")
    assert canceled.status_code == 200, canceled.text
    rows = await _targets(world, item)
    assert {r["state"] for r in rows.values()} == {"stopped"}
    assert all(r["breached_at"] is None for r in rows.values())


async def test_req_sla_018_a_priority_change_recalculates_from_the_start(world: World) -> None:
    a = world.a
    item = await _p1(world, a)
    first = (await _targets(world, item))["resolution:1"]
    changed = await world.patch(a, a.tech_a, item, priority="p2", priority_reason="Narrower")
    assert changed.status_code == 200, changed.text
    rows = await _targets(world, item)
    # P2 resolution: 8 hours on the site calendar (none set: the default operating hours).
    assert rows["resolution:1"]["target_seconds"] == 8 * 3600
    assert rows["resolution:1"]["id"] == first["id"]  # the same clock, retargeted
    reasons = await world.sql(
        "SELECT reason, current FROM sla_applications WHERE record_id = $1 ORDER BY applied_at",
        uuid.UUID(item["id"]),
    )
    assert [(r["reason"], r["current"]) for r in reasons] == [
        ("created", False),
        ("priority_changed", True),
    ]
    assert "sla.target.recalculated" in await _events(world, item)
    # The SLA's own entry in the record's history, beside the person's change.
    entry = next(e for e in await world.history(a, item) if e["source"] == "sla")
    assert {c["field"] for c in entry["changes"]} >= {"resolution_due_at"}


async def test_req_sla_002_the_first_matching_policy_applies_and_others_keep_theirs(
    world: World,
) -> None:
    a = world.a
    vip = await world.call(
        "POST",
        POLICIES,
        a,
        a.admin,
        json={
            "name": "Key requester",
            "conditions": {"field": "requester_id", "op": "eq", "value": str(a.requester2)},
            "targets": [{"kind": "resolution", "amount": 1, "unit": "hours"}],
        },
        headers={**CONSOLE, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert vip.status_code == 201, vip.text
    other = await _p1(world, a)
    email = await _p1(world, a, requester_id=str(a.requester2))
    assert email["sla_policy_id"] == vip.json()["id"]
    assert other["sla_policy_id"] != vip.json()["id"]
    rows = await _targets(world, email)
    assert rows["resolution:1"]["target_seconds"] == 3600
    assert "first_response:1" not in rows  # the policy has no response target
    # D-115 D7: editing the policy later leaves running records alone.
    policy = vip.json()
    edited = await world.call(
        "PATCH",
        f"/sla/policies/{policy['id']}",
        a,
        a.admin,
        json={"targets": [{"kind": "resolution", "amount": 2, "unit": "hours"}]},
        headers={**CONSOLE, "If-Match": f'"{policy["version"]}"'},
    )
    assert edited.status_code == 200, edited.text
    assert (await _targets(world, email))["resolution:1"]["target_seconds"] == 3600


# --- RLS: the per-record tables of 0047 ---------------------------------------------------------


async def test_sla_clock_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    item = await _p1(world, a)
    await world.act(a, a.tech_a, item, "wait_requester", "more_information", "Logs")
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("sla_applications", "sla_targets", "sla_pauses"):
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed names
                {"a": a.tenant},
            )
            assert count == 0, table
        for statement in (
            "UPDATE sla_applications SET current = false",
            "UPDATE sla_targets SET used_seconds = 0",
            "UPDATE sla_pauses SET cause = 'x'",
        ):
            assert (await session.execute(text(statement))).rowcount == 0, statement
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO sla_applications (id, tenant_id, record_type, record_id, reason,"
                    " snapshot, applied_at) VALUES (:id, :other, 'incident', :id, 'created',"
                    " '{}', now())"
                ),
                {"id": uuid.uuid4(), "other": a.tenant},
            )


# --- due dates set by hand (REQ-SLA-028, D-115 D11) --------------------------------------------


async def _set_due(
    world: World,
    org: Org,
    user: uuid.UUID,
    item: dict[str, Any],
    kind: str,
    due_at: datetime | None,
    reason: str = "Agreed with the requester",
) -> Any:  # noqa: ANN401 - the httpx response
    return await world.call(
        "PUT",
        f"/incidents/{item['id']}/due-dates/{kind}",
        org,
        user,
        json={"due_at": due_at.isoformat() if due_at else None, "reason": reason},
        headers={**CONSOLE, "If-Match": f'"{item["version"]}"'},
    )


async def test_req_sla_028_a_due_date_set_by_hand_stays_until_cleared(world: World) -> None:
    a = world.a
    item = await _p1(world, a)
    calculated = (await _targets(world, item))["resolution:1"]["due_at"]
    wanted = calculated + timedelta(days=2)
    response = await _set_due(world, a, a.admin, item, "resolution", wanted)
    assert response.status_code == 200, response.text
    item = response.json()
    assert _iso(item["resolution_due_at"]) == wanted
    row = (await _targets(world, item))["resolution:1"]
    assert (row["manual_due_at"], row["manual_by"], row["manual_reason"]) == (
        wanted,
        a.admin,
        "Agreed with the requester",
    )
    assert row["warning_at"] is None  # a date set by hand has no business-time share
    assert "sla.target.set_by_hand" in await _events(world, item)
    entry = (await world.history(a, item))[0]
    assert entry["reason"] == "Agreed with the requester"
    assert [c["field"] for c in entry["changes"]] == ["resolution_due_at"]
    # AC1: a priority change does not move it.
    changed = await world.patch(a, a.admin, item, priority="p2", priority_reason="Narrower")
    assert changed.status_code == 200, changed.text
    assert _iso(changed.json()["resolution_due_at"]) == wanted
    # AC2: clearing recalculates from the record's SLA (now P2: 8 business hours).
    cleared = await _set_due(world, a, a.admin, changed.json(), "resolution", None, "Back to SLA")
    assert cleared.status_code == 200, cleared.text
    row = (await _targets(world, item))["resolution:1"]
    assert row["manual_due_at"] is None
    assert row["manual_by"] is None
    assert row["target_seconds"] == 8 * 3600
    assert _iso(cleared.json()["resolution_due_at"]) == row["due_at"] != wanted


async def test_due_dates_by_hand_need_the_permission_a_reason_and_a_future_moment(
    world: World,
) -> None:
    a = world.a
    item = await _p1(world, a)
    later = datetime.fromisoformat(item["resolution_due_at"]) + timedelta(hours=1)
    # D-115 D11: technicians do not hold it by default.
    refused = await _set_due(world, a, a.tech_a, item, "resolution", later)
    assert refused.status_code == 403, refused.text
    blank = await _set_due(world, a, a.admin, item, "resolution", later, reason="  ")
    assert blank.status_code == 422, blank.text
    past = await _set_due(world, a, a.admin, item, "resolution", later - timedelta(days=30))
    assert past.status_code == 422, past.text
    assert past.json()["errors"][0]["code"] == "due_in_past"
    stale = await _set_due(world, a, a.admin, {**item, "version": 0}, "resolution", later)
    assert stale.status_code == 409, stale.text
    resolved = await world.act(a, a.tech_a, item, "resolve")
    done = await _set_due(world, a, a.admin, resolved.json(), "resolution", later)
    assert done.status_code == 409, done.text
    assert done.json()["code"] == "sla_target_done"
    # Another tenant's admin cannot reach it (404, never a hint it exists).
    other = await _set_due(world, world.b, world.b.admin, item, "resolution", later)
    assert other.status_code == 404, other.text


async def test_req_sla_038_the_panel_shows_policy_targets_calendar_and_who_set_a_date(
    world: World,
) -> None:
    a = world.a
    item = await _p1(world, a)
    panel = await world.call("GET", f"/incidents/{item['id']}/sla", a, a.tech_a)
    assert panel.status_code == 200, panel.text
    body = panel.json()
    assert body["policy_id"] == item["sla_policy_id"]
    assert body["policy_name"]
    assert body["reason"] == "created"
    assert body["may_set_due_dates"] is False  # technicians: not by default (D-115 D11)
    assert [t["kind"] for t in body["targets"]] == ["first_response", "resolution"]
    resolution = body["targets"][1]
    assert resolution["state"] == "running"
    assert resolution["calendar_name"]  # P1 runs around the clock: the system calendar
    assert resolution["manual"] is None
    wanted = _iso(resolution["due_at"]) + timedelta(days=1)
    await _set_due(world, a, a.admin, item, "resolution", wanted)
    by_admin = (await world.call("GET", f"/incidents/{item['id']}/sla", a, a.admin)).json()
    assert by_admin["may_set_due_dates"] is True
    manual = by_admin["targets"][1]["manual"]
    assert _iso(manual["due_at"]) == wanted
    assert (manual["by_id"], manual["reason"]) == (str(a.admin), "Agreed with the requester")
    assert manual["by_name"]
    # Out of reach: another tenant gets 404.
    other = await world.call("GET", f"/incidents/{item['id']}/sla", world.b, world.b.admin)
    assert other.status_code == 404, other.text


async def test_req_sla_010_ac3_the_admin_sees_how_many_open_records_a_calendar_reaches(
    world: World,
) -> None:
    a = world.a
    item = await _p1(world, a)
    calendar_id = (await _targets(world, item))["resolution:1"]["calendar_id"]
    path = f"/sla/calendars/{calendar_id}/open-records"
    before = (await world.call("GET", path, a, a.admin)).json()["count"]
    assert before >= 1
    await world.act(a, a.tech_a, item, "cancel", "duplicate", "Same as another")
    after = (await world.call("GET", path, a, a.admin)).json()["count"]
    assert after == before - 1  # a canceled record's clocks are stopped
    # Another tenant's calendar ID is not found there.
    other = await world.call("GET", path, world.b, world.b.admin)
    assert other.status_code == 404, other.text


async def test_a_priority_change_moving_the_due_date_is_no_due_date_edit_in_the_audit_log(
    world: World,
) -> None:
    """WP-064 (lane A): the SLA engine's due rewrite in the same request is not a person's edit."""
    a = world.a
    item = await _p1(world, a)
    changed = await world.patch(a, a.tech_a, item, priority="p2", priority_reason="Narrower")
    assert changed.status_code == 200, changed.text
    sla_saves = [e for e in await world.history(a, item) if e["source"] == "sla"]
    assert any(c["field"] == "resolution_due_at" for e in sla_saves for c in e["changes"])
    rows = await world.sql(
        "SELECT events FROM audit_entries WHERE tenant_id = $1 AND object_id = $2"
        " AND events IS NOT NULL ORDER BY occurred_at, id",
        a.tenant,
        item["id"],
    )
    last = list(rows[-1]["events"])
    assert "incident.priority_changed" in last
    assert "incident.due_date_changed" not in last
