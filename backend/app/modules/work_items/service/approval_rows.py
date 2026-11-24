"""Every new request approval row goes through here before it is written (WP-047a S3b).

- Its round (REQ-SR-041): the record's current round unless the caller set one (a restart opens
  the next round explicitly), so the engine counts it with the others of that round.
- Its delegation (REQ-SR-035): an approver away on an active delegation is asked through the
  delegate (`delegations.route`).

Called from each place a request row is made: a stage opening (staged or today's single stage),
an escalation, an approver added or replaced.
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.infra.models import WorkItem, WorkItemApproval


async def current_round(session: AsyncSession, record: WorkItem) -> int:
    """The record's latest approval round (1 before any)."""
    found = await session.scalar(
        select(func.max(WorkItemApproval.round)).where(
            WorkItemApproval.work_item_id == record.id, WorkItemApproval.deleted_at.is_(None)
        )
    )
    return int(found or 1)


async def prepare(
    session: AsyncSession, record: WorkItem, rows: Sequence[WorkItemApproval]
) -> None:
    """Stamp the round on rows that have none, then route delegations."""
    # A row not yet flushed has no round of its own until the column default applies at flush,
    # so it is read from the instance itself (the typed attribute says int).
    unset = [r for r in rows if vars(r).get("round") is None]
    if unset:
        latest = await current_round(session, record)
        for row in unset:
            row.round = latest
    # Imported here: delegations reaches the work item service, which reaches this module.
    from app.modules.work_items.service import delegations  # noqa: PLC0415 - see above

    await delegations.route(session, record, rows)


__all__ = ["current_round", "prepare"]
