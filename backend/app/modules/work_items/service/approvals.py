"""Approval decisions, withdrawal and the approver's inbox (WP-030 s2; REQ-SR-021..028, -061).

Who may decide: the approval's own approver holding the type's approve permission, or, for an
approval held by the administrators (REQ-SR-023), anyone with `work_items.approve_any`. The
requested-by and requested-for people never decide their own request unless the item allows
self-approval (REQ-SR-027 AC2, 403 `approval_segregation`). An approver need not see the record
in their view scope: the approval itself gives them its summary (REQ-SR-025).

At MVP the first decision decides the stage (domain/approvals.py): approve moves the request
on (to "new", or "assigned" with the item's technician after approval), reject ends it. The
record's approval status, history and events are written in the same transaction (outbox).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules import service_catalog
from app.modules.identity_access import Subject, person_placement
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain import service_requests as sr_rules
from app.modules.work_items.domain.lifecycle import WorkItemAction
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import APPROVE, APPROVE_ANY
from app.modules.work_items.service.approval_stage import approval_event, requested_for
from app.shared.events import ConsumerSpec, EventEnvelope
from app.shared.history import Source

WITHDRAWN_REASON = "withdrawn_by_requester"  # REQ-SR-061 AC1
log = get_logger(__name__)


@dataclass(frozen=True)
class ApprovalView:
    """One approval as a viewer may see it: a private comment only for staff and its author."""

    row: WorkItemApproval
    comment: str | None
    can_decide: bool
    self_approved: bool


@dataclass(frozen=True)
class PendingApproval:
    """One entry of the approver's inbox (REQ-SR-025)."""

    approval: WorkItemApproval
    record: WorkItem


def _staff(subject: Subject, wtype: WorkItemType) -> bool:
    return subject.holds(wtype.permission("edit"))


def _may_decide(subject: Subject, wtype: WorkItemType, row: WorkItemApproval) -> bool:
    if row.state != rules.ApprovalState.PENDING:
        return False
    if row.approver_id is None:
        return subject.holds(APPROVE_ANY)
    return row.approver_id == subject.user_id and subject.holds(wtype.permission(APPROVE))


def _involved(subject: Subject, record: WorkItem) -> bool:
    return subject.user_id in {record.requester_id, record.on_behalf_of_id}


def _shown(
    subject: Subject, wtype: WorkItemType, record: WorkItem, row: WorkItemApproval
) -> ApprovalView:
    private = row.comment_private and not (
        _staff(subject, wtype) or row.decided_by == subject.user_id
    )
    return ApprovalView(
        row=row,
        comment=None if private else row.comment,
        can_decide=_may_decide(subject, wtype, row)
        and not rules.blocked_for_self(
            subject.user_id,
            requested_by=record.requester_id,
            requested_for=requested_for(record),
            self_approval=row.self_approval,
        ),
        self_approved=row.decided_by is not None
        and row.decided_by in {record.requester_id, requested_for(record)},
    )


async def _record(session: AsyncSession, wtype: WorkItemType, record_id: uuid.UUID) -> WorkItem:
    found: WorkItem | None = await session.scalar(
        select(WorkItem).where(
            WorkItem.id == record_id, WorkItem.type == wtype.code, WorkItem.deleted_at.is_(None)
        )
    )
    if found is None:
        raise NotFound(code="work_item_not_found")  # one code for every type, as the engine
    return found


async def _rows(session: AsyncSession, record_id: uuid.UUID) -> list[WorkItemApproval]:
    return list(
        await session.scalars(
            select(WorkItemApproval)
            .where(
                WorkItemApproval.work_item_id == record_id, WorkItemApproval.deleted_at.is_(None)
            )
            .order_by(WorkItemApproval.stage, WorkItemApproval.created_at, WorkItemApproval.id)
        )
    )


async def list_for_record(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[ApprovalView]:
    """A record's approvals, for those who see the record and for its approvers (REQ-SR-024)."""
    record = await _record(session, wtype, record_id)
    found = await _rows(session, record_id)
    is_approver = any(
        r.approver_id == subject.user_id or (r.approver_id is None and subject.holds(APPROVE_ANY))
        for r in found
    )
    if not is_approver:
        await items.get(session, subject, wtype, record_id)  # 404 outside the view scope
        hidden = (await config.load(session, wtype)).approvals_hidden_from_requesters
        if hidden and not _staff(subject, wtype):
            return []  # REQ-SR-024 AC3: the record's own status still says it waits
    return [_shown(subject, wtype, record, r) for r in found]


async def mine(
    session: AsyncSession, subject: Subject, wtype: WorkItemType
) -> list[PendingApproval]:
    """The approvals waiting for the subject, oldest first (the console drawer, REQ-SR-025)."""
    holders = [WorkItemApproval.approver_id == subject.user_id]
    if subject.holds(APPROVE_ANY):
        holders.append(WorkItemApproval.approver_id.is_(None))
    rows = await session.execute(
        select(WorkItemApproval, WorkItem)
        .join(WorkItem, WorkItem.id == WorkItemApproval.work_item_id)
        .where(
            or_(*holders),
            WorkItemApproval.state == rules.ApprovalState.PENDING.value,
            WorkItemApproval.deleted_at.is_(None),
            WorkItem.type == wtype.code,
            WorkItem.deleted_at.is_(None),
        )
        .order_by(WorkItemApproval.created_at, WorkItemApproval.id)
        .limit(200)
    )
    found = [PendingApproval(a, r) for a, r in rows.all()]
    return [p for p in found if _may_decide(subject, wtype, p.approval)]


async def decide(  # noqa: PLR0913 - the decision and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    decision: rules.Decision,
    comment: str | None,
    private: bool,
    expected_version: int,
    channel: rules.DecisionChannel,
    source: Source,
) -> ApprovalView:
    """Approve or reject one approval; the first decision decides the stage (REQ-SR-025)."""
    record = await _record(session, wtype, record_id)
    row: WorkItemApproval | None = await session.scalar(
        select(WorkItemApproval)
        .where(
            WorkItemApproval.id == approval_id,
            WorkItemApproval.work_item_id == record_id,
            WorkItemApproval.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="approval_not_found")
    if row.state != rules.ApprovalState.PENDING:
        raise Conflict(code="approval_closed", params={"state": row.state})
    if not _may_decide(subject, wtype, row):
        raise PermissionDenied(code="not_an_approver")
    if rules.blocked_for_self(
        subject.user_id,
        requested_by=record.requester_id,
        requested_for=requested_for(record),
        self_approval=row.self_approval,
    ):
        raise PermissionDenied(code="approval_segregation")
    if row.version != expected_version:
        raise Conflict(code="approval_changed", params={"version": row.version})
    if problems := rules.decision_problems(
        decision, comment, comments_required=row.comments_required
    ):
        raise items.field_errors(problems)
    approved = decision is rules.Decision.APPROVE
    state = rules.ApprovalState.APPROVED if approved else rules.ApprovalState.REJECTED
    now = items.now()
    row.state = state.value
    row.decided_at = now
    row.decided_by = subject.user_id
    row.channel = channel.value
    row.comment = (comment or "").strip() or None
    row.comment_private = private
    row.version += 1
    await session.flush()
    await approval_event(session, record, row, "decided")
    await _close_others(
        session, record, row.stage, keep=row.id, state=rules.ApprovalState.NOT_NEEDED
    )
    status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    await _finish(session, wtype, record, status, source=source)
    return _shown(subject, wtype, record, row)


async def _close_others(
    session: AsyncSession,
    record: WorkItem,
    stage: int,
    *,
    keep: uuid.UUID | None,
    state: rules.ApprovalState,
) -> None:
    others = [
        r
        for r in await _rows(session, record.id)
        if r.stage == stage and r.id != keep and r.state == rules.ApprovalState.PENDING
    ]
    if not others:
        return
    await session.execute(
        update(WorkItemApproval)
        .where(WorkItemApproval.id.in_([r.id for r in others]))
        .values(state=state.value, version=WorkItemApproval.version + 1)
        .execution_options(synchronize_session="fetch")
    )
    for r in others:
        await approval_event(session, record, r, "closed")


async def _finish(
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    status: ApprovalStatus,
    *,
    source: Source,
) -> None:
    """The record after its stage was decided: approval status, status move, technician."""
    cat = await config.load(session, wtype)
    action = WorkItemAction.APPROVE if status is ApprovalStatus.APPROVED else WorkItemAction.REJECT
    technician = record.technician_id
    if status is ApprovalStatus.APPROVED and record.catalog_item_id is not None:
        item = await service_catalog.item_decides(session, record.catalog_item_id)
        if item is not None:
            technician = sr_rules.after_approval(
                sr_rules.ItemDecides(
                    needs_approval=True,
                    default_priority=item.default_priority,
                    group_id=item.group_id,
                    technician_id=item.technician_id,
                    technician_after_approval=item.technician_after_approval,
                ),
                current_technician=record.technician_id,
            )
    await items.decided_move(
        session,
        wtype,
        cat,
        record,
        action,
        approval_status=status.value,
        technician_id=technician,
        source=source,
    )


async def withdraw(  # noqa: PLR0913 - the withdrawal and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> WorkItem:
    """The requester withdraws a request awaiting approval (REQ-SR-061 AC1)."""
    record = await _record(session, wtype, record_id)
    if not _involved(subject, record):
        await items.get(session, subject, wtype, record_id)  # 404 outside the view scope
        raise PermissionDenied(code="withdraw_not_allowed")
    if record.approval_status != ApprovalStatus.PENDING:
        raise Conflict(
            code="withdraw_not_pending", params={"approval_status": record.approval_status or ""}
        )
    if record.version != expected_version:
        await items.update_columns(session, record, expected_version, {})  # 409 with what changed
    rows = [r for r in await _rows(session, record_id) if r.state == rules.ApprovalState.PENDING]
    for r in rows:
        await _close_others(
            session, record, r.stage, keep=None, state=rules.ApprovalState.WITHDRAWN
        )
        break  # one call closes the whole stage
    cat = await config.load(session, wtype)
    return await items.decided_move(
        session,
        wtype,
        cat,
        record,
        WorkItemAction.CANCEL,
        approval_status=ApprovalStatus.WITHDRAWN.value,
        technician_id=record.technician_id,
        source=source,
        reason_code=WITHDRAWN_REASON,
    )


__all__ = [
    "APPROVER_LEFT",
    "WITHDRAWN_REASON",
    "ApprovalView",
    "PendingApproval",
    "decide",
    "inactive_approvers_schedule",
    "list_for_record",
    "mine",
    "on_user_status_changed",
    "reroute_inactive",
    "withdraw",
]


async def reroute_from(session: AsyncSession, leaver: uuid.UUID) -> int:
    """Move `leaver`'s pending approvals to the approval administrators (REQ-SR-023).

    "Approver inactive" becomes each one's reason; the leaver's inbox and the administrators'
    screens hear about it. Idempotent: a second run finds nothing pending for that person.
    """
    rows = list(
        await session.scalars(
            select(WorkItemApproval)
            .where(
                WorkItemApproval.approver_id == leaver,
                WorkItemApproval.state == rules.ApprovalState.PENDING.value,
                WorkItemApproval.deleted_at.is_(None),
            )
            .with_for_update()
        )
    )
    for row in rows:
        record = await session.get(WorkItem, row.work_item_id)
        if record is None:  # pragma: no cover - the foreign key keeps the record
            continue
        await approval_event(session, record, row, "closed")  # the leaver's inbox drops it
        row.approver_id = None
        row.origin = rules.ApproverOrigin.ADMINISTRATORS.value
        row.route_reason = rules.RouteReason.APPROVER_INACTIVE.value
        row.version += 1
        await session.flush()
        await approval_event(session, record, row, "opened")  # the administrators' inboxes
    return len(rows)


async def on_user_status_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """A deactivated approver's pending approvals go to the fallback (REQ-SR-023 AC2)."""
    if session is None or envelope.payload.get("status") != "disabled":
        return
    await reroute_from(session, uuid.UUID(str(envelope.payload["user_id"])))


async def reroute_inactive(session: AsyncSession) -> int:
    """The daily check (REQ-SR-023 AC3): no approval waits on someone no longer active.

    Catches what the deactivation event could not (a person removed another way, an event
    lost to an outage); the administrators then find them in their approvals inbox.
    """
    approvers = set(
        await session.scalars(
            select(WorkItemApproval.approver_id)
            .where(
                WorkItemApproval.approver_id.is_not(None),
                WorkItemApproval.state == rules.ApprovalState.PENDING.value,
                WorkItemApproval.deleted_at.is_(None),
            )
            .distinct()
        )
    )
    moved = 0
    for approver in approvers:
        if approver is not None and not (await person_placement(session, approver)).active:
            moved += await reroute_from(session, approver)
    return moved


async def inactive_approvers_schedule(database: Database, settings: Settings) -> None:
    """Every tenant, daily: approvals held by people no longer active go to the fallback."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            if moved := await reroute_inactive(session):
                log.info("approvals_rerouted", tenant_id=str(tenant), approvals=moved)


APPROVER_LEFT = ConsumerSpec(
    name="work_items__approver_left",
    event_types=("identity_access.user.status_changed",),
    handler=on_user_status_changed,
)
