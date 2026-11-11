"""Changes as a report source with their own figures (WP-045d S4c; REQ-CHG-116).

Success rate is of the changes whose implementation has an outcome; a group with none has no
rate (no data), never 0%. Every measure counts only the changes the viewer could list, and each
chart drills down to the change list with the same filter (AC2). The ready-made Changes
dashboard is listed only to those who may report on changes (AC1).
"""

import json
import uuid
from typing import Any

import asyncpg
import httpx
import pytest

from tests.db.per_test_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_changes_api import CHG, a_change
from tests.db.test_incidents_api import CONSOLE, Org, World, role

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

RUN = "/reports/run"
MEASURES = [
    "count",
    "success_rate",
    "failed_count",
    "emergency_share",
    "retrospective_share",
    "freeze_override_count",
    "average_implementation_time",
    "planned_downtime_total",
    "actual_downtime_total",
]


async def _run(world: World, org: Org, user: Any, **definition: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        RUN,
        org,
        user,
        json={"definition": {"entity": "change", **definition}},
        headers=CONSOLE,
    )


async def _totals(world: World, org: Org, user: Any, **definition: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    found: dict[str, Any] = {}
    for start in range(0, len(MEASURES), 4):  # a report takes at most four measures
        chunk = MEASURES[start : start + 4]
        ran = await _run(world, org, user, measures=chunk, **definition)
        assert ran.status_code == 200, ran.text
        found.update(zip(chunk, ran.json()["totals"], strict=True))
    return found


async def _outcome(world: World, org: Org, item: dict[str, Any], **body: Any) -> None:  # noqa: ANN401 - JSON
    shown = (await world.call("GET", f"{CHG}/{item['id']}/schedule", org, org.admin)).json()
    row = next(s for s in shown if s["stage"] == "implementation")
    set_ = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/implementation",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert set_.status_code == 200, set_.text


async def _listed(world: World, org: Org, user: Any, tree: Any) -> set[str]:  # noqa: ANN401 - JSON
    query = str(httpx.QueryParams({"filter": json.dumps(tree), "limit": "100"}))
    response = await world.call("GET", f"{CHG}?{query}", org, user)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


async def _three(world: World, org: Org) -> list[dict[str, Any]]:
    """Successful (2 h, actual times), backed out, and one with no outcome yet."""
    made = [await a_change(world, org) for _ in range(3)]
    await _outcome(
        world,
        org,
        made[0],
        outcome="successful",
        actual_start="2026-11-01T20:00:00Z",
        actual_end="2026-11-01T22:00:00Z",
        reason="Recorded from the change window log",
    )
    await _outcome(world, org, made[1], outcome="backed_out")
    for phase, hours in (("planned", 1), ("actual", 3)):
        added = await world.call(
            "POST",
            f"{CHG}/{made[0]['id']}/downtimes",
            org,
            org.admin,
            json={
                "phase": phase,
                "starts_at": "2026-11-01T20:00:00Z",
                "ends_at": f"2026-11-01T{20 + hours}:00:00Z",
            },
            headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
        )
        assert added.status_code == 201, added.text
    return made


async def test_req_chg_116_measures_count_outcomes_with_a_stated_denominator(world: World) -> None:
    a = world.a
    made = await _three(world, a)
    totals = await _totals(world, a, a.admin)
    assert totals["count"] == len(made)
    assert totals["success_rate"] == 50  # 1 successful of the 2 with an outcome, not of all 3
    assert totals["failed_count"] == 1
    assert totals["emergency_share"] == 0
    assert totals["freeze_override_count"] == 0
    assert totals["average_implementation_time"] == 2 * 3600  # actual times only
    assert (totals["planned_downtime_total"], totals["actual_downtime_total"]) == (3600, 3 * 3600)
    # An empty tenant: counts are 0, a rate with nothing to be of is no data, never 0%.
    empty = await _totals(world, world.b, world.b.admin)
    assert empty["count"] == 0
    assert empty["success_rate"] is None


async def test_req_chg_116_ac2_each_chart_drills_down_to_the_same_changes(world: World) -> None:
    a = world.a
    made = await _three(world, a)
    ran = await _run(world, a, a.admin, group_by=[{"field": "implementation_outcome"}])
    assert ran.status_code == 200, ran.text
    rows = {r["keys"][0]: r for r in ran.json()["rows"]}
    assert rows["successful"]["values"] == [1]
    # The drill-down filter opens the change list, which takes the change's own fields.
    passed = {"field": "implementation_outcome", "op": "eq", "value": "successful"}
    assert await _listed(world, a, a.admin, passed) == {made[0]["id"]}
    failed = {"field": "implementation_outcome", "op": "in", "value": ["failed", "backed_out"]}
    assert await _listed(world, a, a.admin, failed) == {made[1]["id"]}
    # Incidents never take a change's fields, nor problems a change's.
    for path in ("/incidents", "/problems"):
        query = str(httpx.QueryParams({"filter": json.dumps(passed)}))
        refused = await world.call("GET", f"{path}?{query}", a, a.admin)
        assert refused.status_code == 422, (path, refused.text)


async def test_req_chg_116_a_group_scoped_viewer_counts_only_their_groups_changes(
    world: World,
) -> None:
    """The coordinator's access check: measures and drill-down agree with what the list shows."""
    a = world.a
    ours = await a_change(world, a)
    theirs = await a_change(world, a)
    for item, group in ((ours, a.gb), (theirs, a.ga)):
        put = await world.call(
            "POST",
            f"{CHG}/{item['id']}/assign",
            a,
            a.admin,
            json={"group_id": str(group)},
            headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
        )
        assert put.status_code == 200, put.text
    # Technicians see every change by default (identity's changes.view at all), so the viewer is
    # a person whose role grants changes at group scope, in group GB only.
    group_role = await role(
        world, a, "Changes of my groups", [("changes.view", "group"), ("reports.view", "all")]
    )
    given = await world.call("PUT", f"/users/{a.requester2}/roles/{group_role}", a, a.admin)
    assert given.status_code == 204, given.text
    joined = await world.call(
        "PUT", f"/organization/groups/{a.gb}/members/{a.requester2}", a, a.admin
    )
    assert joined.status_code in {200, 204}, joined.text
    seen = await _listed(world, a, a.requester2, None)
    totals = await _totals(world, a, a.requester2)
    assert totals["count"] == len(seen)
    assert ours["id"] in seen
    assert theirs["id"] not in seen


async def test_req_chg_116_ac1_the_changes_dashboard_is_listed_to_who_may_report_on_changes(
    world: World,
) -> None:
    a = world.a
    listed = await world.call("GET", "/dashboards", a, a.admin)
    assert listed.status_code == 200, listed.text
    refs = {d["ref"] for d in listed.json()["items"]}
    assert "builtin:changes" in refs
    # Its key numbers run in a new tenant (success rate is no data until an outcome exists).
    board = (await world.call("GET", "/dashboards/builtin:changes", a, a.admin)).json()
    for widget in board["body"]["widgets"]:
        if widget.get("report") is not None:
            ran = await world.call(
                "POST", RUN, a, a.admin, json={"definition": widget["report"]}, headers=CONSOLE
            )
            assert ran.status_code == 200, (widget["id"], ran.text)
    # Someone who reports on incidents but may not see changes: no Changes dashboard, and the
    # widget catalogue offers no change widget either.
    incidents_only = await role(
        world, a, "Incident reports", [("reports.view", "all"), ("incidents.view", "all")]
    )
    given = await world.call("PUT", f"/users/{a.requester2}/roles/{incidents_only}", a, a.admin)
    assert given.status_code == 204, given.text
    theirs = await world.call("GET", "/dashboards", a, a.requester2)
    assert theirs.status_code == 200, theirs.text
    assert "builtin:changes" not in {d["ref"] for d in theirs.json()["items"]}
    assert "builtin:service_desk" in {d["ref"] for d in theirs.json()["items"]}
    catalogue = await world.call("GET", "/dashboards/widgets", a, a.requester2)
    assert catalogue.status_code == 200, catalogue.text
    assert not [e for e in catalogue.json()["entries"] if e["module"] == "changes"]
    # Lane C's review: a direct link and a home choice refuse it the same way (404, as unknown).
    direct = await world.call("GET", "/dashboards/builtin:changes", a, a.requester2)
    assert direct.status_code == 404, direct.text
    chosen = await world.call(
        "PUT", "/dashboards/home", a, a.requester2, json={"dashboard_ref": "builtin:changes"}
    )
    assert chosen.status_code == 404, chosen.text
    # A home chosen while they could see changes falls back to their role's built-in home.
    await world.sql(
        "INSERT INTO dashboard_preferences (tenant_id, user_id, home_ref) VALUES ($1, $2, $3)"
        " ON CONFLICT (tenant_id, user_id) DO UPDATE SET home_ref = EXCLUDED.home_ref",
        a.tenant,
        a.requester2,
        "builtin:changes",
    )
    home = await world.call("GET", "/dashboards/home", a, a.requester2)
    assert home.status_code == 200, home.text
    assert (home.json()["dashboard_ref"], home.json()["chosen"]) != ("builtin:changes", True)
    assert home.json()["dashboard_ref"] != "builtin:changes"


CHANGE_TABLES = ("work_item_change_details", "work_item_stage_schedules", "work_item_downtimes")


async def test_0143_the_reporting_role_reads_the_change_tables_per_tenant_only(
    world: World,
    migrated_db: Any,  # noqa: ANN401 - the throwaway database fixture
) -> None:
    """Lane B's grant review: SELECT on exactly the three tables, under RLS (no BYPASSRLS)."""
    a = world.a
    await _three(world, a)
    conn = await asyncpg.connect(migrated_db.app_url)
    try:
        for tenant, expect_rows in ((None, False), (world.b.tenant, False), (a.tenant, True)):
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE supportx_report")
                if tenant is not None:
                    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
                for table in CHANGE_TABLES:
                    found = await conn.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed names
                    assert (found > 0) is expect_rows, (tenant, table, found)
        # Nothing broader: the plans and their texts stay out of reports.
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE supportx_report")
            plans = await conn.fetchval(
                "SELECT has_table_privilege('work_item_plan_sections', 'SELECT')"
            )
        assert plans is False
        bypass = await conn.fetchval(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'supportx_report'"
        )
        assert bypass is False
    finally:
        await conn.close()
