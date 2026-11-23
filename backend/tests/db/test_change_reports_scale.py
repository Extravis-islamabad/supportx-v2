"""Change reports at volume (WP-045d S4c; the coordinator's check on REQ-CHG-116).

Opt-in: SUPPORTX_CHANGE_REPORT_SCALE_ROWS sets the number of changes (100,000 for the check the
coordinator asked for). Without it the test is skipped. The change figures are correlated
subqueries on the change's own rows (details, stage schedules, downtimes), so this times the
ready-made Changes dashboard's widgets on a big tenant, as the admin (`all` scope) and as a
viewer with changes at `group` scope, and prints EXPLAIN ANALYZE of the slowest one.

The rows are copied inside PostgreSQL from one change made through the API (INSERT ... SELECT as
the admin role), with every child row it has, spread over a year and both groups, with varied
types, risks, outcomes and paths, then ANALYZE. Target: 2 seconds a widget (D-100 D5).
"""

import os
import statistics
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from app.core.tenancy import TenantContext
from app.modules.analytics.domain.builtin import BUILTIN
from app.modules.analytics.domain.definition import ReportDefinition
from app.modules.analytics.domain.widgets import BUILTIN_DASHBOARDS
from app.modules.analytics.service.compiler import compile_report
from app.modules.identity_access import subject_for
from app.shared.reporting import provider_for
from tests.db.per_test_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_change_reports import _run, _three
from tests.db.test_incidents_api import World, role
from tooling import timing

pytestmark = [pytest.mark.db, pytest.mark.scale, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixture, re-used

ROWS = int(os.environ.get("SUPPORTX_CHANGE_REPORT_SCALE_ROWS", "0"))
TARGET_SECONDS = 2.0  # D-100 D5: an operational widget
RUNS = 3

# Each copy n of the template change gets a stable id, so its child rows can name it.
NEW_ID = "md5(t_id::text || '-' || n)::uuid"
WORK_ITEMS = {
    "id": NEW_ID,
    "display_id": "'SCALE-' || n",
    "display_number": "t.display_number + 1000 + n",  # past the three made through the API
    "subject": "'Volume change ' || n",
    "group_id": "CASE n % 2 WHEN 0 THEN $3::uuid ELSE $4::uuid END",
    "stage_path": "CASE WHEN n % 10 = 0 THEN 'emergency' ELSE t.stage_path END",
    "created_at": "now() - make_interval(secs => (n::bigint * 31536000 / $2::int))",
    "updated_at": "now() - make_interval(secs => (n::bigint * 31536000 / $2::int))",
}
DETAILS = {
    "work_item_id": NEW_ID,
    "risk": "(ARRAY['low', 'medium', 'high', 'very_high'])[1 + n % 4]",
    "retrospective": "n % 25 = 0",
    "freeze_override_at": "CASE WHEN n % 50 = 0 THEN now() END",
}
SCHEDULES = {
    "work_item_id": NEW_ID,
    "outcome": (
        "CASE WHEN t.stage = 'implementation' THEN"
        " (ARRAY['successful', 'successful_with_issues', 'failed', 'backed_out', NULL])[1 + n % 5]"
        " ELSE t.outcome END"
    ),
}
DOWNTIMES = {"id": "gen_random_uuid()", "work_item_id": NEW_ID}


async def _copy(
    world: World, table: str, template: uuid.UUID, overrides: dict[str, str], key: str
) -> None:
    a = world.a
    columns = [
        r["column_name"]
        for r in await world.sql(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public'"
            " AND table_name = $1 AND is_generated = 'NEVER' ORDER BY ordinal_position",
            table,
        )
    ]
    chosen = ", ".join(overrides.get(c, f"t.{c}") for c in columns)
    await world.sql(
        f"INSERT INTO {table} ({', '.join(columns)})"  # noqa: S608 - fixed table and column names
        f" SELECT {chosen} FROM generate_series(1, $2::int) AS n"
        f" CROSS JOIN (SELECT *, $1::uuid AS t_id FROM {table} WHERE {key} = $1) AS t"
        " WHERE $3::uuid IS NOT NULL AND $4::uuid IS NOT NULL",
        template,
        ROWS,
        a.ga,
        a.gb,
    )


async def _load(world: World) -> None:
    template = uuid.UUID((await _three(world, world.a))[0]["id"])
    await _copy(world, "work_items", template, WORK_ITEMS, "id")
    await _copy(world, "work_item_change_details", template, DETAILS, "work_item_id")
    await _copy(world, "work_item_stage_schedules", template, SCHEDULES, "work_item_id")
    await _copy(world, "work_item_downtimes", template, DOWNTIMES, "work_item_id")
    for table in ("work_items", *(t for t in ("work_item_change_details",
                                              "work_item_stage_schedules",
                                              "work_item_downtimes"))):  # fmt: skip
        await world.sql(f"ANALYZE {table}")


def _definitions() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for widget in BUILTIN_DASHBOARDS["changes"].widgets:
        if widget.report is not None:
            definition = widget.report
        else:
            definition = BUILTIN[(widget.report_ref or "").removeprefix("builtin:")].definition
        found[widget.id] = definition.model_dump(mode="json", by_alias=True, exclude_none=True)
    return found


async def _time(world: World, user: uuid.UUID, definition: dict[str, Any]) -> dict[str, float]:
    a = world.a
    body = {k: v for k, v in definition.items() if k != "entity"}
    seconds: list[float] = []
    for _ in range(RUNS + 1):
        started = time.perf_counter()
        response = await _run(world, a, user, **body)
        seconds.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
    return {"cold": round(seconds[0], 3), "median": round(statistics.median(seconds[1:]), 3)}


async def _explain(world: World, definition: dict[str, Any]) -> str:
    a = world.a
    database = world.app.state.db
    async with database.tenant_session(TenantContext(a.tenant, a.admin)) as session:
        source = await provider_for("change").source(
            session, await subject_for(session, a.tenant, a.admin)
        )
        from datetime import UTC, datetime  # noqa: PLC0415 - this helper only

        compiled = compile_report(
            ReportDefinition.model_validate(definition), source, now=datetime.now(UTC), zone="UTC"
        )
        sql = str(
            compiled.grouped.compile(
                dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]  # SQLAlchemy's dialect constructor is untyped
                compile_kwargs={"literal_binds": True},
            )
        )
        rows = await session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {sql}"))
        return "\n".join(str(r[0]) for r in rows)


@pytest.mark.timing
@pytest.mark.skipif(ROWS <= 0, reason="set SUPPORTX_CHANGE_REPORT_SCALE_ROWS to run it")
async def test_req_chg_116_the_changes_dashboard_at_volume(world: World) -> None:
    a = world.a
    started = time.perf_counter()
    await _load(world)
    print(f"loaded {ROWS} changes in {time.perf_counter() - started:.1f}s", flush=True)  # noqa: T201 - progress of a long run
    group_role = await role(
        world, a, "Changes of my groups", [("changes.view", "group"), ("reports.view", "all")]
    )
    await world.call("PUT", f"/users/{a.requester2}/roles/{group_role}", a, a.admin)
    await world.call("PUT", f"/organization/groups/{a.gb}/members/{a.requester2}", a, a.admin)
    measured: dict[str, dict[str, float]] = {}
    definitions = _definitions()
    for viewer, user in (("admin", a.admin), ("group_scope", a.requester2)):
        for code, definition in definitions.items():
            measured[f"{viewer}:{code}"] = await _time(world, user, definition)
            print(f"{viewer}:{code} {measured[f'{viewer}:{code}']}", flush=True)  # noqa: T201 - progress
    slowest = max(measured.items(), key=lambda item: item[1]["median"])
    print(f"slowest {slowest}", flush=True)  # noqa: T201 - the result of the check
    print(await _explain(world, definitions[slowest[0].split(":", 1)[1]]), flush=True)  # noqa: T201 - EXPLAIN for the PR
    timing.record("change_reports_at_volume", {"rows": ROWS, "slowest": slowest})
    bound = timing.limit(TARGET_SECONDS)
    over = {q: m["median"] for q, m in measured.items() if m["median"] > bound}
    assert not over, f"over {bound}s at {ROWS} changes: {over}"
