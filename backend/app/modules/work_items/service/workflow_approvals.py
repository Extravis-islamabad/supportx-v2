"""A workflow's approval node on the WP-030 engine (WP-048b S2; REQ-WF-014; ADR-043 §6).

The node's command opens one level of approvals on the record, purpose "workflow", each row
naming the instance and the command. People, groups (each member) and the record's roles (their
holders) are named as a stage's approvers are; anyone who cannot be named (inactive, the
requester, a role nobody holds) sends the level to the administrators too, never a silent dead
end. The level decides by its rule through the shared level outcome, with the tenant's chair
breaking an exact majority split (D-146). The decision reaches the workflow through automation's
`command_finished`, in the deciding transaction (outbox), so the node continues after the commit.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import automation
from app.modules.identity_access import active_user_ids
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import approval_settings, stage_approvals
from app.modules.work_items.service.approval_stage import approval_event, requested_for
from app.shared import action_links
from app.shared.history import Source

APPROVED, REJECTED = "approved", "rejected"  # the node's outputs
TIMED_OUT = "timed_out"  # WP-047a S4 (REQ-SR-044): the node's timeout passed
# The types whose approvals someone can decide (their approval routes, api/routes.py): the node
# is offered for these only, so an incident never holds an approval nobody can answer.
APPROVAL_TYPES = frozenset(
    {
        WorkItemTypeCode.SERVICE_REQUEST,
        WorkItemTypeCode.RELEASE,
        WorkItemTypeCode.PROBLEM,
        WorkItemTypeCode.CHANGE,
    }
)
LINK_OBJECT = "work_item_approval"  # the approvals' no-sign-in links (as approvals.py)


def _level(approvers: Mapping[str, Any], rule: str) -> rules.LevelApprovers:
    return rules.LevelApprovers(
        rule=rules.LevelRule(rule),
        user_ids=tuple(uuid.UUID(str(u)) for u in approvers.get("user_ids", [])),
        group_ids=tuple(uuid.UUID(str(g)) for g in approvers.get("group_ids", [])),
        roles=tuple(str(r) for r in approvers.get("roles", [])),
    )


def _row(  # noqa: PLR0913 - one approval row, explicit
    record: WorkItem,
    *,
    instance_id: uuid.UUID,
    command: str,
    rule: rules.LevelRule,
    approver: uuid.UUID | None,
    reason: rules.RouteReason | None = None,
    chair: bool = False,
) -> WorkItemApproval:
    origin = rules.ApproverOrigin.NAMED if approver else rules.ApproverOrigin.ADMINISTRATORS
    return WorkItemApproval(
        tenant_id=record.tenant_id,
        work_item_id=record.id,
        stage=1,
        rule=rule.value,
        approver_id=approver,
        origin=origin.value,
        route_reason=reason.value if reason else None,
        state=rules.ApprovalState.PENDING.value,
        purpose=rules.ApprovalPurpose.WORKFLOW.value,
        workflow_instance_id=instance_id,
        workflow_command=command,
        # The chair's tie-break vote (D-146) is recorded, but never counted as one of the level.
        advisory=chair,
    )


async def open_for(  # noqa: PLR0913 - the node's command, explicit
    session: AsyncSession,
    record: WorkItem,
    *,
    instance_id: uuid.UUID,
    command: str,
    approvers: Mapping[str, Any],
    rule: str,
) -> list[WorkItemApproval]:
    """Open the node's level on the record: one row per approver, never none."""
    level = _level(approvers, rule)
    people, unheld = await stage_approvals.level_people(session, record, level)
    active = await active_user_ids(session, people)
    reason: rules.RouteReason | None = rules.RouteReason.NO_HOLDER if unheld else None
    named: list[uuid.UUID] = []
    for person in people:
        if person not in active:
            reason = reason or rules.RouteReason.APPROVER_INACTIVE
        elif person == record.requester_id:  # nobody approves their own record's step
            reason = reason or rules.RouteReason.SELF_APPROVAL_BLOCKED
        else:
            named.append(person)
    if not named and reason is None:
        reason = rules.RouteReason.NO_HOLDER
    rows = [
        _row(record, instance_id=instance_id, command=command, rule=level.rule, approver=p)
        for p in named
    ]
    if reason is not None:  # someone could not be named: the administrators decide too
        rows.append(
            _row(
                record,
                instance_id=instance_id,
                command=command,
                rule=level.rule,
                approver=None,
                reason=reason,
            )
        )
    session.add_all(rows)
    await session.flush()
    for row in rows:
        await approval_event(session, record, row, "opened")
    return rows


async def _level_rows(session: AsyncSession, row: WorkItemApproval) -> list[WorkItemApproval]:
    return list(
        await session.scalars(
            select(WorkItemApproval).where(
                WorkItemApproval.workflow_instance_id == row.workflow_instance_id,
                WorkItemApproval.workflow_command == row.workflow_command,
                WorkItemApproval.deleted_at.is_(None),
            )
        )
    )


async def _usable_chair(
    session: AsyncSession, record: WorkItem, chair: uuid.UUID | None
) -> uuid.UUID | None:
    """The tenant's chair, if they may break this record's tie (lane A's #366 review).

    Not when inactive (the tie would wait for ever), not on a record they asked for or that is
    for them (self-approval), and not when they hold one of its segregated roles (REQ-CHG-039).
    Then there is no chair, and an exact majority split rejects (D-146).
    """
    if chair is None:
        return None
    if chair not in await active_user_ids(session, [chair]):
        return None
    if chair in {record.requester_id, requested_for(record)}:
        return None
    if chair in await stage_approvals.segregated(session, record):
        return None
    return chair


def _outcome(
    rule: rules.LevelRule, rows: Sequence[WorkItemApproval], *, chair: uuid.UUID | None
) -> rules.LevelOutcome:
    """The level's outcome by its rule, the tenant's chair breaking a majority split (D-146)."""
    chair_row = next((r for r in rows if r.advisory), None)
    return rules.level_outcome(
        rule,
        [rules.ApprovalState(r.state) for r in rows if not r.advisory],
        chair=chair is not None and rule is rules.LevelRule.MAJORITY,
        chair_vote=rules.ApprovalState(chair_row.state) if chair_row else None,
    )


async def after_decision(
    session: AsyncSession, record: WorkItem, decided: WorkItemApproval
) -> None:
    """A vote on a workflow's level: once the level is decided, the node continues."""
    instance_id, command = decided.workflow_instance_id, decided.workflow_command
    if instance_id is None or command is None:
        return  # not a workflow's row (the caller routes only those here)
    rows = await _level_rows(session, decided)
    chair_row = next((r for r in rows if r.advisory), None)
    chair = await _usable_chair(session, record, await approval_settings.chair(session))
    rule = rules.LevelRule(decided.rule or rules.LevelRule.ANY)
    outcome = _outcome(rule, rows, chair=chair)
    if outcome is rules.LevelOutcome.PENDING:
        return
    if outcome is rules.LevelOutcome.TIED:
        if chair is not None and chair_row is None:  # D-146: the chair breaks the split
            row = _row(
                record,
                instance_id=instance_id,
                command=command,
                rule=rule,
                approver=chair,
                chair=True,
            )
            session.add(row)
            await session.flush()
            await approval_event(session, record, row, "opened")
        return
    await _close_pending(session, record, rows)
    await automation.command_finished(
        session,
        instance_id=instance_id,
        command=command,
        ok=True,
        port=APPROVED if outcome is rules.LevelOutcome.APPROVED else REJECTED,
    )


async def expire_for(
    session: AsyncSession, record: WorkItem, *, instance_id: uuid.UUID, command: str
) -> str:
    """An approval node's timeout passed (WP-047a S4; REQ-SR-044): the output it now takes.

    Its level's rows are locked, the same rows a decision takes (lane C), so exactly one wins:
    a level a decision already settled gives that decision; otherwise its pending rows expire
    (`expired`, the time kept, links revoked in this transaction) and the node takes
    `timed_out`. A decision on an expired row is then refused (`approval_closed`).
    """
    rows = list(
        await session.scalars(
            select(WorkItemApproval)
            .where(
                WorkItemApproval.workflow_instance_id == instance_id,
                WorkItemApproval.workflow_command == command,
                WorkItemApproval.deleted_at.is_(None),
            )
            .with_for_update()
        )
    )
    if rows:
        rule = rules.LevelRule(rows[0].rule or rules.LevelRule.ANY)
        chair = await _usable_chair(session, record, await approval_settings.chair(session))
        outcome = _outcome(rule, rows, chair=chair)
        if outcome is rules.LevelOutcome.APPROVED:
            return APPROVED
        if outcome is rules.LevelOutcome.REJECTED:
            return REJECTED
    now = datetime.now(UTC)
    for row in (r for r in rows if r.state == rules.ApprovalState.PENDING):
        row.state, row.expires_at = rules.ApprovalState.EXPIRED.value, now
        row.version += 1
        await session.flush()
        await approval_event(session, record, row, "closed")
        await action_links.revoke_for(session, LINK_OBJECT, row.id)
    return TIMED_OUT


async def close_for_instance(
    session: AsyncSession, record_id: uuid.UUID, instance_id: uuid.UUID
) -> None:
    """A stopped workflow's open approvals on the record close as not needed (REQ-WF-026).

    Its tasks stay: they are people's work, which may still be wanted without the workflow.
    """
    record = await session.get(WorkItem, record_id)
    if record is None:
        return
    rows = list(
        await session.scalars(
            select(WorkItemApproval).where(
                WorkItemApproval.workflow_instance_id == instance_id,
                WorkItemApproval.deleted_at.is_(None),
            )
        )
    )
    await _close_pending(session, record, rows)


async def _close_pending(
    session: AsyncSession, record: WorkItem, rows: Sequence[WorkItemApproval]
) -> None:
    pending = [r for r in rows if r.state == rules.ApprovalState.PENDING]
    if not pending:
        return
    await session.execute(
        update(WorkItemApproval)
        .where(WorkItemApproval.id.in_([r.id for r in pending]))
        .values(state=rules.ApprovalState.NOT_NEEDED.value, version=WorkItemApproval.version + 1)
        .execution_options(synchronize_session="fetch")
    )
    for r in pending:
        await approval_event(session, record, r, "closed")
        await action_links.revoke_for(session, LINK_OBJECT, r.id)  # decided another way


# --- a trigger's ad hoc ask (WP-047a S4; REQ-SR-044) -------------------------------------------

ASK_APPLIED, ASK_PENDING, ASK_CLOSED = "applied", "approval_pending", "record_closed"


async def ask_for(  # noqa: PLR0913 - the rule's ask, explicit
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    trigger_id: uuid.UUID,
    approvers: Mapping[str, Any],
    rule: str,
    source: Source,
) -> str:
    """A rule asks these people to approve (an ad hoc ask, as REQ-SR-042's); what came of it.

    The coordinator's decision (option a): the decision is recorded, with its history and
    notices, and never moves the request. Named as the workflow node's approvers are (people,
    groups' members, the record's roles), never the requester or the person it is for, anyone
    who cannot be named sending the ask to the administrators too. No-op `approval_pending`
    while this rule's earlier ask (or any approval) is still pending on the request, so a rule
    never asks twice; `record_closed` once it is closed.
    """
    record = await session.scalar(
        select(WorkItem).where(WorkItem.id == record_id).with_for_update()
    )
    if record is None or record.deleted_at is not None:
        return ASK_CLOSED
    if StatusCategory(record.status_category) in FINAL_CATEGORIES:
        return ASK_CLOSED
    if record.approval_status == ApprovalStatus.PENDING.value:
        return ASK_PENDING  # this rule's earlier ask, or the item's own approval, is open
    level = _level(approvers, rule)
    people, unheld = await stage_approvals.level_people(session, record, level)
    active = await active_user_ids(session, people)
    own = {record.requester_id, requested_for(record)}
    named = [p for p in people if p in active and p not in own]
    reason: rules.RouteReason | None = None
    if unheld or not named:
        reason = rules.RouteReason.NO_HOLDER
    elif len(named) < len(people):
        reason = (
            rules.RouteReason.SELF_APPROVAL_BLOCKED
            if own & set(people)
            else rules.RouteReason.APPROVER_INACTIVE
        )
    stage = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(WorkItemApproval.stage), 0)).where(
                    WorkItemApproval.work_item_id == record.id
                )
            )
            or 0
        )
        + 1
    )
    # Imported here: the work item service imports this module through the approvals.
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - see above

    updated = await items.set_fields(
        session,
        record,
        {"approval_status": ApprovalStatus.PENDING.value},
        expected_version=record.version,
        source=source,
    )
    rows = [
        WorkItemApproval(
            tenant_id=record.tenant_id,
            work_item_id=record.id,
            stage=stage,
            approver_id=person,
            origin=(
                rules.ApproverOrigin.NAMED if person else rules.ApproverOrigin.ADMINISTRATORS
            ).value,
            route_reason=None if person else (reason.value if reason else None),
            purpose=rules.ApprovalPurpose.AD_HOC.value,
            rule=level.rule.value,
            state=rules.ApprovalState.PENDING.value,
            trigger_id=trigger_id,
        )
        for person in [*named, *([None] if reason is not None else [])]
    ]
    session.add_all(rows)
    await session.flush()
    for row in rows:
        await approval_event(session, updated, row, "opened")
    return ASK_APPLIED
