"""Releases as a report source with their own figures (WP-058b S5b; REQ-REL-060; 0150).

- AC2: on-time delivery is of the releases whose deployment ended; on time means it ended before
  the deployment stage's scheduled end. A release still deploying is neither.
- Every measure counts only the releases the viewer could list, and the drill-down opens the
  release list with the same filter.
- 0150's grants are column-level: the reporting role reads a release's details and its
  approvals' times per tenant, never the release notes or an approval's comment.
"""

import json
from typing import Any

import asyncpg
import httpx
import pytest

from tests.db.per_test_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World, role
from tests.db.test_releases_api import REL, a_release, move

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

RUN = "/reports/run"


async def _run(world: World, org: Org, user: Any, **definition: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        RUN,
        org,
        user,
        json={"definition": {"entity": "release", **definition}},
        headers=CONSOLE,
    )


async def _totals(world: World, org: Org, user: Any, measures: list[str]) -> dict[str, Any]:  # noqa: ANN401 - JSON
    ran = await _run(world, org, user, measures=measures)
    assert ran.status_code == 200, ran.text
    return dict(zip(measures, ran.json()["totals"], strict=True))


async def _deployment(world: World, org: Org, item: dict[str, Any], **body: Any) -> None:  # noqa: ANN401 - JSON
    await _stage_dates(world, org, item, "deployment", **body)


async def _stage_dates(
    world: World,
    org: Org,
    item: dict[str, Any],
    stage: str,
    **body: Any,  # noqa: ANN401 - JSON
) -> None:
    shown = (await world.call("GET", f"{REL}/{item['id']}/schedule", org, org.admin)).json()
    row = next(s for s in shown if s["stage"] == stage)
    set_ = await world.call(
        "PATCH",
        f"{REL}/{item['id']}/schedule/{stage}",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert set_.status_code == 200, set_.text


async def _listed(world: World, org: Org, user: Any, tree: Any) -> set[str]:  # noqa: ANN401 - JSON
    query = {"limit": "100"} | ({"filter": json.dumps(tree)} if tree is not None else {})
    response = await world.call("GET", f"{REL}?{httpx.QueryParams(query)}", org, user)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


async def _three(world: World, org: Org) -> list[dict[str, Any]]:
    """On time, late, and one still deploying (no actual end)."""
    made = [await a_release(world, org) for _ in range(3)]
    window = {"scheduled_start": "2026-11-01T20:00:00Z", "scheduled_end": "2026-11-01T22:00:00Z"}
    for item in made:
        await _deployment(world, org, item, **window)
    await _deployment(
        world,
        org,
        made[0],
        actual_start="2026-11-01T20:00:00Z",
        actual_end="2026-11-01T21:30:00Z",
        reason="From the deployment log",
    )
    await _deployment(
        world,
        org,
        made[1],
        actual_start="2026-11-01T20:00:00Z",
        actual_end="2026-11-01T23:00:00Z",
        reason="From the deployment log",
    )
    return made


async def test_req_rel_060_ac2_on_time_is_of_the_deployments_that_ended(world: World) -> None:
    a = world.a
    made = await _three(world, a)
    totals = await _totals(world, a, a.admin, ["count", "on_time_rate", "failed_count"])
    assert totals["count"] == len(made)
    assert totals["on_time_rate"] == 50  # 1 of the 2 that ended, not of all 3
    assert totals["failed_count"] == 0
    # The drill-down opens the release list with the same filter.
    on_time = {"field": "deployed_on_time", "op": "eq", "value": True}
    assert await _listed(world, a, a.admin, on_time) == {made[0]["id"]}
    ended = {"field": "deployment_ended", "op": "eq", "value": True}
    assert await _listed(world, a, a.admin, ended) == {made[0]["id"], made[1]["id"]}
    # Incidents never take a release's own fields.
    query = str(httpx.QueryParams({"filter": json.dumps(on_time)}))
    refused = await world.call("GET", f"/incidents?{query}", a, a.admin)
    assert refused.status_code == 422, refused.text


async def test_req_rel_060_a_group_scoped_viewer_counts_only_their_groups_releases(
    world: World,
) -> None:
    """The coordinator's access check: measures agree with what the list shows."""
    a = world.a
    ours, theirs = await a_release(world, a), await a_release(world, a)
    for item, group in ((ours, a.gb), (theirs, a.ga)):
        put = await world.call(
            "POST",
            f"{REL}/{item['id']}/assign",
            a,
            a.admin,
            json={"group_id": str(group)},
            headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
        )
        assert put.status_code == 200, put.text
    group_role = await role(
        world, a, "Releases of my groups", [("releases.view", "group"), ("reports.view", "all")]
    )
    given = await world.call("PUT", f"/users/{a.requester2}/roles/{group_role}", a, a.admin)
    assert given.status_code == 204, given.text
    joined = await world.call(
        "PUT", f"/organization/groups/{a.gb}/members/{a.requester2}", a, a.admin
    )
    assert joined.status_code in {200, 204}, joined.text
    seen = await _listed(world, a, a.requester2, None)
    totals = await _totals(world, a, a.requester2, ["count"])
    assert totals["count"] == len(seen)
    assert ours["id"] in seen
    assert theirs["id"] not in seen


async def test_req_rel_060_ac1_the_releases_dashboard_is_ready_made(world: World) -> None:
    a = world.a
    listed = await world.call("GET", "/dashboards", a, a.admin)
    assert listed.status_code == 200, listed.text
    assert "builtin:releases" in json.dumps(listed.json())


async def _as_report(conn: asyncpg.Connection, statement: str) -> None:
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE supportx_report")
        await conn.fetchval(statement)


async def test_0150_the_reporting_role_reads_only_the_granted_columns_per_tenant(
    world: World,
    migrated_db: Any,  # noqa: ANN401 - the throwaway database fixture
) -> None:
    """Lane B's blocking review: column-level SELECT, under RLS, and nothing it may write."""
    a = world.a
    made = await _three(world, a)
    current = (await world.call("GET", f"{REL}/{made[0]['id']}", a, a.admin)).json()
    detailed = await world.call(
        "PATCH",
        f"{REL}/{made[0]['id']}/details",
        a,
        a.admin,
        json={"release_version": "4.2.0", "release_notes": "<p>Private notes</p>"},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert detailed.status_code == 200, detailed.text
    conn = await asyncpg.connect(migrated_db.app_url)
    try:
        for tenant, expect_rows in ((None, False), (world.b.tenant, False), (a.tenant, True)):
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE supportx_report")
                if tenant is not None:
                    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
                found = await conn.fetchval(
                    "SELECT count(release_version) FROM work_item_release_details"
                )
                assert (found > 0) is expect_rows, (tenant, found)
                await conn.fetchval(
                    "SELECT count(*) FROM work_item_approvals WHERE decided_at IS NOT NULL"
                )
        # Never the free text: the release notes and an approval's comment are not granted.
        for statement in (
            "SELECT release_notes FROM work_item_release_details",
            "SELECT comment FROM work_item_approvals",
            "SELECT decided_by FROM work_item_approvals",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await _as_report(conn, statement)
        # Nothing it may write.
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE supportx_report")
            writes = await conn.fetchval(
                "SELECT has_table_privilege('work_item_release_details', 'UPDATE')"
                " OR has_table_privilege('work_item_approvals', 'INSERT')"
            )
        assert writes is False
        bypass = await conn.fetchval(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'supportx_report'"
        )
        assert bypass is False
    finally:
        await conn.close()


async def test_req_rel_060_overdue_is_the_open_release_current_stage_only(world: World) -> None:
    """Lane A's #443 review: a stage it is not in, or a cancelled release, is never overdue."""
    a = world.a
    past = {"scheduled_start": "2026-01-01T08:00:00Z", "scheduled_end": "2026-01-02T08:00:00Z"}
    ahead, current, cancelled = [await a_release(world, a) for _ in range(3)]
    await _stage_dates(world, a, ahead, "deployment", **past)  # not the stage it is in
    await _stage_dates(world, a, current, current["stage"], **past)
    await _stage_dates(world, a, cancelled, cancelled["stage"], **past)
    gone = await move(world, a, cancelled, "closure_canceled", reason_text="Not needed")
    assert gone.status_code == 200, gone.text
    overdue = {"field": "stage_overdue", "op": "eq", "value": True}
    assert await _listed(world, a, a.admin, overdue) == {current["id"]}
    assert (await _totals(world, a, a.admin, ["overdue_count"]))["overdue_count"] == 1
