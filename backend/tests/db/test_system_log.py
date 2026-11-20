"""The system log (WP-057 S5b, REQ-AUD-016; 0187; the coordinator's conditions).

- Per tenant (RLS) and append-only by grants: the app role can neither update nor delete; rows
  leave only through `system_log_purge()`, which takes the tenant's own retention (never under
  30 days) and reaches only the tenant set in the transaction (AC2).
- Modules write through the public `record_system` / `record_system_alone`; an entry is a code
  with small params, never free text, and every write raises its outbox event.
- The screen's list and the CSV export give the same rows for the same filters (AC3); the CSV
  is in the reader's language and neutralises formula cells.
"""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.audit import (
    SystemLogCode,
    SystemLogEntryIn,
    SystemLogObject,
    SystemLogSeverity,
    record_system,
    record_system_alone,
)
from app.modules.audit.domain.system_log import SystemLogProblem
from app.modules.audit.service import system_log
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

LOG = "/audit/system-log"


def _failed_check(mailbox: uuid.UUID, reason: str = "auth_failed") -> SystemLogEntryIn:
    return SystemLogEntryIn(
        module="integrations",
        code=SystemLogCode.MAILBOX_CHECK_FAILED,
        severity=SystemLogSeverity.ERROR,
        params={"reason": reason},
        about=SystemLogObject("mailbox", mailbox),
        job_id="mail-poll-1",
    )


async def _count(world: World, tenant: uuid.UUID, code: str | None = None) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM system_log_entries WHERE tenant_id = $1"
        " AND ($2::text IS NULL OR code = $2)",
        tenant,
        code,
    )
    return int(rows[0]["n"])


async def test_a_failed_mailbox_check_is_logged_and_links_to_the_mailbox(world: World) -> None:
    """AC1: the entry names the mailbox, so the screen links to it; its event goes out."""
    mailbox = uuid.uuid4()
    written = await record_system_alone(world.app.state.db, world.a.tenant, _failed_check(mailbox))
    assert written is not None
    found = await world.call(
        "GET", f"{LOG}?object_type=mailbox&object_id={mailbox}", world.a, user=world.a.admin
    )
    assert found.status_code == 200, found.text
    [item] = found.json()["items"]
    assert item["code"] == "integrations.mailbox.check_failed"
    assert item["severity"] == "error"
    assert (item["object_type"], item["object_id"]) == ("mailbox", str(mailbox))
    assert item["params"] == {"reason": "auth_failed"}
    events = await world.sql(
        "SELECT envelope->'payload' AS payload FROM outbox_events WHERE tenant_id = $1"
        " AND envelope->>'aggregate_id' = $2"
        " AND envelope->>'event_type' = 'audit.system_log.recorded'",
        world.a.tenant,
        str(written),
    )
    assert len(events) == 1
    assert "mailbox" not in str(events[0]["payload"])  # the severity only (rule c)


async def test_append_only_for_the_app_and_isolated_per_tenant(world: World) -> None:
    """AC2 and rule a: no UPDATE or DELETE right; B never sees or purges A's rows."""
    await record_system_alone(world.app.state.db, world.a.tenant, _failed_check(uuid.uuid4()))
    before = await _count(world, world.a.tenant)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        for statement in (
            "UPDATE system_log_entries SET severity = 'info'",
            "DELETE FROM system_log_entries",
        ):
            with pytest.raises(DBAPIError):  # no UPDATE or DELETE right at all
                async with session.begin_nested():
                    await session.execute(text(statement))
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        seen = await session.scalar(
            text("SELECT count(*) FROM system_log_entries WHERE tenant_id = :a"),
            {"a": world.a.tenant},
        )
        assert seen == 0
        with pytest.raises(DBAPIError):  # nor write one for A
            async with session.begin_nested():
                await session.execute(
                    text(
                        "INSERT INTO system_log_entries (id, tenant_id, occurred_at, severity,"
                        " module, code) VALUES (gen_random_uuid(), :a, now(), 'info', 'audit',"
                        " 'audit.retention.archived')"
                    ),
                    {"a": world.a.tenant},
                )
        assert await session.scalar(text("SELECT system_log_purge()")) == 0
    listed = await world.call("GET", LOG, world.b, user=world.b.admin)
    assert all(i["job_id"] != "mail-poll-1" for i in listed.json()["items"])
    assert await _count(world, world.a.tenant) == before


async def test_the_purge_keeps_everything_inside_retention(world: World) -> None:
    """The app passes no cut-off: 90 days by default, the tenant's own when set, never < 30."""
    tenant = world.a.tenant
    now = datetime.now(UTC)
    ages = {"old": 200, "middle": 60, "young": 10}
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        for name, days in ages.items():
            await record_system(
                session,
                SystemLogEntryIn(
                    module="audit",
                    code=SystemLogCode.AUDIT_RETENTION_ARCHIVED,
                    severity=SystemLogSeverity.INFO,
                    params={"month": name},
                ),
                now=now - timedelta(days=days),
            )

    async def months() -> set[str]:
        rows = await world.sql(
            "SELECT params->>'month' AS m FROM system_log_entries WHERE tenant_id = $1"
            " AND code = 'audit.retention.archived' AND params ? 'month'",
            tenant,
        )
        return {r["m"] for r in rows} & set(ages)

    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        assert await system_log.purge(session) >= 1  # 90 days: "old" goes
    assert await months() == {"middle", "young"}
    # The tenant's own period (30 days): "middle" goes too; "young" never does.
    await world.sql(
        "INSERT INTO audit_settings (tenant_id, retention_days, read_window_minutes,"
        " refusal_threshold, refusal_window_minutes, read_categories, system_log_retention_days)"
        " VALUES ($1, 1095, 10, 10, 10, '[]'::jsonb, 30)"
        " ON CONFLICT (tenant_id) DO UPDATE SET system_log_retention_days = 30",
        tenant,
    )
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        await system_log.purge(session)
    assert await months() == {"young"}
    # The database refuses a period under 30 days, whatever the app sends.
    with pytest.raises(Exception, match="system_log_retention_range"):
        await world.sql(
            "UPDATE audit_settings SET system_log_retention_days = 7 WHERE tenant_id = $1", tenant
        )


async def test_the_export_is_the_screens_rows_in_words(world: World) -> None:
    """AC3: the same filters give the same rows; codes in words; formula cells neutralised."""
    mailbox = uuid.uuid4()
    for reason in ("timeout", "=HYPERLINK(1)"):
        await record_system_alone(
            world.app.state.db, world.a.tenant, _failed_check(mailbox, reason)
        )
    query = f"severity=error&object_type=mailbox&object_id={mailbox}"
    screen = await world.call("GET", f"{LOG}?{query}", world.a, user=world.a.admin)
    exported = await world.call(
        "GET", f"{LOG}/export?{query}&language=en", world.a, user=world.a.admin
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(exported.text.lstrip("﻿"))))
    header, body = rows[0], rows[1:]
    assert len(body) == len(screen.json()["items"]) == 2
    assert [r[0] for r in body] == [
        datetime.fromisoformat(i["occurred_at"]).isoformat() for i in screen.json()["items"]
    ]
    assert "integrations.mailbox.check_failed" not in exported.text  # never the code
    assert "error" not in [r[1] for r in body]  # the severity in words
    assert header[0] != "occurred_at"
    assert all(not cell.startswith(("=", "+", "-", "@")) for r in body for cell in r)
    arabic = await world.call(
        "GET", f"{LOG}/export?{query}&language=ar", world.a, user=world.a.admin
    )
    assert arabic.text != exported.text


async def test_reading_needs_audit_view_and_exporting_audit_export(world: World) -> None:
    for user in (world.a.tech_a, world.a.lead):
        refused = await world.call("GET", LOG, world.a, user=user)
        assert refused.status_code in {403, 404}, refused.text
        refused = await world.call("GET", f"{LOG}/export", world.a, user=user)
        assert refused.status_code in {403, 404}, refused.text


async def test_paging_walks_every_row_once(world: World) -> None:
    job = f"page-{uuid.uuid4().hex[:8]}"
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        stamp = datetime.now(UTC)
        for n in range(5):
            await record_system(
                session,
                SystemLogEntryIn(
                    module="audit",
                    code=SystemLogCode.AUDIT_EXPORT_FAILED,
                    severity=SystemLogSeverity.WARNING,
                    params={"n": n},
                    job_id=job,
                ),
                now=stamp,  # the same time: the ID breaks the tie
            )
    seen: list[str] = []
    after = None
    for _ in range(10):
        query = "code=audit.export.failed&limit=2" + (f"&after={quote(after)}" if after else "")
        page = (await world.call("GET", f"{LOG}?{query}", world.a, user=world.a.admin)).json()
        seen += [i["id"] for i in page["items"] if i["job_id"] == job]
        after = page["next_after"]
        if after is None:
            break
    assert len(seen) == len(set(seen)) == 5


def test_a_writer_cannot_log_free_text_or_another_modules_code() -> None:
    with pytest.raises(SystemLogProblem):  # another module's code
        SystemLogEntryIn(
            module="files",
            code=SystemLogCode.MAILBOX_CHECK_FAILED,
            severity=SystemLogSeverity.ERROR,
        )
    with pytest.raises(SystemLogProblem):  # long text in a param
        SystemLogEntryIn(
            module="files",
            code=SystemLogCode.FILES_SCAN_FAILED,
            severity=SystemLogSeverity.ERROR,
            params={"detail": "x" * 500},
        )
    with pytest.raises(SystemLogProblem):  # a structure in a param
        SystemLogEntryIn(
            module="files",
            code=SystemLogCode.FILES_SCAN_FAILED,
            severity=SystemLogSeverity.ERROR,
            params={"detail": {"a": 1}},  # type: ignore[dict-item]  # what the check refuses
        )
    with pytest.raises(SystemLogProblem):  # a name the label renderer takes itself
        SystemLogEntryIn(
            module="files",
            code=SystemLogCode.FILES_SCAN_FAILED,
            severity=SystemLogSeverity.ERROR,
            params={"language": "en"},
        )


async def test_a_burst_of_refused_mail_writes_one_entry_per_reason(world: World) -> None:
    """Lane A's conditions: refused e-mails coalesce per reason per hour, with the refusal's
    code only (never an address); the caller's transaction goes on."""
    from app.modules.notifications.service.engine import _log_refused  # noqa: PLC0415
    from app.shared.mail.domain.message import MailRefused  # noqa: PLC0415

    tenant = world.b.tenant
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        for reason in ("too_many_recipients",) * 5 + ("subject_too_long",) * 3:
            await _log_refused(session, MailRefused(code=reason))
        assert await session.scalar(text("SELECT 1")) == 1  # the transaction is still usable
    rows = await world.sql(
        "SELECT params->>'reason' AS reason, params::text AS raw FROM system_log_entries"
        " WHERE tenant_id = $1 AND code = 'notifications.mail.refused' ORDER BY reason",
        tenant,
    )
    assert [r["reason"] for r in rows] == ["subject_too_long", "too_many_recipients"]
    assert all("@" not in r["raw"] for r in rows)
