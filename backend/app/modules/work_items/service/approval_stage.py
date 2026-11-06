"""Opening a record's approval stage at submission (WP-030 s2; REQ-SR-021, -022, -023, -027).

Kept apart from the decisions (service/approvals.py) so that creation can open a stage without
importing the decision code, which itself moves the record through the work item service.
The stage is snapshotted from the item: its approvers resolved now (a later manager change does
not move a pending approval, REQ-SR-022 AC3) and its switches kept on each approval.
"""

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import service_catalog
from app.modules.identity_access import person_placement
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.events import ApprovalChange, WorkItemApprovalChanged
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.shared.events import record_event
from app.shared.history import Source


def requested_for(record: WorkItem) -> uuid.UUID:
    """The person the request is for: on behalf of someone, else the requester."""
    return record.on_behalf_of_id or record.requester_id


class Holders(Protocol):
    """The policy service as this needs it: who holds a permission."""

    async def holders(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        permission: str,
        *,
        search: str | None = ...,
        limit: int = ...,
    ) -> list[tuple[uuid.UUID, str]]:
        """Active users holding the permission: (id, display name)."""
        ...


APPROVE_ANY = "work_items.approve_any"


async def _nobody_can_decide(
    session: AsyncSession, record: WorkItem, holders: Holders | None, *, self_approval: bool
) -> bool:
    """The administrators' entry would wait for ever: no one but the requester holds it."""
    if holders is None:
        return False
    blocked = set() if self_approval else {record.requester_id, requested_for(record)}
    found = await holders.holders(session, record.tenant_id, APPROVE_ANY, limit=20)
    return all(user_id in blocked for user_id, _ in found)


async def open_stage(
    session: AsyncSession,
    record: WorkItem,
    item: service_catalog.RequestItem | None,
    holders: Holders | None = None,
) -> list[WorkItemApproval]:
    """Open stage 1 of `record` from its item: one approval per resolved approver, never none.

    Nothing for a record without an item (incidents) or an item that needs no approval.
    """
    if item is None or not item.needs_approval:
        return []
    target = requested_for(record)
    manager = (await person_placement(session, target)).manager_id
    candidates = {pid for _, pid in item.approvers if pid is not None}
    candidates |= {p for p in (manager, item.backup_id) if p is not None}
    people: dict[uuid.UUID, rules.Person] = {}
    for person_id in candidates:
        placement = await person_placement(session, person_id)
        people[person_id] = rules.Person(person_id, active=placement.active)
    assignments = rules.resolve(
        rules.StageInput(
            approvers=tuple(
                rules.ApproverSpec(manager_of_requested_for=is_manager, person_id=pid)
                for is_manager, pid in item.approvers
            ),
            backup_id=item.backup_id,
            self_approval=item.self_approval,
            requested_by=record.requester_id,
            requested_for=target,
            manager_id=manager,
        ),
        people,
    )
    opened = []
    for assignment in assignments:
        reason = assignment.reason.value if assignment.reason else None
        if (
            assignment.origin is rules.ApproverOrigin.ADMINISTRATORS
            # "The approver is the requester" already says why it waits (REQ-SR-027).
            and assignment.reason is not rules.RouteReason.SELF_APPROVAL_BLOCKED
            and await _nobody_can_decide(session, record, holders, self_approval=item.self_approval)
        ):
            # QA6-SR-01: say so on the record instead of waiting silently for ever; an admin
            # names an approver or gives someone else the right (the daily check reroutes).
            reason = rules.RouteReason.NO_HOLDER.value
        row = WorkItemApproval(
            tenant_id=record.tenant_id,
            work_item_id=record.id,
            stage=1,
            approver_id=assignment.approver_id,
            origin=assignment.origin.value,
            route_reason=reason,
            state=rules.ApprovalState.PENDING.value,
            self_approval=item.self_approval,
            comments_required=item.comments_required,
        )
        session.add(row)
        opened.append(row)
    await session.flush()
    for row in opened:
        await approval_event(session, record, row, "opened")
    return opened


async def after_submission(
    session: AsyncSession,
    record: WorkItem,
    item: service_catalog.RequestItem | None,
    *,
    source: Source,
    holders: Holders | None = None,
) -> None:
    """A new request from an item: its approval stage, or its fulfilment plan when none."""
    if item is None:
        return
    if item.needs_approval:
        await open_stage(session, record, item, holders)
        return
    # Imported here: fulfilment reaches the work item service, which imports this module.
    from app.modules.work_items.service import fulfilment  # noqa: PLC0415 - see above

    await fulfilment.start_plan(session, record, item, source=source)  # REQ-SR-046


async def approval_event(
    session: AsyncSession, record: WorkItem, row: WorkItemApproval, change: ApprovalChange
) -> None:
    """The approval's event, in the same transaction (outbox)."""
    await record_event(
        session,
        WorkItemApprovalChanged(
            work_item_id=record.id,
            type=record.type,
            approval_id=row.id,
            approver_id=row.approver_id,
            state=row.state,
            change=change,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )


__all__ = ["after_submission", "approval_event", "open_stage", "requested_for"]
