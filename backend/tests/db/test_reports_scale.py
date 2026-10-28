"""Reports at volume (WP-035, D-100 D5): every built-in report and the widget queries at 1M rows.

Opt-in: SUPPORTX_REPORT_SCALE_ROWS sets the number of incidents (the "Report scale" workflow:
1,000,000, nightly and on demand). Without it the test is skipped. The rows are generated inside
PostgreSQL from one incident made through the API (INSERT ... SELECT as the admin role: far
faster than sending a million rows over the wire), spread over a year, both groups, both sites,
every incident status and priority, then ANALYZE. Everything measured runs as a real user through
the HTTP API, the reporting role and lane A's incident source.

D-100 D5: at MVP every widget is operational, at most 2 seconds. Dashboards (WP-036) run built-in
reports and measure totals, so those are what is timed, as the admin (`all` scope) and as a
technician with the D-052 `group` scope, who must never see another group's numbers. Timings go
to SUPPORTX_REPORT_SCALE_REPORT (JSON) when set, and to the test output; the limit is
tooling.timing.limit (the target itself in the workflow, SUPPORTX_PERF_STRICT=1).
"""

import asyncio
import json
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.modules.analytics.domain.builtin import BUILTIN_REPORTS
from tests.db import test_reports_api
from tests.db.test_incidents_api import BASE, World
from tooling import timing

pytestmark = [pytest.mark.db, pytest.mark.scale]
world = test_reports_api.world
reports = test_reports_api.reports

ROWS = int(os.environ.get("SUPPORTX_REPORT_SCALE_ROWS", "0"))
TARGET_SECONDS = 2.0  # D-100 D5: an operational widget
RUNS = 3  # warm runs per query; the median is asserted, the first (cold) run is reported
# Widget-style totals with no grouping (KPI tiles).
KPI = {"measures": ["count", "open_count", "unassigned_open_count"]}

# One template row copied ROWS times with varied columns; n is 1..ROWS.
GENERATE = """
INSERT INTO work_items (
    id, tenant_id, type, display_id, display_number, subject, requester_id, channel, site_id,
    desk_id, group_id, technician_id, priority, priority_source, status, status_category,
    status_changed_at, created_at, updated_at, first_responded_at, resolved_at,
    reassignment_count
)
SELECT
    gen_random_uuid(), t.tenant_id, t.type, 'SCALE-' || n, t.display_number + n,
    'Volume incident ' || n, t.requester_id, t.channel,
    CASE n % 3 WHEN 0 THEN $2::uuid WHEN 1 THEN $3::uuid END,
    t.desk_id,
    CASE n % 5 WHEN 0 THEN NULL WHEN 1 THEN $4::uuid WHEN 2 THEN $4::uuid ELSE $5::uuid END,
    -- Each technician only on their own group's records (own records are visible, D-052).
    CASE WHEN n % 7 = 0 AND n % 5 IN (1, 2) THEN $6::uuid
         WHEN n % 7 = 0 AND n % 5 IN (3, 4) THEN $7::uuid END,
    (ARRAY['p1', 'p2', 'p3', 'p4'])[1 + n % 4],
    'default', s.code, s.category,
    c.created, c.created, c.created,
    c.created + interval '30 minutes',
    CASE WHEN s.category IN ('resolved', 'closed') THEN c.created + interval '6 hours' END,
    n % 3
FROM generate_series(1, $8::int) AS n
CROSS JOIN (SELECT * FROM work_items WHERE id = $1) AS t
CROSS JOIN LATERAL (
    SELECT now() - make_interval(secs => (n::bigint * 31536000 / $8::int)) AS created
) AS c
JOIN LATERAL (
    SELECT code, category FROM work_item_statuses
    WHERE tenant_id = t.tenant_id AND type = t.type
    ORDER BY code OFFSET n % $9::int LIMIT 1
) AS s ON true
"""


async def _load(world: World) -> None:
    a = world.a
    template = await world.create(a, a.admin, group_id=str(a.ga))
    statuses = await world.sql(
        "SELECT count(*) AS n FROM work_item_statuses s JOIN work_items w"
        " ON w.tenant_id = s.tenant_id AND w.type = s.type WHERE w.id = $1",
        uuid.UUID(template["id"]),
    )
    await world.sql(
        GENERATE,
        uuid.UUID(template["id"]),
        a.s1,
        a.s2,
        a.ga,
        a.gb,
        a.tech_a,
        a.tech_b,
        ROWS,
        statuses[0]["n"],
    )
    await world.sql("ANALYZE work_items")


async def _time(world: World, user: uuid.UUID, definition: dict[str, Any]) -> dict[str, Any]:
    a = world.a
    seconds: list[float] = []
    result: dict[str, Any] = {}
    for _ in range(RUNS + 1):
        started = time.perf_counter()
        response = await test_reports_api.run(world, a, user, **definition)
        seconds.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
        result = response.json()
    return {
        "cold": round(seconds[0], 3),
        "median": round(statistics.median(seconds[1:]), 3),
        "max": round(max(seconds[1:]), 3),
        "result": result,
    }


@pytest.mark.timing
@pytest.mark.skipif(ROWS <= 0, reason="set SUPPORTX_REPORT_SCALE_ROWS to run the volume test")
async def test_d100_d5_every_builtin_report_and_widget_within_two_seconds(
    reports: World,
) -> None:
    world = reports
    a = world.a
    started = time.perf_counter()
    await _load(world)
    timings: dict[str, Any] = {
        "rows": ROWS,
        "target_seconds": TARGET_SECONDS,
        "limit_seconds": timing.limit(TARGET_SECONDS),
        "load_seconds": round(time.perf_counter() - started, 1),
    }
    print(f"loaded {ROWS} incidents in {timings['load_seconds']}s", flush=True)  # noqa: T201 - progress of a long run

    queries: dict[str, dict[str, Any]] = {"kpi_totals": KPI}
    for report in BUILTIN_REPORTS:
        queries[report.code] = report.definition.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
    measured: dict[str, dict[str, Any]] = {}
    for viewer, user in (("admin", a.admin), ("technician_group_scope", a.tech_a)):
        for code, definition in queries.items():
            body = {k: v for k, v in definition.items() if k != "entity"}
            found = await _time(world, user, body)
            result = found.pop("result")
            measured[f"{viewer}:{code}"] = found
            print(f"{viewer}:{code} {found}", flush=True)  # noqa: T201 - progress of a long run
            by_group = [g.get("field") for g in body.get("group_by", [])] == ["group_id"]
            if viewer == "technician_group_scope" and by_group:
                # D-052: GA, plus the S1 site queue (no group); never GB's numbers.
                assert {r["keys"][0] for r in result["rows"]} <= {str(a.ga), None}, code
            if code == "kpi_totals":
                timings[f"{viewer}_total"] = result["totals"][0]

    # The drill-down from a widget opens the incident list: its first page.
    drill_seconds: list[float] = []
    for _ in range(RUNS):
        started = time.perf_counter()
        response = await world.call("GET", f"{BASE}?limit=50", a, a.tech_a)
        drill_seconds.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
    measured["technician_group_scope:list_first_page"] = {
        "median": round(statistics.median(drill_seconds), 3),
        "max": round(max(drill_seconds), 3),
    }

    slowest = max(measured.items(), key=lambda item: item[1]["median"])
    timings["slowest"] = {"query": slowest[0], **slowest[1]}
    timings["queries"] = measured
    assert timings["admin_total"] == ROWS + 1
    assert 0 < timings["technician_group_scope_total"] < timings["admin_total"]
    if target := os.environ.get("SUPPORTX_REPORT_SCALE_REPORT"):
        await asyncio.to_thread(
            Path(target).write_text, json.dumps(timings, indent=2, sort_keys=True)
        )
    timing.record("reports_at_volume", {"rows": ROWS, "slowest": timings["slowest"]})
    bound = timing.limit(TARGET_SECONDS)
    over = {q: m["median"] for q, m in measured.items() if m["median"] > bound}
    assert not over, f"over {bound}s at {ROWS} rows: {over}"
