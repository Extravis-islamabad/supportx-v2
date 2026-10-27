"""Reports over HTTP (WP-035). Test names cite parity file 09 criteria.

Real PostgreSQL and Valkey, the incident world of tests/db/test_incidents_api.py (orgs Alpha and
Beta, technicians with the D-052 `group` scope). Until lane A's incident reporting provider lands
(WP-029 PR, D-100 D9), a test-only provider registers the incident list query exactly as the list
endpoint builds it: `staff_rows` plus the list's filter fields.
"""

import json
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules import metadata
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service.access import FIELDS
from app.modules.work_items.service.work_items import staff_rows
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.reporting import (
    Dimension,
    DimensionKind,
    ReportingSource,
    register_source,
    unregister_source,
)
from tests.db import test_incidents_api
from tests.db.test_custom_fields_api import add_field, choices
from tests.db.test_incidents_api import BASE, CONSOLE, World
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

RUN = "/reports/run"
_D = DimensionKind
DIMENSIONS: Mapping[str, Dimension] = {
    "priority": Dimension(_D.CODE, label_prefix="priority"),
    "status_category": Dimension(_D.CODE, label_prefix="status_category"),
    "channel": Dimension(_D.CODE, label_prefix="work_item_channel"),
    "impact": Dimension(_D.CODE, label_prefix="impact"),
    "urgency": Dimension(_D.CODE, label_prefix="urgency"),
    "status": Dimension(_D.ADMIN_CODE),
    "level": Dimension(_D.ADMIN_CODE),
    "group_id": Dimension(_D.REFERENCE, reference="group"),
    "site_id": Dimension(_D.REFERENCE, reference="site"),
    "department_id": Dimension(_D.REFERENCE, reference="department"),
    "technician_id": Dimension(_D.REFERENCE, reference="user"),
    "requester_id": Dimension(_D.REFERENCE, reference="user"),
    "category_id": Dimension(_D.REFERENCE, reference="category"),
    "created_at": Dimension(_D.DATETIME),
    "resolved_at": Dimension(_D.DATETIME),
    "reopen_count": Dimension(_D.NUMBER),
    "reassignment_count": Dimension(_D.NUMBER),
}
EXTRA_FIELDS = {
    "first_responded_at": FilterField(
        WorkItem.first_responded_at, FieldType.DATETIME, sortable=True, simple=False
    ),
    "paused_seconds": FilterField(WorkItem.paused_seconds, FieldType.INTEGER),
    "department_id": FilterField(WorkItem.department_id, FieldType.UUID),
}


class IncidentTestProvider:
    """What lane A's provider will register (D-100 D9), built from the list's own pieces."""

    entity = "incident"
    feature = "incident"
    permission = "incidents.view"

    async def source(self, session: AsyncSession, subject: Any) -> ReportingSource:  # noqa: ANN401 - Subject
        custom = await metadata.filter_fields(session, "incident", "work_items")
        fields = ResourceFields(
            FIELDS.name, {**FIELDS.fields, **EXTRA_FIELDS, **custom}, FIELDS.id_column
        )
        dimensions = dict(DIMENSIONS)
        for name, spec in custom.items():
            if spec.type == FieldType.ENUM:
                dimensions[name] = Dimension(_D.ADMIN_CODE)
        return ReportingSource(
            entity="incident",
            rows=staff_rows(subject, INCIDENT),
            fields=fields,
            dimensions=dimensions,
            list_path="incidents",
        )


@pytest_asyncio.fixture
async def reports(world: World) -> AsyncIterator[World]:
    """The incident world with the incident reporting source registered."""
    register_source(IncidentTestProvider())
    try:
        yield world
    finally:
        unregister_source("incident")


async def run(world: World, org: Any, user: uuid.UUID, **definition: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    zone = definition.pop("_zone", "UTC")
    return await world.call(
        "POST",
        RUN,
        org,
        user,
        json={"definition": {"entity": "incident", **definition}},
        headers={**CONSOLE, "X-Time-Zone": zone},
    )


async def ran(world: World, org: Any, user: uuid.UUID, **definition: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    response = await run(world, org, user, **definition)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def listed(world: World, org: Any, user: uuid.UUID, tree: Any) -> set[str]:  # noqa: ANN401 - JSON
    query = "?" + str(httpx.QueryParams({"filter": json.dumps(tree)})) if tree else ""
    response = await world.call("GET", f"{BASE}{query}&limit=100" if query else BASE, org, user)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


def by_key(result: Mapping[str, Any]) -> dict[Any, list[Any]]:
    return {
        tuple(r["keys"]) if len(r["keys"]) > 1 else r["keys"][0]: r["values"]
        for r in result["rows"]
    }


async def seed(world: World) -> None:
    """Org A: incidents in groups GA and GB, at sites S1 and S2, and unassigned; one in org B."""
    a = world.a
    await world.create(a, a.admin, group_id=str(a.ga))  # S1 requester
    await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    await world.create(a, a.admin, group_id=str(a.gb), requester_id=str(a.requester2))
    await world.create(
        a, a.admin, group_id=str(a.gb), technician_id=str(a.tech_b), requester_id=str(a.requester2)
    )
    await world.create(a, a.admin)  # S1 site queue: tech_a sees it (D-052)
    await world.create(a, a.admin, requester_id=str(a.requester2))  # S2 queue: tech_a does not
    await world.create(world.b, world.b.admin)  # another tenant: never counted


# --- REQ-RPT-002 / D-052: a report counts exactly what the viewer could list ---------------------


async def test_req_rpt_002_report_list_and_drill_down_agree_for_every_scope(reports: World) -> None:
    world = reports
    a = world.a
    await seed(world)
    for user in (a.admin, a.lead, a.tech_a, a.tech_b, a.tech_c):
        result = await ran(world, a, user, group_by=[{"field": "group_id"}])
        visible = await listed(world, a, user, None)
        assert result["totals"] == [len(visible)], user
        for row in result["rows"]:
            assert len(await listed(world, a, user, row["drill"])) == row["values"][0], row
        assert sum(r["values"][0] for r in result["rows"]) == len(visible)


async def test_req_rpt_002_ac2_one_report_different_totals_per_scope(reports: World) -> None:
    world = reports
    a = world.a
    await seed(world)
    lead = await ran(world, a, a.lead)  # incidents.view at `all`
    tech_a = await ran(world, a, a.tech_a)  # group GA + own + S1 queue
    assert lead["totals"] == [6]  # all of org A, nothing of org B
    assert tech_a["totals"] == [3]  # two in GA, the S1 queue


async def test_req_rpt_001_ac3_other_tenants_rows_never_count(reports: World) -> None:
    world = reports
    await seed(world)
    result = await ran(world, world.b, world.b.admin)
    assert result["totals"] == [1]


async def test_reporting_role_reads_only_its_tenant_cannot_write_and_is_cancelled(
    reports: World, migrated_db: ThrowawayDatabase
) -> None:
    world = reports
    await seed(world)
    database = Database(
        create_engine(migrated_db.app_url, application_name="t", use_null_pool=True)
    )
    try:
        context = TenantContext(tenant_id=world.b.tenant)
        async with database.reporting_session(context, timeout_seconds=5) as rs:
            assert (await rs.scalar(text("SELECT current_user"))) == "supportx_report"
            assert (await rs.scalar(text("SELECT count(*) FROM work_items"))) == 1
        with pytest.raises(DBAPIError, match="read-only"):
            async with database.reporting_session(context, timeout_seconds=5) as rs:
                await rs.execute(text("UPDATE work_items SET subject = 'x'"))
        with pytest.raises(DBAPIError, match="permission denied"):
            async with database.reporting_session(context, timeout_seconds=5) as rs:
                await rs.execute(text("SELECT count(*) FROM users"))  # not granted
        with pytest.raises(DBAPIError) as caught:
            async with database.reporting_session(context, timeout_seconds=0.2) as rs:
                await rs.execute(text("SELECT pg_sleep(2)"))
        assert getattr(caught.value.orig, "sqlstate", None) == "57014"  # statement timeout
    finally:
        await database.dispose()


# --- REQ-RPT-004, 013, 015: measures, custom fields, built-in reports -----------------------------


async def test_req_rpt_004_measures_and_req_rpt_015_ac3_ageing(reports: World) -> None:
    world = reports
    a = world.a
    await seed(world)
    await world.sql(
        "UPDATE work_items SET created_at = now() - interval '4 days' WHERE tenant_id = $1"
        " AND group_id = $2",
        a.tenant,
        a.gb,
    )
    ageing = await ran(
        world,
        a,
        a.admin,
        filter={"field": "status_category", "op": "in", "value": ["open", "paused"]},
        group_by=[{"field": "created_at", "bucket": "age"}],
    )
    assert by_key(ageing) == {"under_1_day": [4], "3_to_7_days": [2]}
    for row in ageing["rows"]:
        assert len(await listed(world, a, a.admin, row["drill"])) == row["values"][0]
    measures = await ran(
        world, a, a.admin, measures=["count", "open_count", "unassigned_open_count"]
    )
    assert measures["totals"] == [6, 6, 2]
    assert [m["code"] for m in measures["measures"]] == [
        "count",
        "open_count",
        "unassigned_open_count",
    ]


async def test_req_rpt_013_ac1_new_pick_list_groups_a_report_at_once(reports: World) -> None:
    world = reports
    a = world.a
    await add_field(
        world, a, field_type="choice", labels={"en": "Floor"}, choices=choices("Ground", "First")
    )
    await world.create(a, a.admin, custom={"floor": "first"})
    await world.create(a, a.admin, custom={"floor": "first"})
    await world.create(a, a.admin, custom={"floor": "ground"})
    await world.create(a, a.admin)
    result = await ran(world, a, a.admin, group_by=[{"field": "custom.floor"}])
    assert by_key(result) == {"first": [2], "ground": [1], None: [1]}
    assert result["groups"][0]["kind"] == "admin_code"


async def test_req_dsh_044_ac1_days_in_the_viewers_zone(reports: World) -> None:
    world = reports
    a = world.a
    item = await world.create(a, a.admin)
    await world.sql(
        "UPDATE work_items SET created_at = '2026-10-20T23:30:00+00' WHERE id = $1",
        uuid.UUID(item["id"]),
    )
    body = {
        "filter": {
            "field": "created_at",
            "op": "between",
            "value": ["2026-10-19T00:00:00Z", "2026-10-23T00:00:00Z"],
        },
        "group_by": [{"field": "created_at", "bucket": "day"}],
    }
    utc = await ran(world, a, a.admin, **body)
    karachi = await ran(world, a, a.admin, _zone="Asia/Karachi", **body)
    assert [r["keys"][0][:10] for r in utc["rows"]] == ["2026-10-20"]
    assert [r["keys"][0][:10] for r in karachi["rows"]] == ["2026-10-21"]
    assert karachi["time_zone"] == "Asia/Karachi"
    assert len(await listed(world, a, a.admin, karachi["rows"][0]["drill"])) == 1


async def test_req_rpt_015_ac1_builtin_reports_listed_and_run_without_setup(reports: World) -> None:
    world = reports
    a = world.a
    await seed(world)
    library = await world.call("GET", "/reports/library", a, a.tech_a)
    assert library.status_code == 200, library.text
    builtin = library.json()["builtin"]
    assert len(builtin) >= 20
    for report in builtin:
        response = await world.call(
            "POST", RUN, a, a.tech_a, json={"definition": report["definition"]}, headers=CONSOLE
        )
        assert response.status_code == 200, (report["code"], response.text)


# --- REQ-RPT-019, 045, 048: saved reports, folders, permissions ----------------------------------


async def test_req_rpt_019_copy_private_then_share_through_a_folder(reports: World) -> None:
    world = reports
    a = world.a
    library = (await world.call("GET", "/reports/library", a, a.tech_a)).json()
    original = next(r for r in library["builtin"] if r["code"] == "incidents_open_by_priority")
    definition = dict(original["definition"])
    definition["filter"] = {
        "and": [definition["filter"], {"field": "site_id", "op": "eq", "value": str(a.s1)}]
    }
    saved = await world.call(
        "POST",
        "/reports",
        a,
        a.tech_a,
        json={"name": "Open at S1", "definition": definition, "copied_from": original["code"]},
        headers={**CONSOLE, "Idempotency-Key": "copy-1"},
    )
    assert saved.status_code == 201, saved.text
    report = saved.json()
    assert report["folder_id"] is None
    assert report["can_edit"] is True
    # Private: nobody else sees it (REQ-RPT-047 AC1 default).
    assert (await world.call("GET", f"/reports/{report['id']}", a, a.tech_b)).status_code == 404
    # The built-in one is untouched: still the same definition in the library.
    again = (await world.call("GET", "/reports/library", a, a.tech_a)).json()
    assert next(r for r in again["builtin"] if r["code"] == original["code"]) == original
    # A technician may not create folders (REQ-RPT-048); an admin may.
    denied = await world.call(
        "POST", "/reports/folders", a, a.tech_a, json={"name": "Team"}, headers=CONSOLE
    )
    assert denied.status_code == 403
    folder = await world.call(
        "POST", "/reports/folders", a, a.admin, json={"name": "Team"}, headers=CONSOLE
    )
    assert folder.status_code == 201, folder.text
    moved = await world.call(
        "PATCH",
        f"/reports/{report['id']}",
        a,
        a.tech_a,
        json={"folder_id": folder.json()["id"]},
        headers={**CONSOLE, "If-Match": f'"{report["version"]}"'},
    )
    assert moved.status_code == 200, moved.text
    shared = await world.call("GET", f"/reports/{report['id']}", a, a.tech_b)
    assert shared.status_code == 200
    assert shared.json()["can_edit"] is False
    refused = await world.call(
        "PATCH",
        f"/reports/{report['id']}",
        a,
        a.tech_b,
        json={"name": "Mine now"},
        headers={**CONSOLE, "If-Match": f'"{moved.json()["version"]}"'},
    )
    assert refused.status_code == 403
    stale = await world.call(
        "PATCH",
        f"/reports/{report['id']}",
        a,
        a.tech_a,
        json={"name": "Stale"},
        headers={**CONSOLE, "If-Match": f'"{report["version"]}"'},
    )
    assert stale.status_code == 409
    # Deleting the folder needs a destination for its reports (REQ-RPT-045 AC3).
    fid = folder.json()["id"]
    no_choice = await world.call(
        "DELETE", f"/reports/folders/{fid}", a, a.admin, headers={**CONSOLE, "If-Match": '"1"'}
    )
    assert no_choice.status_code == 422
    gone = await world.call(
        "DELETE",
        f"/reports/folders/{fid}?move_to=owners",
        a,
        a.admin,
        headers={**CONSOLE, "If-Match": '"1"'},
    )
    assert gone.status_code == 204, gone.text
    assert (await world.call("GET", f"/reports/{report['id']}", a, a.tech_b)).status_code == 404
    events = await world.sql(
        "SELECT event_type FROM outbox_events"
        " WHERE tenant_id = $1 AND event_type LIKE 'analytics.%'",
        a.tenant,
    )
    assert {e["event_type"] for e in events} >= {
        "analytics.report.saved",
        "analytics.report_folder.saved",
        "analytics.report_folder.deleted",
    }


async def test_saving_an_invalid_definition_is_refused(reports: World) -> None:
    world = reports
    a = world.a
    bad = await world.call(
        "POST",
        "/reports",
        a,
        a.tech_a,
        json={"name": "x", "definition": {"entity": "incident", "group_by": [{"field": "secret"}]}},
        headers=CONSOLE,
    )
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["code"] == "unknown_dimension"


async def test_req_rpt_048_requesters_cannot_run_reports_and_favourites_work(
    reports: World,
) -> None:
    world = reports
    a = world.a
    assert (await run(world, a, a.requester)).status_code == 403
    star = await world.call("PUT", "/reports/favourites/builtin:incidents_all", a, a.tech_a)
    assert star.status_code == 204, star.text
    unknown = await world.call("PUT", "/reports/favourites/builtin:nope", a, a.tech_a)
    assert unknown.status_code == 404
    library = (await world.call("GET", "/reports/library", a, a.tech_a)).json()
    assert library["favourites"] == ["builtin:incidents_all"]
    assert (
        await world.call("DELETE", "/reports/favourites/builtin:incidents_all", a, a.tech_a)
    ).status_code == 204
    assert (await world.call("GET", "/reports/library", a, a.tech_a)).json()["favourites"] == []


async def test_rename_folder_edit_definition_and_delete_a_report(reports: World) -> None:
    world = reports
    a = world.a
    folder = await world.call(
        "POST", "/reports/folders", a, a.admin, json={"name": "Ops"}, headers=CONSOLE
    )
    assert folder.status_code == 201, folder.text
    fid = folder.json()["id"]
    duplicate = await world.call(
        "POST", "/reports/folders", a, a.admin, json={"name": "ops"}, headers=CONSOLE
    )
    assert duplicate.status_code == 422
    renamed = await world.call(
        "PATCH",
        f"/reports/folders/{fid}",
        a,
        a.admin,
        json={"name": "Operations"},
        headers={**CONSOLE, "If-Match": '"1"'},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Operations"
    saved = await world.call(
        "POST",
        "/reports",
        a,
        a.tech_a,
        json={"name": "Mine", "folder_id": fid, "definition": {"entity": "incident"}},
        headers=CONSOLE,
    )
    assert saved.status_code == 201, saved.text
    report = saved.json()
    edited = await world.call(
        "PATCH",
        f"/reports/{report['id']}",
        a,
        a.tech_a,
        json={"definition": {"entity": "incident", "group_by": [{"field": "priority"}]}},
        headers={**CONSOLE, "If-Match": f'"{report["version"]}"'},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["definition"]["group_by"] == [{"field": "priority", "bucket": None}]
    star = await world.call("PUT", f"/reports/favourites/{report['id']}", a, a.tech_a)
    assert star.status_code == 204
    # Deleting a folder into another folder keeps its reports shared there.
    other = await world.call(
        "POST", "/reports/folders", a, a.admin, json={"name": "Archive"}, headers=CONSOLE
    )
    moved = await world.call(
        "DELETE",
        f"/reports/folders/{fid}?move_to={other.json()['id']}",
        a,
        a.admin,
        headers={**CONSOLE, "If-Match": f'"{renamed.json()["version"]}"'},
    )
    assert moved.status_code == 204, moved.text
    current = await world.call("GET", f"/reports/{report['id']}", a, a.tech_b)
    assert current.json()["folder_id"] == other.json()["id"]
    gone = await world.call(
        "DELETE",
        f"/reports/{report['id']}",
        a,
        a.tech_a,
        headers={**CONSOLE, "If-Match": f'"{current.json()["version"]}"'},
    )
    assert gone.status_code == 204, gone.text
    assert (await world.call("GET", f"/reports/{report['id']}", a, a.tech_a)).status_code == 404
    library = (await world.call("GET", "/reports/library", a, a.tech_a)).json()
    assert report["id"] not in library["favourites"]  # the star went with the report
    history = await world.sql(
        "SELECT kind FROM field_changes WHERE record_type = 'report' AND record_id = $1"
        " ORDER BY occurred_at",
        uuid.UUID(report["id"]),
    )
    assert [h["kind"] for h in history][:1] == ["created"]
    assert "deleted" in {h["kind"] for h in history}
