"""Report exports and report settings (WP-035 session 3). Test names cite parity file 09.

The incident world and the test-only incident provider of test_reports_api.py; object storage is
an in-memory fake (nothing touches the dev stack's MinIO); the worker's subject loader is the
API's own PolicyService.compile, which is what identity_access.subject_for runs (D-100, lane B).
"""

import csv
import io
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from openpyxl import load_workbook

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.analytics.api.routes import STORAGE_STATE
from app.modules.analytics.service.exports import Worker, build_export
from tests.db import test_reports_api
from tests.db.test_incidents_api import CONSOLE, Org, World
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db
world = test_reports_api.world
reports = test_reports_api.reports

OPEN = {"field": "status_category", "op": "in", "value": ["open", "paused"]}


class MemoryStorage:
    """ObjectStorage in a dict (the port's methods the export path uses)."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        self.files[key] = data

    async def put_stream(self, key: str, parts: AsyncIterator[bytes], content_type: str) -> int:
        del content_type
        data = b"".join([part async for part in parts])
        self.files[key] = data
        return len(data)

    async def get(self, key: str) -> bytes | None:
        return self.files.get(key)

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)

    async def check(self) -> None:
        return None

    async def read_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        yield self.files[key][start : end + 1]


@pytest_asyncio.fixture
async def exporting(reports: World) -> AsyncIterator[tuple[World, MemoryStorage]]:
    storage = MemoryStorage()
    setattr(reports.app.state, STORAGE_STATE, storage)
    try:
        yield reports, storage
    finally:
        setattr(reports.app.state, STORAGE_STATE, None)


async def _request(world: World, org: Any, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        "/reports/exports",
        org,
        user,
        json={"title": "Open incidents", "definition": {"entity": "incident"}, **body},
        headers=CONSOLE,
    )


async def _build(
    world: World, migrated_db: ThrowawayDatabase, storage: MemoryStorage, org: Org, export_id: str
) -> None:
    """What the consumers worker does for one requested export."""
    policy = world.app.state.policy
    database = Database(
        create_engine(migrated_db.app_url, application_name="t", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            await build_export(
                session,
                uuid.UUID(export_id),
                Worker(
                    reporting=database,
                    storage=storage,
                    load_subject=policy.compile,
                    render_pdf=None,
                    timeout_seconds=30,
                    max_rows=1000,
                    link_days=7,
                ),
            )
    finally:
        await database.dispose()


async def test_req_rpt_058_records_csv_holds_exactly_what_the_user_may_list(
    exporting: tuple[World, MemoryStorage], migrated_db: ThrowawayDatabase
) -> None:
    world, storage = exporting
    a = world.a
    await test_reports_api.seed(world)
    await world.create(a, a.admin, group_id=str(a.ga), subject='=HYPERLINK("http://x","y")')
    requested = await _request(
        world,
        a,
        a.tech_a,
        format="csv",
        content="records",
        definition={"entity": "incident", "filter": OPEN, "group_by": [{"field": "priority"}]},
    )
    assert requested.status_code == 202, requested.text
    export = requested.json()
    assert export["status"] == "running"
    await _build(world, migrated_db, storage, a, export["id"])

    listed = await world.call("GET", "/reports/exports", a, a.tech_a)
    mine = next(e for e in listed.json() if e["id"] == export["id"])
    assert mine["status"] == "ready", mine
    visible = await test_reports_api.listed(world, a, a.tech_a, OPEN)
    assert mine["row_count"] == len(visible)  # tech_a's scope (D-052), nothing more

    download = await world.call("GET", f"/reports/exports/{export['id']}/file", a, a.tech_a)
    assert download.status_code == 200, download.text
    assert download.content.startswith("﻿".encode())
    rows = list(csv.reader(io.StringIO(download.content.decode("utf-8-sig"))))
    table = rows[rows.index(next(r for r in rows if r and r[0] == "Priority")) :]
    ids = {r[1] for r in table[1:]}
    assert len(ids) == len(visible)
    subjects = [r[2] for r in table[1:]]
    assert '\'=HYPERLINK("http://x","y")' in subjects  # neutralised (D-100)
    assert not any(s.startswith("=") for s in subjects)
    assert not any(r[0] in {"p1", "p2", "p3", "p4"} for r in table[1:])  # labels, never codes

    # Only the person who asked can download it.
    other = await world.call("GET", f"/reports/exports/{export['id']}/file", a, a.tech_b)
    assert other.status_code == 404
    audit = await world.sql(
        "SELECT action, details FROM audit_entries WHERE tenant_id = $1 AND action LIKE 'report.%'",
        a.tenant,
    )
    actions = {r["action"] for r in audit}
    assert {"report.exported", "report.export_downloaded"} <= actions
    exported = next(r for r in audit if r["action"] == "report.exported")
    assert '"rows": ' + str(len(visible)) in str(exported["details"]).replace("'", '"')


async def test_req_rpt_058_ac1_xlsx_summary_and_records_with_totals(
    exporting: tuple[World, MemoryStorage], migrated_db: ThrowawayDatabase
) -> None:
    world, storage = exporting
    a = world.a
    await test_reports_api.seed(world)
    requested = await _request(
        world,
        a,
        a.lead,
        format="xlsx",
        content="records",
        language="ar",
        definition={"entity": "incident", "group_by": [{"field": "status_category"}]},
    )
    assert requested.status_code == 202, requested.text
    await _build(world, migrated_db, storage, a, requested.json()["id"])
    data = (
        await world.call("GET", f"/reports/exports/{requested.json()['id']}/file", a, a.lead)
    ).content
    workbook = load_workbook(io.BytesIO(data))
    summary, records = workbook.worksheets
    assert summary.sheet_view.rightToLeft is True
    values = [[c.value for c in row] for row in summary.iter_rows()]
    total = values[-1]
    assert total[1] == 6  # every incident of org A, a number not text
    assert isinstance(total[1], int)
    assert records.max_row - 6 == 6  # header lines + blank + header, then six records


async def test_exports_need_permission_and_storage(exporting: tuple[World, MemoryStorage]) -> None:
    world, _storage = exporting
    a = world.a
    refused = await _request(world, a, a.requester, format="csv")
    assert refused.status_code == 403
    setattr(world.app.state, STORAGE_STATE, None)
    no_storage = await _request(world, a, a.tech_a, format="csv")
    assert no_storage.status_code == 503
    assert no_storage.json()["code"] == "storage_not_configured"


async def test_pdf_without_the_worker_image_fails_visibly(
    exporting: tuple[World, MemoryStorage], migrated_db: ThrowawayDatabase
) -> None:
    world, storage = exporting
    a = world.a
    requested = await _request(world, a, a.tech_a, format="pdf")
    await _build(world, migrated_db, storage, a, requested.json()["id"])
    mine = (await world.call("GET", "/reports/exports", a, a.tech_a)).json()[0]
    assert (mine["status"], mine["problem"]) == ("failed", "pdf_not_available")
    events = await world.sql(
        "SELECT id FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'analytics.report_export.finished'",
        a.tenant,
    )
    assert events  # the person who asked is told live (REQ-RPT-056)


async def test_d041_report_settings_are_editable_by_admins_and_shape_weeks(reports: World) -> None:
    world = reports
    a = world.a
    got = await world.call("GET", "/reports/settings", a, a.tech_a)
    assert got.status_code == 200, got.text
    assert got.json()["week_start"] == "monday"
    assert got.json()["interactive_timeout_seconds"] == 30
    version = got.json()["version"]
    refused = await world.call(
        "PATCH",
        "/reports/settings",
        a,
        a.tech_a,
        json={"week_start": "sunday"},
        headers={**CONSOLE, "If-Match": f'"{version}"'},
    )
    assert refused.status_code == 403
    changed = await world.call(
        "PATCH",
        "/reports/settings",
        a,
        a.admin,
        json={"week_start": "sunday", "export_link_days": 3},
        headers={**CONSOLE, "If-Match": f'"{version}"'},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["week_start"] == "sunday"
    stale = await world.call(
        "PATCH",
        "/reports/settings",
        a,
        a.admin,
        json={"export_link_days": 5},
        headers={**CONSOLE, "If-Match": f'"{version}"'},
    )
    assert stale.status_code == 409
    out_of_range = await world.call(
        "PATCH",
        "/reports/settings",
        a,
        a.admin,
        json={"interactive_timeout_seconds": 600},
        headers={**CONSOLE, "If-Match": f'"{changed.json()["version"]}"'},
    )
    assert out_of_range.status_code == 422

    # A Wednesday incident counts in the week that starts on the Sunday before it.
    item = await world.create(a, a.admin)
    await world.sql(
        "UPDATE work_items SET created_at = '2026-10-21T10:00:00+00' WHERE id = $1",
        uuid.UUID(item["id"]),
    )
    weeks = await test_reports_api.ran(
        world,
        a,
        a.admin,
        filter={
            "field": "created_at",
            "op": "between",
            "value": ["2026-10-18T00:00:00Z", "2026-10-25T00:00:00Z"],
        },
        group_by=[{"field": "created_at", "bucket": "week"}],
    )
    assert [r["keys"][0][:10] for r in weeks["rows"]] == ["2026-10-18"]  # a Sunday
    audit = await world.sql(
        "SELECT outcome FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'report.settings_changed'",
        a.tenant,
    )
    # The change, and the three refusals (permission, stale version, out of range), are audited.
    assert sorted(r["outcome"] for r in audit).count("done") == 1
    assert len(audit) == 4
