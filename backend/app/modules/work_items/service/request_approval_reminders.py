"""Request approval reminders and escalation (WP-047a S3a; REQ-SR-034, REQ-SR-036 AC2).

Every five minutes, in every tenant (app.tenant_id set, RLS), the sweep looks at each pending
approval of a running service request and works out its plan (`domain/approval_reminders`): the
reminders on working days at the tenant's time of day in the approver's time zone, then one
escalation as the stage says. The latest slot that has come is acted on:

- a reminder re-sends the approval's "opened" event, so the notice goes out again with a fresh
  link (as the manual reminder does, REQ-SR-042), and the record's history says so;
- an escalation adds the stage's target next to the primary approver, who keeps their row (036
  AC2); the family's first decision settles it. Nobody to escalate to: the administrators,
  recorded (the coordinator's condition 2).

The coordinator's condition 5: claim-once and idempotent (a `processed_events` row per approval,
step and number; an escalation's rows are its proof as well), capped per run (`MAX_ACTIONS`;
the rest wait for the next run, oldest first). Reminders stop when the stage is decided, since
only pending rows are read (AC3), and while a clarification is open (REQ-SR-037 AC3).
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import exists, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules import organization, service_catalog, sla
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import record as record_audit
from app.modules.identity_access import notifiable_people, person_placement
from app.modules.work_items.domain import approval_reminders as plans
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain import stage_snapshot
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.infra.models import (
    ApprovalClarification,
    WorkItem,
    WorkItemApproval,
    WorkItemTypeSettings,
)
from app.modules.work_items.service import request_stages
from app.modules.work_items.service.approval_stage import approval_event, requested_for
from app.modules.work_items.service.followers import RECORD_TYPE
from app.shared.clock import Clock, SystemClock
from app.shared.events.outbox import ProcessedEvent
from app.shared.history import Change, record_changes

log = get_logger(__name__)

CONSUMER = "request_approval_reminders"
EVERY_SECONDS = 300
MAX_ACTIONS = 200  # reminders and escalations per tenant per run (condition 5)
SCAN_MAX = 5000  # pending approvals read per run, oldest first
REMINDER_FIELD = "approval_reminder_sent"  # history, apart from the manual reminder's count
ESCALATED_FIELD = "approval_escalated"
ESCALATED = "service_request.approval_escalated"
_NAMESPACE = uuid.UUID("2f0c9a1e-6b47-5d3a-8e21-047a53a00000")


def claim_key(approval_id: uuid.UUID, step: plans.Step, number: int) -> uuid.UUID:
    """The one-time key of a slot: the approval, the step and its number."""
    return uuid.uuid5(_NAMESPACE, f"{approval_id}|{step.value}|{number}")


async def _claim(session: AsyncSession, key: uuid.UUID) -> bool:
    """True the first time `key` is claimed in this tenant; False ever after (until purged)."""
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    claimed = await session.scalar(
        insert(ProcessedEvent)
        .values(tenant_id=tenant, consumer=CONSUMER, event_id=key)
        .on_conflict_do_nothing()
        .returning(ProcessedEvent.event_id)
    )
    return claimed is not None


async def schedule_of(session: AsyncSession) -> plans.Schedule:
    """The tenant's schedule for request approvals (Appendix A's when none is stored)."""
    row = (
        await session.execute(
            select(
                WorkItemTypeSettings.approval_reminder_after_days,
                WorkItemTypeSettings.approval_reminder_count,
                WorkItemTypeSettings.approval_reminder_minute,
            ).where(WorkItemTypeSettings.type == SERVICE_REQUEST.code.value)
        )
    ).one_or_none()
    if row is None:
        return plans.Schedule()
    after, count, minute = row
    return plans.Schedule(after, count, time(minute // 60, minute % 60))


async def _working_day(session: AsyncSession) -> Callable[[date], bool]:
    """The tenant's operating hours as "is this a working day" (the coordinator's Q4)."""
    calendar = await sla.calendar_for_maths(
        session, await sla.system_calendar_id(session, sla.SystemCalendar.OPERATING_HOURS)
    )
    if calendar.counts_everything:
        return lambda _day: True
    return lambda day: bool(calendar.day_intervals(day))


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


async def _zones(session: AsyncSession, people: Sequence[uuid.UUID]) -> dict[uuid.UUID, ZoneInfo]:
    """Each approver's time zone: their own, else the tenant's, else UTC."""
    fallback = _zone((await organization.regional_defaults(session, None)).time_zone)
    found = await notifiable_people(session, people)
    utc = ZoneInfo("UTC")
    return {p: _zone(found[p].time_zone if p in found else None) or fallback or utc for p in people}


async def _pending(session: AsyncSession) -> list[tuple[WorkItem, WorkItemApproval]]:
    """Pending, named approvals of running requests, with no open clarification, oldest first."""
    clarifying = exists().where(
        ApprovalClarification.approval_id == WorkItemApproval.id,
        ApprovalClarification.ended_at.is_(None),
        ApprovalClarification.deleted_at.is_(None),
    )
    rows = await session.execute(
        select(WorkItem, WorkItemApproval)
        .join(WorkItemApproval, WorkItemApproval.work_item_id == WorkItem.id)
        .where(
            WorkItem.type == SERVICE_REQUEST.code.value,
            WorkItem.deleted_at.is_(None),
            WorkItem.status_category.in_([StatusCategory.OPEN.value, StatusCategory.PAUSED.value]),
            WorkItem.approval_status == ApprovalStatus.PENDING.value,
            WorkItemApproval.deleted_at.is_(None),
            WorkItemApproval.state == rules.ApprovalState.PENDING.value,
            WorkItemApproval.purpose == rules.ApprovalPurpose.RECORD.value,
            WorkItemApproval.record_stage.is_(None),
            WorkItemApproval.approver_id.is_not(None),
            ~clarifying,
        )
        .order_by(WorkItemApproval.created_at, WorkItemApproval.id)
        .limit(SCAN_MAX)
    )
    return [(r[0], r[1]) for r in rows.all()]


async def _escalated_primaries(session: AsyncSession, record_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The approvals already escalated (their escalated rows are the durable proof)."""
    if not record_ids:
        return set()
    found = await session.scalars(
        select(WorkItemApproval.escalated_from_id).where(
            WorkItemApproval.work_item_id.in_(record_ids),
            WorkItemApproval.escalated_from_id.is_not(None),
            WorkItemApproval.deleted_at.is_(None),
        )
    )
    return {f for f in found if f is not None}


async def stage_config(
    session: AsyncSession, record: WorkItem, number: int
) -> tuple[plans.EscalateTo, uuid.UUID | None]:
    """Where stage `number` escalates to, and its backup.

    A staged request reads its snapshot; today's single stage reads its item, as approvals do.
    """
    if record.approval_stages is not None:
        stages = stage_snapshot.from_json(record.approval_stages)
        if 0 < number <= len(stages):
            stage = stages[number - 1]
            return plans.EscalateTo(stage.escalate_to), stage.backup_id
        return plans.DEFAULT_ESCALATE_TO, None
    item = (
        await service_catalog.item_decides(session, record.catalog_item_id)
        if record.catalog_item_id is not None
        else None
    )
    if item is None:
        return plans.DEFAULT_ESCALATE_TO, None
    if item.stages and 0 < number <= len(item.stages):
        spec = item.stages[number - 1]
        return plans.EscalateTo(spec.escalate_to), spec.backup_id
    return plans.DEFAULT_ESCALATE_TO, item.backup_id


async def _targets(
    session: AsyncSession,
    record: WorkItem,
    row: WorkItemApproval,
    to: plans.EscalateTo,
    backup: uuid.UUID | None,
) -> list[uuid.UUID]:
    """The people an escalation adds: eligible, never the request's people or its holders."""
    wanted: list[uuid.UUID] = []
    if to is plans.EscalateTo.BACKUP and backup is not None:
        wanted = [backup]
    elif to is plans.EscalateTo.APPROVER_MANAGER and row.approver_id is not None:
        manager = (await person_placement(session, row.approver_id)).manager_id
        wanted = [manager] if manager is not None else []
    elif to is plans.EscalateTo.FULFILMENT_GROUP and record.group_id is not None:
        wanted = await request_stages.group_members(session, record.group_id)
    holding = {
        r.approver_id
        for r in await request_stages.rows_of(session, record)
        if r.stage == row.stage and r.state == rules.ApprovalState.PENDING
    }
    left_out = {record.requester_id, requested_for(record), *holding}
    candidates = [p for p in dict.fromkeys(wanted) if p not in left_out]
    eligible = await request_stages.eligible(session, set(candidates))
    return [p for p in candidates if eligible.get(p)]


def _like(row: WorkItemApproval, person: uuid.UUID | None, *, fallback: bool) -> WorkItemApproval:
    """A pending row next to `row`: the same stage, escalated from it."""
    return WorkItemApproval(
        tenant_id=row.tenant_id,
        work_item_id=row.work_item_id,
        stage=row.stage,
        rule=row.rule,
        branch=row.branch,
        approver_id=person,
        origin=(
            rules.ApproverOrigin.ADMINISTRATORS if fallback else rules.ApproverOrigin.ESCALATED
        ).value,
        route_reason=rules.RouteReason.NO_ESCALATION_TARGET.value if fallback else None,
        state=rules.ApprovalState.PENDING.value,
        self_approval=False,  # never the requester (S2a condition 2)
        comments_required=row.comments_required,
        purpose=rules.ApprovalPurpose.RECORD.value,
        escalated_from_id=row.id,
    )


async def _history(
    session: AsyncSession, record: WorkItem, field: str, said: dict[str, Any]
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_changed",
        changes=[Change(field, None, said)],
        source="rule",
        subtype=record.type,
    )


async def remind(
    session: AsyncSession, record: WorkItem, row: WorkItemApproval, number: int
) -> None:
    """Send the n-th reminder: the "opened" event again (a fresh link), recorded."""
    await approval_event(session, record, row, "opened")
    await _history(
        session,
        record,
        REMINDER_FIELD,
        {"stage": row.stage, "number": number, "approver_id": str(row.approver_id)},
    )


async def escalate(
    session: AsyncSession, record: WorkItem, row: WorkItemApproval
) -> list[WorkItemApproval]:
    """Add the stage's escalation target next to `row`; the administrators when nobody."""
    to, backup = await stage_config(session, record, row.stage)
    people = await _targets(session, record, row, to, backup)
    added = (
        [_like(row, p, fallback=False) for p in people]
        if people
        else [_like(row, None, fallback=True)]
    )
    session.add_all(added)
    record.version += 1  # rule 5g: the record's approvals changed
    record.updated_at = datetime.now(UTC)
    record.updated_by = None
    await session.flush()
    for new in added:
        await approval_event(session, record, new, "opened")
    said = {
        "stage": row.stage,
        "to": to.value,
        "from_id": str(row.approver_id),
        "count": len(people),
        "fallback": not people,
    }
    await _history(session, record, ESCALATED_FIELD, said)
    await record_audit(
        session,
        action_code=ESCALATED,
        facts=AUDIT_WORKER,
        object_type="service_request",
        object_id=str(record.id),
        details={
            "display_id": record.display_id,
            **said,
            "people": [str(p) for p in people],
        },
    )
    return added


async def sweep(session: AsyncSession, clock: Clock) -> int:
    """Act on every slot due now in this tenant, each once; how many reminders and escalations."""
    pending = await _pending(session)
    if not pending:
        return 0
    now = clock.now()
    schedule = await schedule_of(session)
    working_day = await _working_day(session)
    zones = await _zones(
        session, list(dict.fromkeys(r.approver_id for _, r in pending if r.approver_id))
    )
    escalated = await _escalated_primaries(session, {record.id for record, _ in pending})
    configs: dict[tuple[uuid.UUID, int], plans.EscalateTo] = {}
    acted = 0
    for record, row in pending:
        if acted >= MAX_ACTIONS:
            break
        if row.approver_id is None:  # pragma: no cover - filtered by the query
            continue
        key = (record.id, row.stage)
        if key not in configs:
            configs[key] = (await stage_config(session, record, row.stage))[0]
        escalates = (
            row.escalated_from_id is None
            and row.id not in escalated
            and configs[key] is not plans.EscalateTo.NONE
        )
        slots = plans.plan(
            row.created_at,
            schedule,
            zones[row.approver_id],
            working_day,
            paused=timedelta(seconds=row.paused_seconds),
            escalates=escalates,
        )
        slot = plans.due_now(slots, now)
        if slot is None or not await _claim(session, claim_key(row.id, slot.step, slot.number)):
            continue
        if slot.step is plans.Step.REMIND:
            await remind(session, record, row, slot.number)
        else:
            await escalate(session, record, row)
            escalated.add(row.id)
        acted += 1
    return acted


async def reminders_schedule(database: Database, settings: Settings) -> None:
    """Every five minutes, every tenant: the request approval reminders due now.

    Each tenant in its own session; one tenant failing never stops the others.
    """
    del settings
    clock = SystemClock()
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                if acted := await sweep(session, clock):
                    log.info("request_approval_reminders", tenant_id=str(tenant), count=acted)
        except Exception:
            log.warning("request_approval_reminders_failed", tenant_id=str(tenant), exc_info=True)
