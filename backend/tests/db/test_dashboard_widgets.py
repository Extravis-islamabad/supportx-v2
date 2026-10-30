"""The dashboard widget library (D-114): catalogue, flow report, `@my_groups`, records widgets.

The incident world of test_incidents_api.py through lane A's real incident source: tech_a is in
group GA, tech_b in GB, tech_c in both; the admin holds every permission.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.modules.analytics.domain.builtin import BUILTIN
from app.modules.analytics.domain.dashboard import ME
from app.modules.analytics.domain.widgets import BUILTIN_DASHBOARDS, CATALOGUE, SECTIONS
from tests.db import test_reports_api
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, field_codes

pytestmark = pytest.mark.db
world = test_reports_api.world
reports = test_reports_api.reports
ran = test_reports_api.ran
run = test_reports_api.run


def _noon(days_ago: int) -> datetime:
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days_ago)


async def _at(world: World, item: dict[str, Any], **stamps: datetime) -> None:
    """Move an incident's timestamps (the test's clock; the API stamps "now")."""
    sets = ", ".join(f"{name} = ${i + 2}" for i, name in enumerate(stamps))
    await world.sql(
        f"UPDATE work_items SET {sets} WHERE id = $1",  # noqa: S608 - fixed column names
        uuid.UUID(item["id"]),
        *stamps.values(),
    )


async def _flow_world(world: World) -> None:
    """Four incidents of group GA, at known days (see the flow test for what each shows)."""
    a = world.a
    early = await world.create(a, a.admin, group_id=str(a.ga))  # open since before the window
    await _at(world, early, created_at=_noon(10))
    fixed = await world.create(a, a.admin, group_id=str(a.ga))
    resolved = await world.act(a, a.admin, fixed, "resolve")
    assert resolved.status_code == 200, resolved.text
    await _at(world, fixed, created_at=_noon(3), resolved_at=_noon(1))
    waiting = await world.create(a, a.admin, group_id=str(a.ga))
    await _at(world, waiting, created_at=_noon(2))
    dropped = await world.create(a, a.admin, group_id=str(a.ga))
    canceled = await world.act(a, a.admin, dropped, "cancel", reason_code="duplicate")
    assert canceled.status_code == 200, canceled.text
    await _at(world, dropped, created_at=_noon(5), status_changed_at=_noon(2))


FLOW = {
    "measures": ["flow_created", "flow_resolved", "flow_backlog"],
    "flow": {"days": 7, "bucket": "day"},
    "chart": "line",
}


async def test_d114_flow_counts_created_resolved_and_backlog_per_day(reports: World) -> None:
    world = reports
    a = world.a
    await _flow_world(world)
    in_ga = {"field": "group_id", "op": "eq", "value": str(a.ga)}
    result = await ran(world, a, a.admin, filter=in_ga, **FLOW)
    days = [r["values"] for r in result["rows"]]
    # Oldest first: 6 days ago ... today. Backlog is what is still open at each day's end.
    assert days == [
        [0, 0, 1],  # 6 days ago: only the one from before the window
        [1, 0, 2],  # 5: the later-cancelled one arrives
        [0, 0, 2],
        [1, 0, 3],  # 3: the later-resolved one arrives
        [1, 0, 3],  # 2: one arrives, the cancelled one leaves
        [0, 1, 2],  # 1: one resolved
        [0, 0, 2],  # today
    ]
    assert result["totals"] == [3, 1, 2]  # created and resolved over the range; backlog now
    first = result["rows"][1]["drill"]  # a click opens the ones created that day
    assert {"field": "created_at", "op": "gte", "value": first["and"][1]["value"]} in first["and"]

    # The viewer's scope: tech_b (group GB) sees none of group GA's.
    other = await ran(world, a, a.tech_b, filter=in_ga, **FLOW)
    assert other["totals"] == [0, 0, 0]


async def test_d114_flow_reports_are_checked(reports: World) -> None:
    world = reports
    a = world.a
    grouped = await run(world, a, a.admin, group_by=[{"field": "priority"}], **FLOW)
    assert field_codes(grouped) == {"group_by": "flow_without_groupings"}
    wrong = await run(world, a, a.admin, **{**FLOW, "measures": ["count"]})
    assert field_codes(wrong) == {"measures[0]": "unknown_measure"}
    short = await run(world, a, a.admin, **{**FLOW, "flow": {"days": 3}})
    assert short.status_code == 422


async def test_d114_my_groups_is_the_viewers_own_groups_on_the_server(reports: World) -> None:
    world = reports
    a = world.a
    await test_reports_api.seed(world)  # two in GA, two in GB, two without a group
    mine = {"field": "group_id", "op": "in", "value": "@my_groups"}
    for user, expected in ((a.tech_a, 2), (a.tech_b, 2), (a.tech_c, 4), (a.admin, 0)):
        result = await ran(world, a, user, filter=mine, measures=["count"], chart="kpi")
        assert result["totals"] == [expected], user
    # The drill filter carries the resolved groups, so the list opens exactly those records.
    grouped = await ran(world, a, a.tech_a, filter=mine, group_by=[{"field": "group_id"}])
    assert grouped["drill_all"] == {"field": "group_id", "op": "in", "value": [str(a.ga)]}


async def test_d114_new_key_numbers(reports: World) -> None:
    world = reports
    a = world.a
    late = await world.create(a, a.admin, group_id=str(a.ga))
    await _at(world, late, resolution_due_at=_noon(1))
    soon = await world.create(a, a.admin, group_id=str(a.ga))
    await _at(world, soon, resolution_due_at=datetime.now(UTC) + timedelta(minutes=5))
    result = await ran(
        world,
        a,
        a.admin,
        measures=["overdue_count", "due_today_count", "awaiting_response_count"],
        chart="table",
    )
    overdue, due_today, awaiting = result["totals"]
    assert overdue == 1
    assert due_today >= 1  # "today" in UTC; the soon one is due within minutes
    assert awaiting == 2  # nobody has answered either yet


# --- records widgets ------------------------------------------------------------------------------


def _records_board(records: dict[str, Any]) -> dict[str, Any]:
    widget = {"id": "list", "title": "Latest", "records": records}
    widget["place"] = {"x": 0, "y": 0, "w": 6, "h": 4}
    return {"name": "Lists", "body": {"widgets": [widget]}}


async def test_d114_records_widgets_save_and_are_checked(reports: World) -> None:
    world = reports
    a = world.a
    headers = {**CONSOLE, "Idempotency-Key": str(uuid.uuid4())}
    good = _records_board(
        {
            "entity": "incident",
            "filter": {"field": "technician_id", "op": "eq", "value": ME},
            "sort": "updated",
            "limit": 5,
        }
    )
    saved = await world.call("POST", "/dashboards", a, a.tech_a, json=good, headers=headers)
    assert saved.status_code == 201, saved.text
    groups = _records_board(
        {"entity": "incident", "filter": {"field": "group_id", "op": "in", "value": "@my_groups"}}
    )
    refused = await world.call(
        "POST",
        "/dashboards",
        a,
        a.tech_a,
        json=groups,
        headers={**headers, "Idempotency-Key": "x1"},
    )
    assert field_codes(refused) == {"body.widgets.0.records.filter": "my_groups_in_records"}
    unknown = _records_board({"entity": "incident", "filter": {"field": "nope", "op": "is_null"}})
    bad = await world.call(
        "POST",
        "/dashboards",
        a,
        a.tech_a,
        json=unknown,
        headers={**headers, "Idempotency-Key": "x2"},
    )
    assert bad.status_code == 422


# --- the catalogue ------------------------------------------------------------------------------


async def _catalogue(world: World, org: Org, user: uuid.UUID) -> dict[str, Any]:
    response = await world.call("GET", "/dashboards/widgets", org, user)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_d114_catalogue_lists_every_builtin_report_and_widget(reports: World) -> None:
    world = reports
    a = world.a
    catalogue = await _catalogue(world, a, a.tech_a)
    assert catalogue["sections"] == list(SECTIONS)
    codes = {e["code"] for e in catalogue["entries"]}
    assert codes == set(CATALOGUE)
    assert {f"report_{code}" for code in BUILTIN} <= codes  # every built-in report
    later = {e["code"]: e["coming_with"] for e in catalogue["entries"] if e["coming_with"]}
    assert later == {
        "sla_breached": "sla",
        "sla_at_risk": "sla",
        "sla_breaches_by_technician": "sla",
        "first_response_sla": "sla",
        "pending_approvals": "approvals",
    }
    # A requester may not use reports at all.
    denied = await world.call("GET", "/dashboards/widgets", a, a.requester)
    assert denied.status_code == 403


async def test_d114_every_catalogue_widget_runs_in_the_viewers_scope(reports: World) -> None:
    world = reports
    a = world.a
    await test_reports_api.seed(world)
    catalogue = await _catalogue(world, a, a.tech_a)
    for entry in catalogue["entries"]:
        if entry["coming_with"]:
            continue
        widget = entry["widget"]
        if widget["records"] is not None:
            records = widget["records"]
            tree = json.dumps(records["filter"]).replace(f'"{ME}"', f'"{a.tech_a}"')
            sort = {"updated": "-updated_at", "created": "-created_at", "due": "resolution_due_at"}
            query = httpx.QueryParams(
                {"sort": sort.get(records["sort"], records["sort"]), "limit": records["limit"]}
                | ({"filter": tree} if records["filter"] is not None else {})
            )
            listed = await world.call("GET", f"{BASE}?{query}", a, a.tech_a)
            assert listed.status_code == 200, (entry["code"], listed.text)
            continue
        if widget["report"] is not None:
            definition = widget["report"]
        else:
            definition = BUILTIN[widget["report_ref"].removeprefix("builtin:")].definition
            definition = definition.model_dump(mode="json", by_alias=True)
        result = await run(world, a, a.tech_a, **{**definition, "entity": "incident"})
        assert result.status_code == 200, (entry["code"], result.text)


async def test_d114_builtin_dashboards_are_built_from_the_catalogue() -> None:
    for code, body in BUILTIN_DASHBOARDS.items():
        for widget in body.widgets:
            assert widget.id in CATALOGUE, (code, widget.id)
            assert CATALOGUE[widget.id].coming_with is None
