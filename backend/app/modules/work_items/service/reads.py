"""Unread markers (WP-046b S3a; REQ-INC-115 AC2).

A record is unread for a person when, since they last opened it, someone else changed it
(its version moved and `updated_by` is not them) or added a public conversation entry (a reply
does not move the record's version, so entries are checked on their own). Only public entries
count, so a note's existence never reaches a reader who might not see it. One they never
opened counts only when it is assigned to them: a new public reply marks an incident unread
for its assignee (AC2), and the release does not light up every old record for everyone.

Personal and private: nobody else ever learns what someone has read. Opening is marked by an
explicit call from the record page (never by a GET), and only moves forward.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.work_items.domain.conversation import Visibility
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemConversation, WorkItemRead
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import work_items as items


def is_unread(
    record: WorkItem,
    user_id: uuid.UUID,
    seen: tuple[int, datetime] | None,
    others_public_at: datetime | None,
) -> bool:
    """The rule above for one record (pure): `seen` is (version, when) of their last opening."""
    changed_by_others = record.updated_by != user_id
    if seen is None:
        return record.technician_id == user_id and (
            changed_by_others or others_public_at is not None
        )
    version, seen_at = seen
    return (record.version > version and changed_by_others) or (
        others_public_at is not None and others_public_at > seen_at
    )


async def unread_ids(
    session: AsyncSession, subject: Subject, rows: Sequence[WorkItem]
) -> list[uuid.UUID]:
    """Which of a page's rows are unread for the subject (rows they already may see)."""
    if not rows:
        return []
    ids = [r.id for r in rows]
    seen = {
        item: (version, at)
        for item, version, at in (
            await session.execute(
                select(
                    WorkItemRead.work_item_id, WorkItemRead.seen_version, WorkItemRead.seen_at
                ).where(WorkItemRead.user_id == subject.user_id, WorkItemRead.work_item_id.in_(ids))
            )
        ).all()
    }
    latest = dict(
        (
            await session.execute(
                select(WorkItemConversation.work_item_id, func.max(WorkItemConversation.created_at))
                .where(
                    WorkItemConversation.work_item_id.in_(ids),
                    WorkItemConversation.visibility == Visibility.PUBLIC,
                    WorkItemConversation.deleted_at.is_(None),
                    WorkItemConversation.created_by.is_distinct_from(subject.user_id),
                )
                .group_by(WorkItemConversation.work_item_id)
            )
        ).all()
    )
    return [r.id for r in rows if is_unread(r, subject.user_id, seen.get(r.id), latest.get(r.id))]


async def mark_read(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> int:
    """Mark the record read at its current version (404 unless they may see it)."""
    if not await items.may(session, subject, wtype, "view", record_id):
        raise items.not_found(wtype)
    version = await session.scalar(
        select(WorkItem.version).where(
            WorkItem.id == record_id, WorkItem.type == wtype.code, WorkItem.deleted_at.is_(None)
        )
    )
    if version is None:
        raise items.not_found(wtype)
    statement = insert(WorkItemRead).values(
        tenant_id=config.tenant_of(session),
        user_id=subject.user_id,
        work_item_id=record_id,
        seen_version=version,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["tenant_id", "user_id", "work_item_id"],
            set_={
                "seen_version": func.greatest(WorkItemRead.seen_version, version),
                "seen_at": func.now(),
            },
        )
    )
    return int(version)
