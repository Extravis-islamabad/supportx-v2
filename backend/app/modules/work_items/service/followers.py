"""Followers of a work item (WP-020b; REQ-INC-056, REQ-INC-151, D-068).

Following is recorded on the record's history (`child_added` / `child_removed`, field
`follower`), so "who followed, who removed whom, and why" is visible on the History tab
(REQ-INC-151 AC4). A follower row that `grants_access` lets that one person reach the record for
`view` and `add_note` (service/access.py); every other follower only gets updates while their own
scope lets them see it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain.conversation import FollowReason
from app.modules.work_items.events import WorkItemFollowerAdded, WorkItemFollowerRemoved
from app.modules.work_items.infra.models import WorkItem, WorkItemFollower
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

RECORD_TYPE = "work_item"


class FollowerRepository(Repository[WorkItemFollower]):
    """Followers of the session's tenant."""

    model = WorkItemFollower


async def current(
    session: AsyncSession, record_id: uuid.UUID, user_id: uuid.UUID
) -> WorkItemFollower | None:
    """The live follower row of one person on one record."""
    found: WorkItemFollower | None = await session.scalar(
        select(WorkItemFollower).where(
            WorkItemFollower.work_item_id == record_id,
            WorkItemFollower.user_id == user_id,
            WorkItemFollower.deleted_at.is_(None),
        )
    )
    return found


async def of_record(session: AsyncSession, record_id: uuid.UUID) -> list[WorkItemFollower]:
    """Everyone following a record, oldest first."""
    rows = await session.scalars(
        select(WorkItemFollower)
        .where(WorkItemFollower.work_item_id == record_id, WorkItemFollower.deleted_at.is_(None))
        .order_by(WorkItemFollower.created_at, WorkItemFollower.id)
    )
    return list(rows)


async def _history(
    session: AsyncSession,
    record: WorkItem,
    kind: str,
    changes: list[Change],
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_removed" if kind == "removed" else "child_added",
        changes=changes,
        source=source,
    )


def _payload(row: WorkItemFollower) -> dict[str, object]:
    return {
        "work_item_id": row.work_item_id,
        "user_id": row.user_id,
        "reason": row.reason,
        "grants_access": row.grants_access,
    }


async def follow(  # noqa: PLR0913 - the record, the person, why, and the source, explicit
    session: AsyncSession,
    record: WorkItem,
    user_id: uuid.UUID,
    *,
    reason: FollowReason,
    grants_access: bool = False,
    source: Source,
) -> tuple[WorkItemFollower, bool]:
    """Make `user_id` a follower (or widen an existing follow to grant access).

    Returns the row and whether anything changed. Following twice is not an error.
    """
    existing = await current(session, record.id, user_id)
    if existing is not None:
        if not grants_access or existing.grants_access:
            return existing, False
        updated = await FollowerRepository(session).update(
            existing.id,
            expected_version=existing.version,
            changes={"grants_access": True, "reason": reason},
        )
        await _history(
            session,
            record,
            "added",
            [Change("follower_access", None, str(user_id)), Change("follow_reason", None, reason)],
            source,
        )
        await record_event(
            session,
            WorkItemFollowerAdded.model_validate(_payload(updated)),
            aggregate_id=updated.id,
            aggregate_version=updated.version,
        )
        return updated, True
    row = await FollowerRepository(session).add(
        WorkItemFollower(
            work_item_id=record.id,
            user_id=user_id,
            reason=reason,
            grants_access=grants_access,
        )
    )
    changes = [Change("follower", None, str(user_id)), Change("follow_reason", None, reason)]
    if grants_access:
        changes.append(Change("follower_access", None, str(user_id)))
    await _history(session, record, "added", changes, source)
    await record_event(
        session,
        WorkItemFollowerAdded.model_validate(_payload(row)),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return row, True


async def unfollow(
    session: AsyncSession, record: WorkItem, row: WorkItemFollower, *, source: Source
) -> None:
    """Stop `row` following (soft delete); access it granted ends with it."""
    removed = await FollowerRepository(session).soft_delete(row.id, expected_version=row.version)
    await _history(session, record, "removed", [Change("follower", str(row.user_id), None)], source)
    await record_event(
        session,
        WorkItemFollowerRemoved.model_validate(_payload(removed)),
        aggregate_id=removed.id,
        aggregate_version=removed.version,
    )
