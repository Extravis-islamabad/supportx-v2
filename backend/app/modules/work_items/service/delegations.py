"""Approval delegation for requests (WP-047a S3b; REQ-SR-035; the coordinator's condition 1).

An approver names a delegate for a date range. While it is active, a request approval that
would name them goes to the delegate instead (`route`), marked `on_behalf_of_id`; the approver
can still decide it. When it ends (early, or its end date comes), the approvals still pending
move back to the approver (`move_back`): the delegate's link is revoked and the approver asked.

Condition 1:
- the delegate passes S2a's eligibility check (active and able to sign in) and is never the
  request's requester or the person it is for (checked at routing; never oneself, in the domain);
- both dates are set, the length is capped (`domain.MAX_DAYS`), one at a time per delegator;
- no chains: a delegate's own delegation is never followed;
- create, change and end are each audited, and both people are told (the event's notice).

A person manages their own delegations with no right; someone else's needs
`requests.manage_delegations` (the service desk manager by default; vendor support never).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import RequestFacts
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject, active_user_ids, person_placement
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain import delegations as domain
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.events import ApprovalDelegationChanged
from app.modules.work_items.infra.models import ApprovalDelegation, WorkItem, WorkItemApproval
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import MANAGE_DELEGATIONS
from app.modules.work_items.service.approval_stage import approval_event, requested_for
from app.modules.work_items.service.followers import RECORD_TYPE
from app.shared import action_links
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

AUDIT_CREATED = "approval_delegation.created"
AUDIT_CHANGED = "approval_delegation.changed"
AUDIT_ENDED = "approval_delegation.ended"
LINK_OBJECT = "work_item_approval"  # as approvals.LINK_OBJECT (no import: it imports this)
MOVED_FIELD = "approval_delegation_ended"  # the record's history when approvals move back
EXPIRE_MAX = 200  # delegations ended per sweep run


def _now() -> datetime:
    return datetime.now(UTC)


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


def _window(row: ApprovalDelegation) -> domain.Window:
    return domain.Window(row.starts_at, row.ends_at, row.ended_at)


async def _eligible(session: AsyncSession, person: uuid.UUID) -> bool:
    """S2a's check: a live, active person of this tenant who may sign in."""
    if person not in await active_user_ids(session, [person]):
        return False
    return (await person_placement(session, person)).can_sign_in


async def active_for(
    session: AsyncSession, person: uuid.UUID, now: datetime | None = None
) -> ApprovalDelegation | None:
    """The person's delegation active now (at most one: overlaps are refused)."""
    at = now or _now()
    rows = await session.scalars(
        select(ApprovalDelegation).where(
            ApprovalDelegation.delegator_id == person,
            ApprovalDelegation.deleted_at.is_(None),
            ApprovalDelegation.starts_at <= at,
            ApprovalDelegation.ends_at > at,
        )
    )
    return next((r for r in rows if _window(r).active_at(at)), None)


async def route(session: AsyncSession, record: WorkItem, rows: Sequence[WorkItemApproval]) -> None:
    """Send each new request approval to its approver's delegate, when one is active (AC1).

    Called on rows about to be written. The delegate must be eligible, not the request's own
    people and not already on the stage; otherwise the approval stays with the approver. A
    delegate's own delegation is never followed (no chains).
    """
    if record.type != SERVICE_REQUEST.code.value:
        return
    own = {record.requester_id, requested_for(record)}
    holding = set(
        await session.scalars(
            select(WorkItemApproval.approver_id).where(
                WorkItemApproval.work_item_id == record.id,
                WorkItemApproval.state == rules.ApprovalState.PENDING.value,
                WorkItemApproval.deleted_at.is_(None),
            )
        )
    )
    for row in rows:
        # A row not yet flushed has no purpose or state of its own until the column defaults
        # apply (record, pending), so an unset one reads as the default.
        purpose = vars(row).get("purpose") or rules.ApprovalPurpose.RECORD.value
        state = vars(row).get("state") or rules.ApprovalState.PENDING.value
        if (
            row.approver_id is None
            or row.on_behalf_of_id is not None
            or purpose != rules.ApprovalPurpose.RECORD.value
            or state != rules.ApprovalState.PENDING.value
        ):
            continue
        delegation = await active_for(session, row.approver_id)
        if delegation is None:
            continue
        delegate = delegation.delegate_id
        on_stage = holding | {r.approver_id for r in rows if r.stage == row.stage}
        if delegate in own or delegate in on_stage or not await _eligible(session, delegate):
            continue
        row.on_behalf_of_id, row.approver_id = row.approver_id, delegate


async def _event(
    session: AsyncSession,
    row: ApprovalDelegation,
    change: Literal["created", "changed", "ended", "expired"],
) -> None:
    await record_event(
        session,
        ApprovalDelegationChanged(
            delegation_id=row.id,
            delegator_id=row.delegator_id,
            delegate_id=row.delegate_id,
            change=change,
            version=row.version,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def _audit(
    session: AsyncSession, row: ApprovalDelegation, action: str, facts: RequestFacts
) -> None:
    await record_audit(
        session,
        action_code=action,
        facts=facts,
        object_type="approval_delegation",
        object_id=str(row.id),
        details={
            "delegator_id": str(row.delegator_id),
            "delegate_id": str(row.delegate_id),
            "starts_at": row.starts_at.isoformat(),
            "ends_at": row.ends_at.isoformat(),
        },
    )


def _may_manage(subject: Subject, delegator_id: uuid.UUID) -> None:
    if delegator_id != subject.user_id and not subject.holds(MANAGE_DELEGATIONS):
        raise PermissionDenied(
            code="permission_denied",
            params={"permission": MANAGE_DELEGATIONS, "reason": "no_permission"},
        )


async def _check(  # noqa: PLR0913 - the delegation's values, explicit
    session: AsyncSession,
    delegator_id: uuid.UUID,
    delegate_id: uuid.UUID,
    window: domain.Window,
    reason: str | None,
    *,
    keep: uuid.UUID | None,
) -> None:
    """Condition 1's checks, the delegate's eligibility, and no overlap (under the lock)."""
    problems = domain.problems(delegator_id, delegate_id, window, reason=reason)
    if not problems and not await _eligible(session, delegate_id):
        problems.append(("delegate_id", "delegate_not_eligible"))
    if not problems:
        others = await session.scalars(
            select(ApprovalDelegation)
            .where(
                ApprovalDelegation.delegator_id == delegator_id,
                ApprovalDelegation.deleted_at.is_(None),
                ApprovalDelegation.id != (keep or uuid.UUID(int=0)),
            )
            .with_for_update()
        )
        if domain.overlaps(window, [_window(o) for o in others]):
            problems.append(("starts_at", "delegation_overlaps"))
    if problems:
        raise items.field_errors(problems)


async def list_for(
    session: AsyncSession, subject: Subject, delegator_id: uuid.UUID | None = None
) -> list[ApprovalDelegation]:
    """Mine (as delegator or delegate), or one person's with the right, newest first."""
    query = select(ApprovalDelegation).where(ApprovalDelegation.deleted_at.is_(None))
    if delegator_id is None:
        query = query.where(
            or_(
                ApprovalDelegation.delegator_id == subject.user_id,
                ApprovalDelegation.delegate_id == subject.user_id,
            )
        )
    else:
        _may_manage(subject, delegator_id)
        query = query.where(ApprovalDelegation.delegator_id == delegator_id)
    return list(await session.scalars(query.order_by(ApprovalDelegation.starts_at.desc())))


async def create(  # noqa: PLR0913 - the delegation and its context, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    delegator_id: uuid.UUID | None,
    delegate_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    reason: str | None,
    facts: RequestFacts,
) -> ApprovalDelegation:
    """Set a delegation (oneself's, or someone else's with the right); both are told."""
    delegator = delegator_id or subject.user_id
    _may_manage(subject, delegator)
    window = domain.Window(starts_at, ends_at)
    text = (reason or "").strip() or None
    await _check(session, delegator, delegate_id, window, text, keep=None)
    row = ApprovalDelegation(
        tenant_id=_tenant(session),
        delegator_id=delegator,
        delegate_id=delegate_id,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=text,
    )
    session.add(row)
    await session.flush()
    await _audit(session, row, AUDIT_CREATED, facts)
    await _event(session, row, "created")
    return row


async def _get(
    session: AsyncSession, delegation_id: uuid.UUID, expected_version: int
) -> ApprovalDelegation:
    row = await session.scalar(
        select(ApprovalDelegation)
        .where(ApprovalDelegation.id == delegation_id, ApprovalDelegation.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="approval_delegation_not_found")
    if row.version != expected_version:
        raise Conflict(code="version_conflict", params={"current_version": row.version})
    return row


async def change(  # noqa: PLR0913 - the delegation, its new values and context, explicit
    session: AsyncSession,
    subject: Subject,
    delegation_id: uuid.UUID,
    values: dict[str, Any],
    *,
    expected_version: int,
    facts: RequestFacts,
) -> ApprovalDelegation:
    """Change a delegation not yet ended (dates, delegate, reason); both are told."""
    row = await _get(session, delegation_id, expected_version)
    _may_manage(subject, row.delegator_id)
    if row.ended_at is not None:
        raise items.field_errors([("ends_at", "delegation_ended")])
    delegate = values.get("delegate_id", row.delegate_id)
    window = domain.Window(
        values.get("starts_at", row.starts_at), values.get("ends_at", row.ends_at)
    )
    reason = (values["reason"] or "").strip() or None if "reason" in values else row.reason
    await _check(session, row.delegator_id, delegate, window, reason, keep=row.id)
    old_delegate = row.delegate_id
    row.delegate_id, row.starts_at, row.ends_at, row.reason = (
        delegate,
        window.starts_at,
        window.ends_at,
        reason,
    )
    row.version += 1
    await session.flush()
    # What the old delegate held goes back to the approver: a new delegate, or a window that no
    # longer covers now (moved later, or ended earlier; lane C's #612 note).
    if delegate != old_delegate or not window.active_at(_now()):
        await move_back(session, row, delegate_id=old_delegate, source="ui")
    await _audit(session, row, AUDIT_CHANGED, facts)
    await _event(session, row, "changed")
    return row


async def end(
    session: AsyncSession,
    subject: Subject,
    delegation_id: uuid.UUID,
    *,
    expected_version: int,
    facts: RequestFacts,
) -> ApprovalDelegation:
    """End a delegation now (AC3: what is still pending moves back); both are told."""
    row = await _get(session, delegation_id, expected_version)
    _may_manage(subject, row.delegator_id)
    if row.ended_at is not None:
        raise items.field_errors([("ends_at", "delegation_ended")])
    row.ended_at = _now()
    row.version += 1
    await session.flush()
    await move_back(session, row, delegate_id=row.delegate_id, source="ui")
    await _audit(session, row, AUDIT_ENDED, facts)
    await _event(session, row, "ended")
    return row


async def move_back(
    session: AsyncSession,
    delegation: ApprovalDelegation,
    *,
    delegate_id: uuid.UUID,
    source: Source,
) -> int:
    """AC3: the delegate's still-pending approvals for the delegator go back to the delegator.

    Each one: the delegate's link revoked (never reused), the delegator asked again (the
    "opened" notice with a fresh link), the record's version bumped (5g) and history saying so.
    How many moved.
    """
    rows = list(
        await session.scalars(
            select(WorkItemApproval)
            .where(
                WorkItemApproval.on_behalf_of_id == delegation.delegator_id,
                WorkItemApproval.approver_id == delegate_id,
                WorkItemApproval.state == rules.ApprovalState.PENDING.value,
                WorkItemApproval.deleted_at.is_(None),
            )
            .with_for_update()
        )
    )
    for row in rows:
        record = await session.get(WorkItem, row.work_item_id, with_for_update=True)
        if record is None:  # pragma: no cover - the foreign key keeps the record
            continue
        await action_links.revoke_for(session, LINK_OBJECT, row.id)
        await session.execute(
            update(WorkItemApproval)
            .where(WorkItemApproval.id == row.id)
            .values(
                approver_id=delegation.delegator_id,
                on_behalf_of_id=None,
                version=WorkItemApproval.version + 1,
            )
            .execution_options(synchronize_session="fetch")
        )
        record.version += 1
        record.updated_at = _now()
        await session.flush()
        await session.refresh(row)
        await approval_event(session, record, row, "opened")
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="child_changed",
            changes=[
                Change(
                    MOVED_FIELD,
                    str(delegate_id),
                    str(delegation.delegator_id),
                )
            ],
            source=source,
            subtype=record.type,
        )
    return len(rows)


async def expire(session: AsyncSession, now: datetime | None = None) -> int:
    """The sweep's part: delegations whose end came give their pending approvals back (AC3).

    Claim-once by marking each `ended_at` at its end (the domain's `until` is unchanged), capped
    per run; both people are told it ended.
    """
    at = now or _now()
    due = list(
        await session.scalars(
            select(ApprovalDelegation)
            .where(
                ApprovalDelegation.deleted_at.is_(None),
                ApprovalDelegation.ended_at.is_(None),
                ApprovalDelegation.ends_at <= at,
            )
            .order_by(ApprovalDelegation.ends_at)
            .limit(EXPIRE_MAX)
            .with_for_update(skip_locked=True)
        )
    )
    for row in due:
        row.ended_at = row.ends_at
        row.version += 1
        await session.flush()
        await move_back(session, row, delegate_id=row.delegate_id, source="rule")
        await _audit(session, row, AUDIT_ENDED, AUDIT_WORKER)
        await _event(session, row, "expired")
    return len(due)


__all__ = [
    "AUDIT_CHANGED",
    "AUDIT_CREATED",
    "AUDIT_ENDED",
    "active_for",
    "change",
    "create",
    "end",
    "expire",
    "list_for",
    "move_back",
    "route",
]
