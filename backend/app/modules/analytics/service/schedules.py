"""Scheduled reports by e-mail (REQ-RPT-052 to 056; D-100 D3: minimal at MVP).

- Built-in or saved reports, daily / chosen weekdays / weekly / monthly at a wall-clock time in
  a time zone, from a start date to an optional end date (domain/schedule.py).
- Recipients are users and groups of the tenant. Each recipient gets their own file, built
  with *their* permissions and in *their* language (REQ-RPT-053 AC1, REQ-DSH-045 AC2); external
  addresses are V1 (D-100 D3).
- Sent only through the mail foundation (app.shared.mail, D-089): never a second sender. When
  mail is not set up, schedules cannot be created and the form says why (REQ-RPT-055).
- Never silent (REQ-RPT-056): every run records its result on the schedule and tells the owner
  live; three failed runs in a row pause it (Appendix A). An owner who loses
  `reports.schedule` has their schedules paused at the next run (REQ-RPT-048 AC3).

Runs: a housekeeping schedule (`analytics__report_schedules`, every minute) finds due schedules
per tenant, moves their next run on and emits `analytics.report_schedule.due`; the consumers
worker builds and mails the files.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as time_type
from html import escape
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import (
    AppError,
    Conflict,
    FieldError,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules import organization
from app.modules.analytics.domain.builtin import BUILTIN, BUILTIN_PREFIX
from app.modules.analytics.domain.definition import ReportDefinition
from app.modules.analytics.domain.schedule import FAILURES_BEFORE_PAUSE, Frequency, Recurrence
from app.modules.analytics.events import ReportScheduleDue, ReportScheduleRan, ReportScheduleSaved
from app.modules.analytics.infra.models import ReportSchedule
from app.modules.analytics.service import library
from app.modules.analytics.service.exports import (
    CONTENT_TYPES,
    Worker,
    fail_stalled_exports,
    render_file,
)
from app.modules.identity_access import Subject, mail_recipients
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes, stale_version
from app.shared.labels import html_label, label, plain_label
from app.shared.mail import (
    MAX_ATTACHMENT_BYTES,
    Attachment,
    Language,
    MailBrand,
    MailNotConfigured,
    MailRefused,
    OutgoingMail,
    mail_configured,
    queue_mail,
    wrap_html,
)

log = get_logger(__name__)
SCHEDULE = "reports.schedule"
SEE_ALL = "settings.manage"
RECORD_TYPE = "report_schedule"
MAX_USERS = 50
MAX_GROUPS = 20
MAX_RECIPIENTS = 200  # after groups are expanded
DUE_BATCH = 50
FILE_NAMES = {"csv": "report.csv", "xlsx": "report.xlsx", "pdf": "report.pdf"}


class ScheduleRepository(Repository[ReportSchedule]):
    """Report schedules of the session's tenant."""

    model = ReportSchedule


@dataclass(frozen=True)
class ScheduleInput:
    """What the owner sets (all fields on create; the given ones on update)."""

    title: str
    report_ref: str
    frequency: Frequency
    at_time: time_type
    time_zone: str
    start_date: date
    end_date: date | None
    weekdays: tuple[int, ...]
    day_of_month: int | None
    recipient_users: tuple[uuid.UUID, ...]
    recipient_groups: tuple[uuid.UUID, ...]
    format: str
    content: str
    message: str | None


def _error(field_name: str, code: str) -> FieldError:
    return FieldError(field=f"body.{field_name}", code=code, message_key=f"errors.field.{code}")


def recurrence_of(row: ReportSchedule) -> Recurrence:
    """The timing of a stored schedule."""
    return Recurrence(
        frequency=Frequency(row.frequency),
        at=row.at_time,
        zone=row.time_zone,
        start=row.start_date,
        end=row.end_date,
        weekdays=tuple(row.weekdays or ()),
        day_of_month=row.day_of_month,
    )


async def definition_of(
    session: AsyncSession, subject: Subject, report_ref: str
) -> tuple[ReportDefinition, str] | None:
    """The report a schedule sends, as `subject` may open it: (definition, title), or None."""
    if report_ref.startswith(BUILTIN_PREFIX):
        builtin = BUILTIN.get(report_ref.removeprefix(BUILTIN_PREFIX))
        return (builtin.definition, builtin.code) if builtin else None
    try:
        found = await library.get_report(session, subject, uuid.UUID(report_ref))
    except (ValueError, NotFound):
        return None
    return ReportDefinition.model_validate(found.record.definition), found.record.name


async def _check(session: AsyncSession, subject: Subject, values: ScheduleInput) -> None:
    errors: list[FieldError] = []
    recurrence = Recurrence(
        values.frequency,
        values.at_time,
        values.time_zone,
        values.start_date,
        values.end_date,
        values.weekdays,
        values.day_of_month,
    )
    errors += [_error(name, code) for name, code in recurrence.problems()]
    if not values.recipient_users and not values.recipient_groups:
        errors.append(_error("recipient_users", "recipients_required"))
    if len(values.recipient_users) > MAX_USERS or len(values.recipient_groups) > MAX_GROUPS:
        errors.append(_error("recipient_users", "too_many_recipients"))
    known = await mail_recipients(session, list(values.recipient_users))
    if any(u not in known for u in values.recipient_users):
        errors.append(_error("recipient_users", "unknown_recipient"))
    groups = await organization.existing_unit_ids(session, "group", list(values.recipient_groups))
    if any(g not in groups for g in values.recipient_groups):
        errors.append(_error("recipient_groups", "unknown_recipient"))
    if await definition_of(session, subject, values.report_ref) is None:
        errors.append(_error("report_ref", "report_not_found"))
    if values.format not in CONTENT_TYPES:
        errors.append(_error("format", "invalid_choice"))
    if errors:
        raise ValidationFailed(errors=errors)


def _snapshot(row: ReportSchedule) -> dict[str, Any]:
    return {
        "title": row.title,
        "report_ref": row.report_ref,
        "frequency": row.frequency,
        "at_time": row.at_time.isoformat(),
        "time_zone": row.time_zone,
        "weekdays": list(row.weekdays or ()),
        "day_of_month": row.day_of_month,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "recipient_users": list(row.recipient_users),
        "recipient_groups": list(row.recipient_groups),
        "format": row.format,
        "content": row.content,
        "message": row.message,
        "status": row.status,
    }


def _apply(row: ReportSchedule, values: ScheduleInput) -> None:
    row.title = values.title.strip()
    row.report_ref = values.report_ref
    row.frequency = values.frequency.value
    row.at_time = values.at_time
    row.time_zone = values.time_zone
    row.start_date = values.start_date
    row.end_date = values.end_date
    row.weekdays = list(values.weekdays)
    row.day_of_month = values.day_of_month
    row.recipient_users = [str(u) for u in values.recipient_users]
    row.recipient_groups = [str(g) for g in values.recipient_groups]
    row.format = values.format
    row.content = values.content
    row.message = (values.message or "").strip() or None


def _require(subject: Subject, settings: Settings) -> None:
    if not subject.holds(SCHEDULE):
        raise PermissionDenied(params={"permission": SCHEDULE})
    if not mail_configured(settings):
        raise Conflict(code="mail_not_configured")


async def _saved(
    session: AsyncSession, row: ReportSchedule, before: Mapping[str, Any], source: Source
) -> None:
    after = _snapshot(row)
    changes = [Change(k, before.get(k), v) for k, v in after.items() if before.get(k) != v]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created" if not before else "updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        ReportScheduleSaved(
            schedule_id=row.id,
            owner_id=row.owner_id,
            status=row.status,
            changed_fields=[c.field for c in changes],
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_schedule(
    session: AsyncSession,
    subject: Subject,
    values: ScheduleInput,
    *,
    settings: Settings,
    source: Source,
) -> ReportSchedule:
    """A new active schedule owned by `subject`."""
    _require(subject, settings)
    await _check(session, subject, values)
    row = ReportSchedule(owner_id=subject.user_id, status="active", failures=0)
    _apply(row, values)
    row.next_run_at = recurrence_of(row).next_after(datetime.now(UTC))
    if row.next_run_at is None:
        raise ValidationFailed(errors=[_error("end_date", "schedule_never_runs")])
    await ScheduleRepository(session).add(row)
    await _saved(session, row, {}, source)
    return row


def _may_manage(subject: Subject, row: ReportSchedule) -> bool:
    return row.owner_id == subject.user_id or subject.holds(SEE_ALL)


async def get_schedule(
    session: AsyncSession, subject: Subject, schedule_id: uuid.UUID
) -> ReportSchedule:
    """A schedule the subject owns (or any, for administrators); 404 otherwise."""
    row = await session.scalar(
        select(ReportSchedule).where(
            ReportSchedule.id == schedule_id, ReportSchedule.deleted_at.is_(None)
        )
    )
    if row is None or not _may_manage(subject, row):
        raise NotFound(code="report_schedule_not_found")
    return row


async def list_schedules(session: AsyncSession, subject: Subject) -> list[ReportSchedule]:
    """The subject's schedules (every schedule for administrators), next run first."""
    query = select(ReportSchedule).where(ReportSchedule.deleted_at.is_(None))
    if not subject.holds(SEE_ALL):
        query = query.where(ReportSchedule.owner_id == subject.user_id)
    return list(
        await session.scalars(
            query.order_by(ReportSchedule.next_run_at.asc().nulls_last(), ReportSchedule.id)
        )
    )


async def update_schedule(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    schedule_id: uuid.UUID,
    values: ScheduleInput,
    *,
    expected_version: int,
    settings: Settings,
    source: Source,
) -> ReportSchedule:
    """Replace the schedule's settings (If-Match); timing changes move the next run."""
    _require(subject, settings)
    row = await get_schedule(session, subject, schedule_id)
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    await _check(session, subject, values)
    before = _snapshot(row)
    _apply(row, values)
    if row.status == "active":
        row.next_run_at = recurrence_of(row).next_after(datetime.now(UTC))
    row.version += 1
    await session.flush()
    await _saved(session, row, before, source)
    return row


async def set_paused(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    schedule_id: uuid.UUID,
    *,
    paused: bool,
    expected_version: int,
    source: Source,
) -> ReportSchedule:
    """Pause, or resume (which clears the failure count and plans the next run)."""
    row = await get_schedule(session, subject, schedule_id)
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    before = _snapshot(row)
    if paused:
        row.status, row.paused_reason = "paused", "paused_by_owner"
    else:
        if not subject.holds(SCHEDULE):
            raise PermissionDenied(params={"permission": SCHEDULE})
        row.next_run_at = recurrence_of(row).next_after(datetime.now(UTC))
        row.status = "active" if row.next_run_at else "finished"
        row.paused_reason, row.failures = None, 0
    row.version += 1
    await session.flush()
    await _saved(session, row, before, source)
    return row


async def delete_schedule(
    session: AsyncSession,
    subject: Subject,
    schedule_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Delete (soft): it never runs again."""
    row = await get_schedule(session, subject, schedule_id)
    await ScheduleRepository(session).soft_delete(row.id, expected_version=expected_version)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version + 1,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        ReportScheduleSaved(
            schedule_id=row.id, owner_id=row.owner_id, status="deleted", changed_fields=[]
        ),
        aggregate_id=row.id,
    )


# --- runs --------------------------------------------------------------------------------------


async def due_sweep(database: Database, settings: Settings) -> None:
    """Every minute: hand each due schedule to the worker, plan its next run, fail lost exports."""
    # An export running longer than every allowed attempt could take was lost (worker crash).
    stalled = datetime.now(UTC) - timedelta(
        seconds=settings.report_background_timeout_seconds * settings.consumer_max_attempts + 60
    )
    async with database.platform_session() as platform:
        # Every tenant: the platform function other modules' schedules use too (audit, mail).
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            await enqueue_due(session, datetime.now(UTC))
            await fail_stalled_exports(session, stalled)


async def enqueue_due(session: AsyncSession, now: datetime) -> int:
    """Emit `due` for every active schedule whose time came; returns how many."""
    rows = list(
        await session.scalars(
            select(ReportSchedule)
            .where(
                ReportSchedule.status == "active",
                ReportSchedule.deleted_at.is_(None),
                ReportSchedule.next_run_at <= now,
            )
            .order_by(ReportSchedule.next_run_at)
            .limit(DUE_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        run_at = row.next_run_at or now
        row.next_run_at = recurrence_of(row).next_after(now)
        if row.next_run_at is None:
            row.status = "finished"  # REQ-RPT-052 AC3: it ends after its end date
        await record_event(
            session, ReportScheduleDue(schedule_id=row.id, run_at=run_at), aggregate_id=row.id
        )
    await session.flush()
    return len(rows)


@dataclass(frozen=True)
class _Copy:
    """One recipient's file of a scheduled report (a FileSpec for render_file)."""

    tenant_id: uuid.UUID
    requested_by: uuid.UUID
    title: str
    definition: dict[str, Any]
    format: str
    content: str
    language: str
    time_zone: str


@dataclass
class _Outcome:
    sent: int = 0
    failed: int = 0
    problems: list[str] = field(default_factory=list)


def _mail(  # noqa: PLR0913 - the message's parts, keyword-only
    row: ReportSchedule,
    *,
    title: str,
    language: Language,
    data: bytes,
    brand: MailBrand,
    to: str,
) -> OutgoingMail:
    # Mail: no directional marks in the subject or plain text; <bdi> in the HTML part.
    subject_line = plain_label("reports.mail_subject", language, title=title)
    intro = plain_label("reports.mail_intro", language, title=title)
    intro_html = html_label("reports.mail_intro", language, title=title)
    note = row.message or ""
    content = f"<p>{intro_html}</p>" + (f"<p>{escape(note)}</p>" if note else "")
    return OutgoingMail(
        kind="report",
        to=(to,),
        language=language,
        subject=subject_line,
        text=f"{intro}\n\n{note}".strip(),
        html=wrap_html(content, brand=brand, language=language, title=subject_line),
        attachments=(
            Attachment(FILE_NAMES[row.format], CONTENT_TYPES[row.format].split(";")[0], data),
        ),
    )


async def _owner(session: AsyncSession, row: ReportSchedule, worker: Worker) -> Subject | str:
    """The owner's permissions now, or the problem that stops the run."""
    if worker.load_subject is None:
        return "owner_not_allowed"
    try:
        owner = await worker.load_subject(session, row.tenant_id, row.owner_id)
    except AppError as error:
        # Retrying will not bring a missing service back; record the run as failed instead of
        # letting it dead-letter unseen, so failures count towards pausing (REQ-RPT-056).
        log.error("report_subject_unavailable", code=error.code)  # noqa: TRY400 - code only
        return "report_failed"
    return owner if owner.holds(SCHEDULE) else "owner_not_allowed"


async def run_schedule(  # noqa: C901 - one run, every outcome explicit
    session: AsyncSession, schedule_id: uuid.UUID, worker: Worker, settings: Settings
) -> ReportSchedule | None:
    """Send one run: a file per recipient, as that recipient sees the report."""
    row = await session.get(ReportSchedule, schedule_id, with_for_update=True)
    if row is None or row.deleted_at is not None:
        return row
    outcome = _Outcome()
    problem: str | None = None
    owner = await _owner(session, row, worker)
    if isinstance(owner, str):
        return await _ran(session, row, outcome, owner, pause=owner == "owner_not_allowed")
    if not mail_configured(settings):
        return await _ran(session, row, outcome, "mail_not_configured")
    report = await definition_of(session, owner, row.report_ref)
    if report is None:
        return await _ran(session, row, outcome, "report_removed", pause=True)
    definition, title_key = report
    group_ids = frozenset(uuid.UUID(g) for g in row.recipient_groups)
    members = (
        list(await session.scalars(organization.users_in_groups(group_ids))) if group_ids else []
    )
    wanted = list(dict.fromkeys([uuid.UUID(u) for u in row.recipient_users] + members))
    recipients = await mail_recipients(session, wanted[:MAX_RECIPIENTS])
    if not recipients:
        return await _ran(session, row, outcome, "no_recipients")
    brands: dict[str, Any] = {}
    for user_id, recipient in recipients.items():
        language = recipient.language
        title = (
            label(f"report.{title_key}", language)
            if row.report_ref.startswith(BUILTIN_PREFIX)
            else title_key
        )
        copy = _Copy(
            tenant_id=row.tenant_id,
            requested_by=user_id,
            title=row.title or title,
            definition=definition.model_dump(mode="json", by_alias=True),
            format=row.format,
            content=row.content,
            language=language,
            time_zone=row.time_zone,
        )
        rendered = await render_file(session, copy, worker)
        if isinstance(rendered, str):
            outcome.failed += 1
            outcome.problems.append(rendered)
            continue
        path, _rows = rendered
        try:
            data = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)
        if len(data) > MAX_ATTACHMENT_BYTES:
            outcome.failed += 1  # V1: a sign-in link instead (REQ-RPT-054)
            outcome.problems.append("attachment_too_large")
            continue
        if language not in brands:
            brands[language] = await organization.email_branding(
                session, settings, row.tenant_id, language
            )
        mail = _mail(
            row,
            title=copy.title,
            language=language,
            data=data,
            brand=brands[language],
            to=recipient.email,
        )
        try:
            await queue_mail(session, settings, mail)
        except (MailNotConfigured, MailRefused) as error:
            outcome.failed += 1
            outcome.problems.append(getattr(error, "code", "mail_refused"))
            continue
        outcome.sent += 1
    if outcome.sent == 0:
        problem = outcome.problems[0] if outcome.problems else "no_recipients"
    return await _ran(session, row, outcome, problem)


async def _ran(
    session: AsyncSession,
    row: ReportSchedule,
    outcome: _Outcome,
    problem: str | None,
    *,
    pause: bool = False,
) -> ReportSchedule:
    """Record the run on the schedule, pause it when needed, and tell the owner live."""
    row.last_run_at = datetime.now(UTC)
    row.last_sent, row.last_failed = outcome.sent, outcome.failed
    row.last_result = problem or "sent"
    if problem is None:
        row.failures = 0
    else:
        row.failures = (row.failures or 0) + 1
        if pause or row.failures >= FAILURES_BEFORE_PAUSE:
            row.status = "paused"
            row.paused_reason = problem if pause else "too_many_failures"
        log.warning("report_schedule_failed", schedule_id=str(row.id), problem=problem)
    await session.flush()
    await record_event(
        session,
        ReportScheduleRan(
            schedule_id=row.id,
            owner_id=row.owner_id,
            result=row.last_result,
            sent=outcome.sent,
            failed=outcome.failed,
            paused=row.status == "paused",
        ),
        aggregate_id=row.id,
    )
    return row
