"""Re-approval of an approved change (WP-045b S4; REQ-CHG-053).

When a stage's approvals complete as approved, the change's watched values are kept
(`take`). `changes_since` lists, per approved stage, what changed since, field by field (AC3);
`after_save` runs after a save of the window, the risk or a plan and reopens the approval of
every stage whose policy says restart (AC1, AC2). Notified changes are listed; the notice to the
board's members comes with the change notifications (WP-056).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied
from app.modules.identity_access import Subject
from app.modules.work_items.domain import changes as change_rules
from app.modules.work_items.domain import reapproval as rules
from app.modules.work_items.domain.change_risk import RiskLevel
from app.modules.work_items.domain.changes import IMPLEMENTATION
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import ChangeApprovalNotice
from app.modules.work_items.infra.models import (
    ChangeApprovalSnapshot,
    WorkItem,
    WorkItemChangeDetails,
    WorkItemPlanSection,
    WorkItemStageEntry,
    WorkItemStageSchedule,
)
from app.modules.work_items.service import catalogue, stage_approvals
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service import work_items as items
from app.shared.events import record_event
from app.shared.history import Change, Source
from app.shared.ids import new_id

CHANGE = TYPES[WorkItemTypeCode.CHANGE]


async def snapshot_now(session: AsyncSession, record: WorkItem) -> rules.Snapshot:
    """The change's watched values as they are now."""
    window = await session.scalar(
        select(WorkItemStageSchedule).where(
            WorkItemStageSchedule.work_item_id == record.id,
            WorkItemStageSchedule.stage == IMPLEMENTATION,
        )
    )
    details = await session.scalar(
        select(WorkItemChangeDetails).where(WorkItemChangeDetails.work_item_id == record.id)
    )
    risk = None if details is None else (details.risk_chosen or details.risk)
    plans = {
        s.section: s.version
        for s in await session.scalars(
            select(WorkItemPlanSection).where(
                WorkItemPlanSection.work_item_id == record.id,
                # The review's sections come after every approval: never a reason to re-approve.
                WorkItemPlanSection.section.in_(change_rules.APPROVED_PLAN_SECTIONS),
            )
        )
    }
    return rules.Snapshot(
        window.scheduled_start if window else None,
        window.scheduled_end if window else None,
        RiskLevel(risk) if risk else None,
        plans,
    )


async def take(session: AsyncSession, record: WorkItem, stage: str) -> None:
    """Keep the watched values now: the stage was just approved."""
    if record.type != WorkItemTypeCode.CHANGE:
        return
    now = await snapshot_now(session, record)
    session.add(
        ChangeApprovalSnapshot(
            id=new_id(),
            tenant_id=record.tenant_id,
            work_item_id=record.id,
            record_stage=stage,
            snapshot=now.to_json(),
        )
    )
    await session.flush()


async def _latest(session: AsyncSession, record_id: uuid.UUID) -> dict[str, rules.Snapshot]:
    """Each approved stage's latest snapshot."""
    rows = await session.scalars(
        select(ChangeApprovalSnapshot)
        .where(ChangeApprovalSnapshot.work_item_id == record_id)
        .order_by(ChangeApprovalSnapshot.created_at, ChangeApprovalSnapshot.id)
    )
    return {r.record_stage: rules.Snapshot.from_json(r.snapshot) for r in rows}


@dataclass(frozen=True)
class StageChanges:
    """What changed since one stage was approved."""

    stage: str
    changes: tuple[rules.FieldChange, ...]


async def _compare(session: AsyncSession, record: WorkItem) -> list[StageChanges]:
    approved = await _latest(session, record.id)
    if not approved:
        return []
    policy = rules.policy_from((await catalogue.load(session, CHANGE)).reapproval)
    now = await snapshot_now(session, record)
    return [
        StageChanges(stage, tuple(rules.compare(before, now, policy)))
        for stage, before in approved.items()
    ]


async def changes_since(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID
) -> list[StageChanges]:
    """Per approved stage, what changed since its approval (REQ-CHG-053 AC3)."""
    record = await items.visible_record(session, subject, CHANGE, record_id)
    return [s for s in await _compare(session, record) if s.changes]


async def to_restart(session: AsyncSession, record: WorkItem) -> list[StageChanges]:
    """The approved stages whose approval a save's changes restart (AC1, AC2)."""
    return [s for s in await _compare(session, record) if rules.restarts(list(s.changes))]


REASON = "reapproval"  # the stage entry's reason code (labels: stage_entry_reason.*)


async def after_save(session: AsyncSession, record: WorkItem, *, source: Source) -> WorkItem:
    """After a save of the window, the risk or a plan: restart what the policy says (AC1, AC2).

    The earliest approved stage that needs approval again takes the change back to its raising
    status by a system move (Haider, 2026-11-10), its level 1 opens as a new round, and the
    history names every field that caused it. Later stages' approvals go with it (the guard
    closes them on entering), since the change passes them again.
    """
    if record.type != WorkItemTypeCode.CHANGE:
        return record
    due = await to_restart(session, record)
    if not due:
        return record
    model = await stage_service.load_model(session, CHANGE, record.lifecycle_version)
    order = list(model.path(str(record.stage_path)).stages)
    first = min(due, key=lambda s: order.index(s.stage) if s.stage in order else len(order))
    settings = await stage_approvals.settings_of(session, CHANGE, record, first.stage)
    if settings is None:  # the stage needs no approval any more: nothing to restart
        return record
    if record.stage == first.stage and record.status == settings.raised_by:
        return record  # already waiting for that approval again: one round, not another
    now = datetime.now(UTC)
    before = items.snapshot_of(record, (*items.STAMP_FIELDS, "stage", "stage_path"))
    from_stage = str(record.stage)
    columns = await stage_service.send_back(
        session,
        CHANGE,
        record,
        stage=first.stage,
        status=settings.raised_by,
        now=now,
        reason_code=REASON,
    )
    updated = await items.save_system_entry(
        session,
        record,
        columns,
        now=now,
        before=before,
        from_stage=from_stage,
        extra=[
            Change(
                "reapproval_restarted",
                None,
                [c.field for c in first.changes if c.effect is rules.OnChange.RESTART],
            )
        ],
        source=source,
    )
    details = await _details(session, record.id)
    if details is not None and order.index(first.stage) < _place(order, from_stage):
        # Where it was, for the emergency override to return it there (Haider, D-144).
        details.resume_stage, details.resume_status = from_stage, str(before["status"])
        await session.flush()
    # The same entry as a move's guard (lane C's #319): a stage whose approvals were removed
    # moves on by itself, so answer with where the record is now.
    await stage_approvals.raise_or_move_on(session, CHANGE, updated)
    await session.refresh(updated)
    await notice(
        session,
        updated,
        "sent_back",
        stage=first.stage,
        fields=[c.field for c in first.changes if c.effect is rules.OnChange.RESTART],
    )
    return updated


def _place(order: list[str], stage: str) -> int:
    return order.index(stage) if stage in order else -1


async def _details(session: AsyncSession, record_id: uuid.UUID) -> WorkItemChangeDetails | None:
    return await session.scalar(
        select(WorkItemChangeDetails).where(WorkItemChangeDetails.work_item_id == record_id)
    )


OVERRIDE = "emergency_override"  # the stage entry's reason code (D-144)


async def emergency_override(  # noqa: PLR0913 - the change, its version and why, explicit
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    reason: str,
    expected_version: int,
    source: Source,
) -> WorkItem:
    """Keep a change going that was sent back for approval mid-way (D-144, Haider 2026-11-10).

    Needs `changes.emergency_override` and a reason. The pending re-approval is withdrawn, the
    change returns to the stage and status it was sent back from, and its review becomes
    mandatory before closing (the guard). The route audits it with the reason.
    """
    record = await items.visible_record(session, subject, CHANGE, record_id)
    # Decided on this change, at the scope it was granted (site, group or all): holding it for
    # one site never reaches another site's change (lane B's #327 review).
    if not await items.may(session, subject, CHANGE, OVERRIDE, record.id):
        raise PermissionDenied(
            params={
                "permission": OVERRIDE_PERMISSION,
                "reason": items.OUT_OF_SCOPE
                if subject.holds(OVERRIDE_PERMISSION)
                else "no_permission",
            }
        )
    if record.version != expected_version:
        raise Conflict(code="version_conflict", params={"current_version": record.version})
    text = " ".join((reason or "").split())
    if not text:
        raise items.field_errors([("reason", "reason_required")])
    details = await _details(session, record.id)
    if details is None or details.resume_stage is None or details.resume_status is None:
        raise Conflict(code="nothing_to_override", params={"id": str(record.id)})
    await stage_approvals.withdraw_pending(session, record, str(record.stage))
    now = datetime.now(UTC)
    before = items.snapshot_of(record, (*items.STAMP_FIELDS, "stage", "stage_path"))
    from_stage = str(record.stage)
    columns = await stage_service.send_back(
        session,
        CHANGE,
        record,
        stage=details.resume_stage,
        status=details.resume_status,
        now=now,
        reason_code=OVERRIDE,
    )
    updated = await items.save_system_entry(
        session,
        record,
        columns,
        now=now,
        before=before,
        from_stage=from_stage,
        extra=[
            Change("emergency_override", None, text),
            Change("pir_required", old=False, new=True),
        ],
        source=source,
    )
    details.resume_stage = details.resume_status = None
    details.pir_required = True
    await session.flush()
    # Back at a status that raises its own stage's approvals: they open (or the stage moves on
    # when it has none), as after any move; never a silent stop (lane C's #327 review).
    await stage_approvals.raise_or_move_on(session, CHANGE, updated)
    await session.refresh(updated)
    await notice(session, updated, "overridden", stage=str(updated.stage))
    return updated


OVERRIDE_PERMISSION = "changes.emergency_override"


async def sent_back_in_this_save(
    session: AsyncSession, record_id: uuid.UUID
) -> list[WorkItemStageEntry]:
    """The stage entries this transaction made to re-approve (for the audit).

    `created_at` defaults to now(), the transaction's start, so equal means "this save".
    """
    return list(
        await session.scalars(
            select(WorkItemStageEntry).where(
                WorkItemStageEntry.work_item_id == record_id,
                WorkItemStageEntry.reason_code == REASON,
                WorkItemStageEntry.created_at == func.now(),
            )
        )
    )


@dataclass(frozen=True)
class Proposed:
    """Values a person is about to save (None: unchanged)."""

    window_start: datetime | None = None
    window_end: datetime | None = None
    risk: RiskLevel | None = None


async def preview(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID, proposed: Proposed
) -> list[StageChanges]:
    """The approved stages a save would send the change back to (Haider: warn first).

    "This sends the change back to CAB; current approvals will be withdrawn": the screen asks
    before saving when this lists a stage. Changes nothing.
    """
    record = await items.visible_record(session, subject, CHANGE, record_id)
    approved = await _latest(session, record.id)
    if not approved:
        return []
    policy = rules.policy_from((await catalogue.load(session, CHANGE)).reapproval)
    now = await snapshot_now(session, record)
    after = rules.Snapshot(
        proposed.window_start or now.window_start,
        proposed.window_end or now.window_end,
        proposed.risk or now.risk,
        now.plans,
    )
    found = [
        StageChanges(stage, tuple(rules.compare(before, after, policy)))
        for stage, before in approved.items()
    ]
    return [s for s in found if rules.restarts(list(s.changes))]


async def notice(  # noqa: PLR0913 - what happened, explicit
    session: AsyncSession,
    record: WorkItem,
    kind: str,
    *,
    stage: str | None,
    fields: list[str] | None = None,
    board_id: uuid.UUID | None = None,
) -> None:
    """Record a notice through the outbox (same transaction); WP-056 sends it."""
    await record_event(
        session,
        ChangeApprovalNotice(
            work_item_id=record.id,
            notice=kind,
            stage=stage,
            fields=fields or [],
            board_id=board_id,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
