"""Scheduled reports (WP-035 session 4, D-100 D3). Test names cite parity file 09.

The incident world of test_reports_api.py (the real incident source). Mail goes through the real
mail foundation (app.shared.mail) into `mail_messages`; nothing connects to a mail server. The
worker's run is called directly with identity_access.subject_for, as the consumers worker does.
"""

import csv
import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.analytics.service.exports import SubjectLoader, Worker
from app.modules.analytics.service.schedules import enqueue_due, run_schedule
from app.modules.identity_access import mail_recipients, subject_for
from tests.db import test_report_exports, test_reports_api
from tests.db.test_incidents_api import CONSOLE, Org, World
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db
world = test_reports_api.world
reports = test_reports_api.reports

OPEN = {"field": "status_category", "op": "in", "value": ["open", "paused"]}


@pytest_asyncio.fixture
async def mailing(reports: World) -> AsyncIterator[tuple[World, Settings]]:
    """The world with outgoing mail set up (the mail catcher's address, never contacted)."""
    original: Settings = reports.app.state.settings
    configured = original.model_copy(
        update={"mail_smtp_host": "127.0.0.1", "mail_from_address": "reports@supportx.test"}
    )
    reports.app.state.settings = configured
    try:
        yield reports, configured
    finally:
        reports.app.state.settings = original


def _body(org: Org, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {
        "title": "Open incidents",
        "report_ref": "builtin:incidents_open_by_priority",
        "frequency": "weekly",
        "at_time": "07:00",
        "time_zone": "Asia/Riyadh",
        "start_date": "2026-10-01",
        "weekdays": [0],
        "recipient_users": [str(org.tech_a)],
        "recipient_groups": [str(org.gb)],
        "format": "csv",
        **extra,
    }


async def _run_due(
    world: World,
    migrated_db: ThrowawayDatabase,
    org: Org,
    settings: Settings,
    load_subject: SubjectLoader = subject_for,
) -> None:
    """What the minute sweep and the consumers worker do, with the clock a week ahead."""
    database = Database(
        create_engine(migrated_db.app_url, application_name="t", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            await enqueue_due(session, datetime.now(UTC) + timedelta(days=8))
        due = await world.sql(
            "SELECT aggregate_id FROM outbox_events"
            " WHERE tenant_id = $1 AND event_type = 'analytics.report_schedule.due'",
            org.tenant,
        )
        ids = {row["aggregate_id"] for row in due}
        for schedule_id in ids:
            async with database.tenant_session(TenantContext(org.tenant)) as session:
                await run_schedule(
                    session,
                    uuid.UUID(str(schedule_id)),
                    Worker(
                        reporting=database,
                        storage=None,
                        load_subject=load_subject,
                        render_pdf=None,
                        timeout_seconds=30,
                        max_rows=1000,
                        link_days=7,
                    ),
                    settings,
                )
    finally:
        await database.dispose()


async def test_req_rpt_055_without_mail_a_schedule_cannot_be_made(reports: World) -> None:
    world = reports
    a = world.a
    listed = await world.call("GET", "/reports/schedules", a, a.admin)
    assert listed.json() == {"mail_configured": False, "items": []}
    refused = await world.call(
        "POST", "/reports/schedules", a, a.admin, json=_body(a), headers=CONSOLE
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "mail_not_configured"


async def test_req_rpt_053_each_recipient_gets_their_own_scope_and_language(
    mailing: tuple[World, Settings], migrated_db: ThrowawayDatabase
) -> None:
    world, settings = mailing
    a = world.a
    await test_reports_api.seed(world)
    await world.sql("UPDATE users SET locale = 'ar' WHERE id = $1", a.tech_b)
    tech = await world.call(
        "POST", "/reports/schedules", a, a.tech_a, json=_body(a), headers=CONSOLE
    )
    assert tech.status_code == 403  # reports.schedule is for administrators by default
    made = await world.call(
        "POST", "/reports/schedules", a, a.admin, json=_body(a), headers=CONSOLE
    )
    assert made.status_code == 201, made.text
    schedule = made.json()
    next_run = datetime.fromisoformat(schedule["next_run_at"])
    assert next_run.astimezone(UTC).weekday() == 0  # Monday
    assert next_run.astimezone(UTC).hour == 4  # 07:00 in Riyadh

    await _run_due(world, migrated_db, a, settings)

    mails = await world.sql(
        "SELECT m.recipients, m.language, m.subject, a.content FROM mail_messages m"
        " JOIN mail_attachments a ON a.message_id = m.id"
        " WHERE m.tenant_id = $1 AND m.kind = 'report'",
        a.tenant,
    )
    by_person = {m["recipients"][0]: m for m in mails}
    emails = {
        r["id"]: r["email"]
        for r in await world.sql(
            "SELECT id, email FROM users WHERE id = ANY($1::uuid[])", [a.tech_a, a.tech_b, a.tech_c]
        )
    }
    assert set(by_person) == {emails[a.tech_a], emails[a.tech_b], emails[a.tech_c]}  # user + GB
    assert by_person[emails[a.tech_b]]["language"] == "ar"
    assert by_person[emails[a.tech_a]]["language"] == "en"

    def total(content: bytes) -> str:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        return rows[-1][-1]

    for person in (a.tech_a, a.tech_b):
        visible = await test_reports_api.listed(world, a, person, OPEN)
        assert total(by_person[emails[person]]["content"]) == str(len(visible))  # their own scope
    listed = (await world.call("GET", "/reports/schedules", a, a.admin)).json()
    item = listed["items"][0]
    assert (item["last_result"], item["last_sent"], item["last_failed"]) == ("sent", 3, 0)


async def test_req_rpt_056_failures_are_recorded_and_pause_the_schedule(
    mailing: tuple[World, Settings], migrated_db: ThrowawayDatabase
) -> None:
    world, settings = mailing
    a = world.a
    saved = await world.call(
        "POST",
        "/reports",
        a,
        a.admin,
        json={"name": "Mine", "definition": {"entity": "incident"}},
        headers=CONSOLE,
    )
    made = await world.call(
        "POST",
        "/reports/schedules",
        a,
        a.admin,
        json=_body(a, report_ref=saved.json()["id"]),
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    await world.call(
        "DELETE",
        f"/reports/{saved.json()['id']}",
        a,
        a.admin,
        headers={**CONSOLE, "If-Match": f'"{saved.json()["version"]}"'},
    )
    await _run_due(world, migrated_db, a, settings)
    item = (await world.call("GET", "/reports/schedules", a, a.admin)).json()["items"][0]
    assert (item["status"], item["paused_reason"], item["last_result"]) == (
        "paused",
        "report_removed",
        "report_removed",
    )
    events = await world.sql(
        "SELECT 1 FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'analytics.report_schedule.ran'",
        a.tenant,
    )
    assert events  # the owner is told live (personal channel)
    resumed = await world.call(
        "POST",
        f"/reports/schedules/{item['id']}/resume",
        a,
        a.admin,
        headers={**CONSOLE, "If-Match": f'"{item["version"]}"'},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "active"


async def test_schedule_validation_names_each_problem(mailing: tuple[World, Settings]) -> None:
    world, _settings = mailing
    a = world.a
    bad = await world.call(
        "POST",
        "/reports/schedules",
        a,
        a.admin,
        json=_body(
            a,
            weekdays=[],
            recipient_users=[str(uuid.uuid4())],
            recipient_groups=[],
            report_ref="builtin:nope",
            time_zone="Mars/Base",
        ),
        headers=CONSOLE,
    )
    assert bad.status_code == 422
    codes = {e["field"]: e["code"] for e in bad.json()["errors"]}
    assert codes == {
        "body.weekdays": "one_day_required",
        "body.time_zone": "invalid_choice",
        "body.recipient_users": "unknown_recipient",
        "body.report_ref": "report_not_found",
    }


async def test_mail_recipients_active_users_with_an_address_in_their_language(
    reports: World, migrated_db: ThrowawayDatabase
) -> None:
    world = reports
    a = world.a
    await world.sql("UPDATE users SET locale = 'ar', ui_locale = NULL WHERE id = $1", a.tech_a)
    await world.sql("UPDATE users SET status = 'disabled' WHERE id = $1", a.tech_b)
    await world.sql("UPDATE users SET deleted_at = now() WHERE id = $1", a.tech_c)
    await world.sql("UPDATE users SET email = NULL WHERE id = $1", a.requester)
    database = Database(
        create_engine(migrated_db.app_url, application_name="t", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            found = await mail_recipients(
                session, [a.tech_a, a.tech_b, a.tech_c, a.requester, a.lead, uuid.uuid4()]
            )
    finally:
        await database.dispose()
    assert set(found) == {a.tech_a, a.lead}
    assert found[a.tech_a].language == "ar"
    assert found[a.lead].language == "en"


async def test_report_schedules_table_is_isolated_by_rls(mailing: tuple[World, Settings]) -> None:
    world, _settings = mailing
    a, b = world.a, world.b
    made = await world.call(
        "POST", "/reports/schedules", a, a.admin, json=_body(a), headers=CONSOLE
    )
    assert made.status_code == 201, made.text
    schedule_id = uuid.UUID(made.json()["id"])
    listed = await world.call("GET", "/reports/schedules", b, b.admin)
    assert listed.json()["items"] == []
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (
            await session.execute(
                text("SELECT id FROM report_schedules WHERE id = :id"), {"id": schedule_id}
            )
        ).all()
        assert rows == []
        updated = await session.execute(
            text("UPDATE report_schedules SET status = 'paused' WHERE id = :id"),
            {"id": schedule_id},
        )
        assert updated.rowcount == 0
    foreign = await world.call(
        "POST",
        f"/reports/schedules/{schedule_id}/pause",
        b,
        b.admin,
        headers={**CONSOLE, "If-Match": '"1"'},
    )
    assert foreign.status_code == 404
    mine = (await world.call("GET", "/reports/schedules", a, a.admin)).json()["items"][0]
    assert mine["status"] == "active"


async def test_req_rpt_056_a_worker_missing_a_service_records_a_failed_run(
    mailing: tuple[World, Settings], migrated_db: ThrowawayDatabase
) -> None:
    world, settings = mailing
    a = world.a
    made = await world.call(
        "POST", "/reports/schedules", a, a.admin, json=_body(a), headers=CONSOLE
    )
    assert made.status_code == 201, made.text
    await _run_due(
        world, migrated_db, a, settings, load_subject=test_report_exports.no_entitlements
    )
    item = (await world.call("GET", "/reports/schedules", a, a.admin)).json()["items"][0]
    # Recorded (counts towards the pause after 3), not dead-lettered unseen.
    assert (item["status"], item["last_result"], item["last_sent"]) == (
        "active",
        "report_failed",
        0,
    )
    assert item["last_run_at"] is not None
