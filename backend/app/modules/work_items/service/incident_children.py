"""Parent and child incidents (WP-046b S2; REQ-INC-086).

One level: a child is linked to one parent (`child_of`, child -> parent; a partial unique index
holds "one parent"), a parent is never itself a child and a child never has children of its
own, so no loop can form. Both records must be ones the person may edit and neither closed.

A link never widens access (lane B): each side lists the other through `parts.links`, which
shows a record the reader may not see as a hidden line. Each change has history and signals
on both records, as any link does.
"""

import uuid

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemLink
from app.modules.work_items.service import parts
from app.modules.work_items.service import work_items as items
from app.shared.history import Source

CHILD_OF = LinkKind.CHILD_OF.value


async def _count(session: AsyncSession, *conditions: ColumnElement[bool]) -> int:
    found = await session.scalar(
        select(func.count()).where(
            WorkItemLink.kind == CHILD_OF,
            WorkItemLink.deleted_at.is_(None),
            *conditions,
        )
    )
    return int(found or 0)


def _open(record: WorkItem) -> bool:
    return StatusCategory(record.status_category) not in FINAL_CATEGORIES


async def add_child(  # noqa: PLR0913 - both records and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    parent_id: uuid.UUID,
    child_id: uuid.UUID,
    *,
    source: Source,
) -> WorkItemLink:
    """Make `child_id` a child of `parent_id` (both editable by the person, both open)."""
    if child_id == parent_id:
        raise items.field_errors([("child_id", "cannot_link_itself")])
    parent = await items.record_for_action(session, subject, wtype, "edit", parent_id)
    try:
        child = await items.record_for_action(session, subject, wtype, "edit", child_id)
    except NotFound as error:
        raise items.field_errors([("child_id", "record_not_found")]) from error
    problems: list[tuple[str, str]] = []
    if not (_open(parent) and _open(child)):
        problems.append(("child_id", "record_closed"))
    if await _count(session, WorkItemLink.source_id == child.id):
        problems.append(("child_id", "already_has_parent"))
    # One level: the parent is no child, the child no parent (so no loop can ever form).
    if await _count(session, WorkItemLink.source_id == parent.id):
        problems.append(("child_id", "parent_is_a_child"))
    if await _count(session, WorkItemLink.target_id == child.id):
        problems.append(("child_id", "child_has_children"))
    if problems:
        raise items.field_errors(problems)
    link = await parts.LinkRepository(session).add(
        WorkItemLink(source_id=child.id, target_id=parent.id, kind=CHILD_OF)
    )
    await parts.link_recorded(session, child, parent, link, "child_added", source)
    return link


async def remove_child(  # noqa: PLR0913 - the record, the link, its version and the source
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    link_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Unlink a child from either side; the person must be able to edit both records."""
    link: WorkItemLink | None = await session.scalar(
        select(WorkItemLink).where(
            WorkItemLink.id == link_id,
            WorkItemLink.kind == CHILD_OF,
            or_(WorkItemLink.source_id == record_id, WorkItemLink.target_id == record_id),
            WorkItemLink.deleted_at.is_(None),
        )
    )
    if link is None:
        raise NotFound(code="work_item_link_not_found")
    child = await items.record_for_action(session, subject, wtype, "edit", link.source_id)
    parent = await items.record_for_action(session, subject, wtype, "edit", link.target_id)
    removed = await parts.LinkRepository(session).soft_delete(
        link.id, expected_version=expected_version
    )
    await parts.link_recorded(session, child, parent, removed, "child_removed", source)


async def open_children(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, parent_id: uuid.UUID
) -> list[WorkItem]:
    """The parent's open children this person may edit (to offer its resolution, REQ-INC-092)."""
    await items.visible_record(session, subject, wtype, parent_id)
    rows = await session.scalars(
        select(WorkItem)
        .join(WorkItemLink, WorkItemLink.source_id == WorkItem.id)
        .where(
            WorkItemLink.target_id == parent_id,
            WorkItemLink.kind == CHILD_OF,
            WorkItemLink.deleted_at.is_(None),
        )
        .order_by(WorkItem.created_at, WorkItem.id)
    )
    return [
        row
        for row in rows
        if _open(row) and await items.may(session, subject, wtype, "edit", row.id)
    ]
