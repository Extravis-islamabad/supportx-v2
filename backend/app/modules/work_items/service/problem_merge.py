"""Merging duplicate problems, with undo (WP-044b s2; REQ-PRB-046).

- `merge`: the duplicate goes to the system status `merged`, a `merged_into` link points to
  the survivor, and every incident it caused moves to the survivor. Each move has history on
  both records. Both problems must be ones the subject may edit, neither closed, and the
  survivor not merged itself.
- `undo_merge`: puts it back. The duplicate returns to the status it had, the link goes, and
  the moved incidents return, those still caused by the survivor. An incident since linked
  elsewhere stays where it is and is named in the answer.

What moved is kept in the duplicate's history (the `merge` change), so the undo needs no table
of its own and the history shows exactly what happened.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import (
    FINAL_CATEGORIES,
    StatusCategory,
    WorkItemAction,
)
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import PROBLEM
from app.modules.work_items.infra.models import WorkItem, WorkItemLink
from app.modules.work_items.service import parts
from app.modules.work_items.service import work_items as items
from app.shared.history import Change, FieldChange, Source

MERGED = "merged"
MERGE_FIELD = "merge"  # the history change that records what moved


@dataclass(frozen=True)
class MergeOutcome:
    """The duplicate after the merge or undo, and the incidents that moved (or stayed)."""

    record: WorkItem
    moved: list[uuid.UUID]
    stayed: list[uuid.UUID]


async def _caused_links(session: AsyncSession, problem_id: uuid.UUID) -> list[WorkItemLink]:
    return list(
        await session.scalars(
            select(WorkItemLink).where(
                WorkItemLink.target_id == problem_id,
                WorkItemLink.kind == LinkKind.CAUSED_BY.value,
                WorkItemLink.deleted_at.is_(None),
            )
        )
    )


async def _move_cause(
    session: AsyncSession,
    link: WorkItemLink,
    old: WorkItem,
    new: WorkItem,
    source: Source,
) -> None:
    """The incident's `caused_by` goes from `old` to `new`, with history on all three records."""
    incident = await session.get(WorkItem, link.source_id)
    if incident is None:  # pragma: no cover - a link always has its records (FK)
        return
    links = parts.LinkRepository(session)
    removed = await links.soft_delete(link.id, expected_version=link.version)
    await parts.link_recorded(session, incident, old, removed, "child_removed", source)
    added = await links.add(
        WorkItemLink(source_id=incident.id, target_id=new.id, kind=LinkKind.CAUSED_BY.value)
    )
    await parts.link_recorded(session, incident, new, added, "child_added", source)


def _open(record: WorkItem) -> bool:
    return StatusCategory(record.status_category) not in FINAL_CATEGORIES


async def merge(  # noqa: PLR0913 - both problems, the version and the source, explicit
    session: AsyncSession,
    subject: Subject,
    duplicate_id: uuid.UUID,
    survivor_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> MergeOutcome:
    """Merge the duplicate into the survivor (409 when either is closed or already merged)."""
    if duplicate_id == survivor_id:
        raise items.field_errors([("into_id", "cannot_merge_itself")])
    duplicate = await items.record_for_action(session, subject, PROBLEM, "edit", duplicate_id)
    survivor = await items.record_for_action(session, subject, PROBLEM, "edit", survivor_id)
    if not _open(duplicate):
        raise Conflict(code="problem_closed", params={"display_id": duplicate.display_id})
    if not _open(survivor):
        raise Conflict(code="problem_closed", params={"display_id": survivor.display_id})
    if duplicate.version != expected_version:
        raise await items.stale_record(session, duplicate, expected_version)
    caused = await _caused_links(session, duplicate.id)
    for link in caused:
        await _move_cause(session, link, duplicate, survivor, source)
    merged = await parts.LinkRepository(session).add(
        WorkItemLink(source_id=duplicate.id, target_id=survivor.id, kind=LinkKind.MERGED_INTO.value)
    )
    await parts.link_recorded(session, duplicate, survivor, merged, "child_added", source)
    moved = [link.source_id for link in caused]
    fresh = await session.get(WorkItem, duplicate.id, populate_existing=True)
    assert fresh is not None  # noqa: S101 - just read above
    what: dict[str, Any] = {
        "into": str(survivor.id),
        "into_display_id": survivor.display_id,
        "status": duplicate.status,
        "incidents": [str(i) for i in moved],
    }
    updated = await items.set_status(
        session,
        PROBLEM,
        fresh,
        WorkItemAction.MERGE,
        target=MERGED,
        expected_version=fresh.version,
        source=source,
        extra=[Change(MERGE_FIELD, None, what)],
    )
    return MergeOutcome(updated, moved, [])


async def _last_merge(session: AsyncSession, record_id: uuid.UUID) -> dict[str, Any] | None:
    found = await session.scalar(
        select(FieldChange.new_value)
        .where(
            FieldChange.record_type == items.RECORD_TYPE,
            FieldChange.record_id == record_id,
            FieldChange.field == MERGE_FIELD,
            FieldChange.new_value.is_not(None),
        )
        .order_by(FieldChange.occurred_at.desc())
        .limit(1)
    )
    return found if isinstance(found, dict) else None


async def undo_merge(
    session: AsyncSession,
    subject: Subject,
    duplicate_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> MergeOutcome:
    """Undo the last merge of this problem (409 `not_merged` when it is not merged now)."""
    duplicate = await items.record_for_action(session, subject, PROBLEM, "edit", duplicate_id)
    if duplicate.status != MERGED:
        raise Conflict(code="not_merged", params={"display_id": duplicate.display_id})
    if duplicate.version != expected_version:
        raise await items.stale_record(session, duplicate, expected_version)
    what = await _last_merge(session, duplicate.id)
    link = await session.scalar(
        select(WorkItemLink).where(
            WorkItemLink.source_id == duplicate.id,
            WorkItemLink.kind == LinkKind.MERGED_INTO.value,
            WorkItemLink.deleted_at.is_(None),
        )
    )
    if what is None or link is None:  # pragma: no cover - a merge always writes both
        raise Conflict(code="not_merged", params={"display_id": duplicate.display_id})
    survivor = await items.record_for_action(session, subject, PROBLEM, "edit", link.target_id)
    removed = await parts.LinkRepository(session).soft_delete(
        link.id, expected_version=link.version
    )
    await parts.link_recorded(session, duplicate, survivor, removed, "child_removed", source)
    wanted = {uuid.UUID(i) for i in what.get("incidents", [])}
    moved: list[uuid.UUID] = []
    for caused in await _caused_links(session, survivor.id):
        if caused.source_id in wanted:
            await _move_cause(session, caused, survivor, duplicate, source)
            moved.append(caused.source_id)
    stayed = sorted(wanted - set(moved), key=str)
    fresh = await session.get(WorkItem, duplicate.id, populate_existing=True)
    assert fresh is not None  # noqa: S101 - just read above
    back = str(what.get("status") or "investigating")
    updated = await items.set_status(
        session,
        PROBLEM,
        fresh,
        WorkItemAction.UNDO_MERGE,
        target=back,
        expected_version=fresh.version,
        source=source,
        extra=[Change(MERGE_FIELD, what, None)],
    )
    return MergeOutcome(updated, moved, stayed)
