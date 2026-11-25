"""Restarting a request's approval after a relevant change (WP-047a S3b; REQ-SR-041).

The item marks the questions whose answers restart approval, and may add the quantity and the
requested-for person (`RequestItem.restart_keys`). When one of those changes after approval
started (pending, or approved before fulfilment started), the coordinator's condition 3 holds:

- this round's pending approvals end as not needed, with the reason in history;
- the approvers of the round that ended are told (`work_items.approval.restarted`);
- every link of that round is revoked, never reused (`action_links.revoke_for`);
- a new round opens from the first stage (conditions and automatic rules read the new answers),
  and the request goes back to awaiting approval (AC1). Earlier decisions stay in history.

An unmarked change restarts nothing (AC2). After fulfilment started, the change is recorded and
flagged on the record's history, with no restart (the WP plan's Q7).
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules import service_catalog
from app.modules.audit import RequestFacts
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain import delegations as domain
from app.modules.work_items.domain.clarifications import ClarificationEnd
from app.modules.work_items.domain.parts import TaskStatus
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import SERVICE_REQUEST, WorkItemType
from app.modules.work_items.events import WorkItemApprovalRestarted
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import approval_rows, clarification_rows, parts
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.approval_stage import approval_event, open_stage
from app.modules.work_items.service.followers import RECORD_TYPE
from app.shared import action_links
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

RESTARTED = "service_request.approval_restarted"  # the audit entry
FIELD = "approval_restarted"  # the record's history line
FLAGGED = "approval_restart_skipped"  # changed after fulfilment started: recorded, no restart
LINK_OBJECT = "work_item_approval"
_RUNNING = (ApprovalStatus.PENDING.value, ApprovalStatus.APPROVED.value)


async def _fulfilment_started(session: AsyncSession, record: WorkItem) -> bool:
    """Whether any of the request's tasks has moved on from open."""
    return any(t.status != TaskStatus.OPEN.value for t in await parts.tasks_of(session, record.id))


async def check(  # noqa: PLR0913 - what changed and how, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    *,
    before_answers: Mapping[str, Any],
    before_quantity: int | None,
    before_for: uuid.UUID | None,
    source: Source,
    facts: RequestFacts,
) -> list[str]:
    """After a saved change: restart the approval if a marked key changed; the keys that did."""
    if (
        record.type != SERVICE_REQUEST.code.value
        or record.catalog_item_id is None
        or record.approval_status not in _RUNNING
    ):
        return []
    item = await service_catalog.item_decides(session, record.catalog_item_id)
    if item is None or not item.restart_keys:
        return []
    marked = [k for k in item.restart_keys if k not in (domain.QUANTITY, domain.REQUESTED_FOR)]
    keys = domain.restart_keys(
        before_answers,
        record.answers or {},
        marked,
        quantity=(before_quantity, record.quantity),
        requested_for=(before_for, record.on_behalf_of_id),
        on_quantity=domain.QUANTITY in item.restart_keys,
        on_requested_for=domain.REQUESTED_FOR in item.restart_keys,
    )
    if not keys:
        return []  # AC2: an unmarked change restarts nothing
    if await _fulfilment_started(session, record):
        await _history(session, record, FLAGGED, {"keys": keys}, source)
        return keys
    await restart(session, wtype, record, keys, source=source, facts=facts, item=item)
    return keys


async def _history(
    session: AsyncSession,
    record: WorkItem,
    field: str,
    said: dict[str, Any],
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_changed",
        changes=[Change(field, None, said)],
        source=source,
        reason="answers_changed",
        subtype=record.type,
    )


async def restart(  # noqa: PLR0913 - the request, why and its item, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    keys: list[str],
    *,
    source: Source,
    facts: RequestFacts,
    item: service_catalog.RequestItem,
) -> int:
    """End this round and open the next from stage 1 (condition 3); the new round's number."""
    rows = list(
        await session.scalars(
            select(WorkItemApproval).where(
                WorkItemApproval.work_item_id == record.id,
                WorkItemApproval.purpose == rules.ApprovalPurpose.RECORD.value,
                WorkItemApproval.record_stage.is_(None),
                WorkItemApproval.deleted_at.is_(None),
            )
        )
    )
    ending = await approval_rows.current_round(session, record)
    this_round = [r for r in rows if r.round == ending]
    pending = [r for r in this_round if r.state == rules.ApprovalState.PENDING]
    if pending:
        await session.execute(
            update(WorkItemApproval)
            .where(WorkItemApproval.id.in_([r.id for r in pending]))
            .values(
                state=rules.ApprovalState.NOT_NEEDED.value, version=WorkItemApproval.version + 1
            )
            .execution_options(synchronize_session="fetch")
        )
        for r in pending:
            await approval_event(session, record, r, "closed")
        await clarification_rows.end_open(
            session, record, [r.id for r in pending], ClarificationEnd.CLOSED
        )
    for r in this_round:  # every link of the round, decided or not, is never reused
        await action_links.revoke_for(session, LINK_OBJECT, r.id)
    told = sorted({r.approver_id for r in this_round if r.approver_id is not None}, key=str)
    told += sorted({r.on_behalf_of_id for r in this_round if r.on_behalf_of_id}, key=str)
    next_round = ending + 1
    said = {"round": next_round, "keys": keys}
    await _history(session, record, FIELD, said, source)
    await record_audit(
        session,
        action_code=RESTARTED,
        facts=facts,
        object_type="service_request",
        object_id=str(record.id),
        details={"display_id": record.display_id, **said},
    )
    await record_event(
        session,
        WorkItemApprovalRestarted(
            work_item_id=record.id,
            type=record.type,
            round=next_round,
            approver_ids=list(dict.fromkeys(told)),
            keys=keys,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    updated = await items.back_to_approval(
        session, wtype, record, approval_round=next_round, source=source
    )
    await _open(session, wtype, updated, item, source=source)
    return next_round


async def _open(
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    item: service_catalog.RequestItem,
    *,
    source: Source,
) -> None:
    """The new round from stage 1: the snapshot's stages as raised, or today's single stage.

    The snapshot stays the one taken at submission (never the item as it is now); its
    conditions and automatic rules read the new answers as the stages open.
    """
    if record.approval_stages is None:
        await open_stage(session, record, item)
        return
    # Imported here: request_stages and approvals reach the work item service, as this does.
    from app.modules.work_items.service import approvals, request_stages  # noqa: PLC0415

    outcome = await request_stages.advance(session, record)
    if outcome is not rules.LevelOutcome.PENDING:  # every stage skipped or automatic
        await approvals.finish_staged(
            session, wtype, record, approved=outcome is rules.LevelOutcome.APPROVED, source=source
        )


async def change_answers(  # noqa: PLR0913 - the request, its new values and context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    answers: Mapping[str, Any] | None,
    quantity: int | None,
    expected_version: int,
    source: Source,
    facts: RequestFacts,
) -> tuple[WorkItem, list[str]]:
    """Change a request's answers or quantity after submitting (staff: the edit right; If-Match).

    The answers given replace those keys (others stay); they are checked against the item's form
    as at raising, the quantity against its maximum. Then a marked change restarts approval
    (`check`). The record, and the keys that restarted it (empty: nothing did).
    """
    if wtype.code is not SERVICE_REQUEST.code:
        raise NotFound(code="work_item_not_found")
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    if record.catalog_item_id is None:
        raise items.field_errors([("answers", "not_allowed")])
    merged = {**(record.answers or {}), **(answers or {})}
    item = await service_catalog.item_decides_with(session, record.catalog_item_id, merged)
    if item is None:
        raise NotFound(code="catalog_item_not_found")
    problems = list(item.answer_problems) if answers is not None else []
    if quantity is not None:
        if item.max_quantity is None:
            problems.append(("quantity", "not_allowed"))
        elif not 1 <= quantity <= item.max_quantity:
            problems.append(("quantity", "quantity_over_max"))
    if problems:
        raise items.field_errors(problems, quantity={"max": item.max_quantity})
    before_answers, before_quantity = dict(record.answers or {}), record.quantity
    updated = await items.save_request_answers(
        session,
        record,
        expected_version=expected_version,
        answers=merged,
        quantity=quantity,
        source=source,
        item=item,  # WP-047b S1: the estimate follows the new answers (D-184)
    )
    keys = await check(
        session,
        wtype,
        updated,
        before_answers=before_answers,
        before_quantity=before_quantity,
        before_for=updated.on_behalf_of_id,
        source=source,
        facts=facts,
    )
    return updated, keys


__all__ = ["FIELD", "FLAGGED", "RESTARTED", "change_answers", "check", "restart"]
