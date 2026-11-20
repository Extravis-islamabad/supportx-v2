"""What a requester may do to their own record after submitting (WP-046b S5; REQ-INC-148).

The tenant decides, per type: cancel `off` (as today), `direct`, or `ask` (staff decide); and
which reporting fields a requester may still edit (none by default: read-only, apart from
replying). Every path starts from the portal's own reach check, so a record outside the
requester's reach is a 404 and their own is the only one they act on.

Deciding an ask: the assignee; with none, anyone who may edit the record at its scope (the
group's members, the type's service desk managers, admins: the coordinator's Q2). Approving runs
the ordinary cancel as the decider, with the requester's reason; nothing moves that the decider
could not do on the record.
"""

import html
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.work_items.domain.conversation import EntryKind, ReplyMode, Visibility
from app.modules.work_items.domain.lifecycle import DONE_CATEGORIES, WorkItemAction
from app.modules.work_items.domain.portal import PortalReach
from app.modules.work_items.domain.requester_rules import (
    CancellationState,
    RequesterCancel,
    editable_by_requester,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import (
    WorkItemCancellationDecided,
    WorkItemCancellationRequested,
)
from app.modules.work_items.infra.models import WorkItem, WorkItemCancellationRequest
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import conversations, portal
from app.modules.work_items.service import work_items as items
from app.shared.events import record_event
from app.shared.history import Source

REASON_MAX = 2000


@dataclass(frozen=True)
class CancelOutcome:
    """What a requester's cancel did: cancelled now, or asked (the ask's ID)."""

    canceled: bool
    request_id: uuid.UUID | None


async def _own(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItem:
    """The requester's own record (the portal's reach; 404 otherwise, never 403)."""
    found = await portal.get_record(session, subject, record_id, wtype)
    if found.reach is not PortalReach.OWN:
        raise PermissionDenied(params={"permission": portal.CREATE, "reason": "no_permission"})
    record = await session.get(WorkItem, record_id)
    if record is None or record.deleted_at is not None:
        raise NotFound(code="work_item_not_found")
    return record


def _reason(text: str) -> str:
    cleaned = text.strip()
    if not 1 <= len(cleaned) <= REASON_MAX:
        raise items.field_errors([("reason", "out_of_range")])
    return cleaned


async def pending_ask(
    session: AsyncSession, record_id: uuid.UUID
) -> WorkItemCancellationRequest | None:
    """The record's waiting ask, if any (at most one; the partial unique index)."""
    found: WorkItemCancellationRequest | None = await session.scalar(
        select(WorkItemCancellationRequest).where(
            WorkItemCancellationRequest.work_item_id == record_id,
            WorkItemCancellationRequest.state == CancellationState.PENDING.value,
            WorkItemCancellationRequest.deleted_at.is_(None),
        )
    )
    return found


async def cancel(  # noqa: PLR0913 - the record, the reason and the context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    reason: str,
    source: Source,
) -> CancelOutcome:
    """The requester cancels their record, or asks to, as the tenant's rule says (AC1)."""
    record = await _own(session, subject, wtype, record_id)
    cat = await config.load(session, wtype)
    mode = RequesterCancel(cat.requester_cancel)
    if mode is RequesterCancel.OFF:
        raise PermissionDenied(code="requester_cancel_off")
    why = _reason(reason)
    if mode is RequesterCancel.DIRECT:
        try:
            async with session.begin_nested():
                await items.system_move(
                    session,
                    wtype,
                    cat,
                    record,
                    WorkItemAction.CANCEL,
                    source=source,
                    rule=items.REQUESTER_CANCELED,
                    reason_text=why,
                )
        except (ValidationFailed, Conflict):
            # The life cycle has no cancel from here, or it needs more than a requester gives.
            raise Conflict(code="requester_cancel_not_possible") from None
        return CancelOutcome(canceled=True, request_id=None)
    ask = WorkItemCancellationRequest(
        tenant_id=record.tenant_id,  # the row's own tenant (RLS checks it on insert)
        work_item_id=record.id,
        requested_by=subject.user_id,
        reason=why,
    )
    try:
        async with session.begin_nested():
            session.add(ask)
            await session.flush()
    except IntegrityError:
        raise Conflict(code="cancellation_already_asked") from None
    await record_event(
        session,
        WorkItemCancellationRequested(
            work_item_id=record.id, type=wtype.code.value, requested_by=subject.user_id
        ),
        aggregate_id=ask.id,
        aggregate_version=ask.version,
    )
    return CancelOutcome(canceled=False, request_id=ask.id)


async def withdraw(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> None:
    """The requester takes their waiting ask back."""
    record = await _own(session, subject, wtype, record_id)
    ask = await pending_ask(session, record.id)
    if ask is None or ask.requested_by != subject.user_id:
        raise NotFound(code="cancellation_request_not_found")
    await _close(session, wtype, ask, CancellationState.WITHDRAWN, decided_by=None, note=None)


async def may_decide(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record: WorkItem
) -> bool:
    """The assignee; with none, anyone who may edit the record at its scope (Q2)."""
    if record.technician_id is not None:
        return record.technician_id == subject.user_id
    return await items.may(session, subject, wtype, "edit", record.id)


async def decide(  # noqa: PLR0913 - the decision and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    approve: bool,
    note: str | None,
    reason_code: str | None,
    source: Source,
    policy: conversations.ReplyPolicy,
) -> None:
    """Approve (the ordinary cancel, as the decider) or decline (with a note for the requester)."""
    record = await items.visible_record(session, subject, wtype, record_id)
    ask = await pending_ask(session, record.id)
    if ask is None:
        raise NotFound(code="cancellation_request_not_found")
    if not await may_decide(session, subject, wtype, record):
        raise PermissionDenied(code="not_the_decider")
    if approve:
        await items.transition(
            session,
            subject,
            wtype,
            record.id,
            WorkItemAction.CANCEL,
            expected_version=record.version,
            reason_code=reason_code,
            reason_text=ask.reason,
            source=source,
            holders=policy,
        )
        await _close(
            session, wtype, ask, CancellationState.APPROVED, decided_by=subject.user_id, note=None
        )
        return
    if note is None or not note.strip():
        raise items.field_errors([("note", "required")])
    why = _reason(note)
    # The requester hears why, as an ordinary public reply from the decider (mailed as replies
    # are), so the conversation keeps it with the rest.
    await conversations.add_entry(
        session,
        subject,
        wtype,
        record.id,
        kind=EntryKind.REPLY,
        visibility=Visibility.PUBLIC,
        body="".join(f"<p>{html.escape(line)}</p>" for line in why.splitlines() if line.strip()),
        reply_mode=ReplyMode.REPLY,
        to=[],
        cc=[],
        source=source,
        policy=policy,
    )
    await _close(
        session, wtype, ask, CancellationState.DECLINED, decided_by=subject.user_id, note=why
    )


async def _close(  # noqa: PLR0913 - the ask and how it ended, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    ask: WorkItemCancellationRequest,
    state: CancellationState,
    *,
    decided_by: uuid.UUID | None,
    note: str | None,
) -> None:
    ask.state = state.value
    if decided_by is not None:
        ask.decided_by = decided_by
        ask.decided_at = datetime.now(UTC)
    ask.decision_note = note
    ask.version += 1
    await session.flush()
    await record_event(
        session,
        WorkItemCancellationDecided(
            work_item_id=ask.work_item_id,
            type=wtype.code.value,
            state=state.value,
            requested_by=ask.requested_by,
        ),
        aggregate_id=ask.id,
        aggregate_version=ask.version,
    )


async def edit(  # noqa: PLR0913 - the record, its version, the change and its context
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    changes: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> WorkItem:
    """The requester edits the fields the tenant allows (AC2), with the version read (If-Match).

    A field outside the list, or a staff-only one whatever the list says, is refused by name,
    never echoed back; nothing is changed then.
    """
    record = await _own(session, subject, wtype, record_id)
    cat = await config.load(session, wtype)
    refused = [f for f in changes if not editable_by_requester(f, cat.requester_edit_fields)]
    if refused:
        raise items.field_errors([(f, "field_not_editable_by_requester") for f in sorted(refused)])
    return await items.set_fields(
        session, record, dict(changes), expected_version=expected_version, source=source
    )


@dataclass(frozen=True)
class RequesterOptions:
    """What the requester may do now on their own record, for the portal to offer (S5)."""

    may_cancel: RequesterCancel
    editable_fields: frozenset[str]
    pending: WorkItemCancellationRequest | None


async def requester_options(
    session: AsyncSession, wtype: WorkItemType, record: WorkItem
) -> RequesterOptions:
    """Off and none once the record is resolved, closed or cancelled; else the tenant's rules."""
    cat = await config.load(session, wtype)
    # Done (resolved, closed, cancelled): nothing left for the requester to cancel or edit.
    if record.status_category in DONE_CATEGORIES:
        return RequesterOptions(RequesterCancel.OFF, frozenset(), None)
    return RequesterOptions(
        may_cancel=RequesterCancel(cat.requester_cancel),
        editable_fields=frozenset(
            f
            for f in cat.requester_edit_fields
            if editable_by_requester(f, cat.requester_edit_fields)
        ),
        pending=await pending_ask(session, record.id),
    )


@dataclass(frozen=True)
class WaitingAsk:
    """A requester's waiting ask as staff see it on the record, and whether this person decides."""

    ask: WorkItemCancellationRequest
    may_decide: bool


async def waiting_ask(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WaitingAsk:
    """The record's waiting ask (404 when none, or when the record is out of the reader's reach)."""
    record = await items.visible_record(session, subject, wtype, record_id)
    ask = await pending_ask(session, record.id)
    if ask is None:
        raise NotFound(code="cancellation_request_not_found")
    return WaitingAsk(ask=ask, may_decide=await may_decide(session, subject, wtype, record))
