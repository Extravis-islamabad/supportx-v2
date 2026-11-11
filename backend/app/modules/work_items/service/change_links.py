"""A change made from another record (WP-045a D6; REQ-CHG-002).

From an incident, a service request, a problem or a release the person may see: the form is
pre-filled from it (`prefill`, every value still editable, AC3), and the new change is linked
to it as `change_for` (the change -> its source), recorded on both records (AC1). CIs and
assets come with the CMDB (lane B's WP-049/050).
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.identity_access import Subject
from app.modules.work_items.domain.changes import REVIEW_SECTIONS
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemLink
from app.modules.work_items.service import parts
from app.modules.work_items.service import work_items as items
from app.shared.history import Source

SOURCES = frozenset(
    {
        WorkItemTypeCode.INCIDENT,
        WorkItemTypeCode.SERVICE_REQUEST,
        WorkItemTypeCode.PROBLEM,
        WorkItemTypeCode.RELEASE,
    }
)


async def _source(session: AsyncSession, subject: Subject, record_id: uuid.UUID) -> WorkItem:
    """A record a change may be made from, which the subject may see (else 404, never why)."""
    found = await session.get(WorkItem, record_id)
    code = WorkItemTypeCode(found.type) if found is not None else None
    if found is None or code not in SOURCES:
        raise NotFound(code="change_source_not_found")
    return await items.visible_record(session, subject, TYPES[code], record_id)


async def prefill(session: AsyncSession, subject: Subject, record_id: uuid.UUID) -> dict[str, Any]:
    """A new change's starting values from the record (REQ-CHG-002); the form may edit each."""
    source = await _source(session, subject, record_id)
    return {
        "subject": source.subject,
        "description": source.description,
        "requester_id": source.requester_id,
        "impact": source.impact,
        "urgency": source.urgency,
        "site_id": source.site_id,
        "from_record_id": source.id,
    }


async def link_new(
    session: AsyncSession,
    subject: Subject,
    change: WorkItem,
    record_id: uuid.UUID,
    *,
    source: Source,
) -> WorkItemLink:
    """Link a just-made change to the record it was made from, with history on both (AC1)."""
    origin = await _source(session, subject, record_id)
    link = await parts.LinkRepository(session).add(
        WorkItemLink(source_id=change.id, target_id=origin.id, kind=LinkKind.CHANGE_FOR.value)
    )
    await parts.link_recorded(session, change, origin, link, "child_added", source)
    return link


# What a copy may bring besides its fields (REQ-CHG-003): CIs, services, tasks and checklists
# come with their parts' sessions (CMDB, WP-045d).
COPY_PARTS = frozenset({"plans", "roles"})


async def copy_change(  # noqa: PLR0913 - the copy and its context, explicit
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    parts_chosen: frozenset[str],
    source: Source,
    holders: Any,  # noqa: ANN401 - identity's PermissionHolders, passed through to create
) -> WorkItem:
    """A new change from this one (REQ-CHG-003): its fields, type and reason, and what is chosen.

    It starts at its path's first stage with no approvals, history or schedule of the
    original (AC1); its history names the source (AC2); plans come as editable text (AC3).
    """
    wtype = TYPES[WorkItemTypeCode.CHANGE]
    original = await items.visible_record(session, subject, wtype, record_id)
    values: dict[str, Any] = {n: getattr(original, n) for n in items.COPIED_FIELDS}
    values["custom"] = dict(original.custom or {})
    own = await items.details(session, subject, wtype, original.id)
    if own.details is not None:
        values |= {n: getattr(own.details, n) for n in ("change_type", "change_reason")}
    values = {n: v for n, v in values.items() if v is not None}
    made = await items.create(session, subject, wtype, values, source=source, holders=holders)
    record = made.record
    await items.record_copied_from(session, record, original, source=source)
    if "plans" in parts_chosen:
        _, sections = await items.plan_sections(session, subject, wtype, original.id)
        for name, row in sections:
            # The plans, never the original's review: a copy has not been implemented yet.
            if name in REVIEW_SECTIONS:
                continue
            if row is not None and row.content:
                await items.put_plan_section(
                    session,
                    subject,
                    wtype,
                    record.id,
                    name,
                    content=row.content,
                    expected_version=0,
                    source=source,
                    copying=True,  # the copy's own plan, not an edit of a standard one
                )
    if "roles" in parts_chosen:
        for role, (users, groups) in (await items.holders_of(session, original.id)).items():
            if role in {"requester", "change_owner"} or not (users or groups):
                continue  # the copy's own requester and owner
            fresh = await items.visible_record(session, subject, wtype, record.id)
            await items.set_role(
                session,
                subject,
                wtype,
                record.id,
                role,
                user_ids=users,
                group_ids=groups,
                expected_version=fresh.version,
                source=source,
                holders=holders,
            )
    return await items.visible_record(session, subject, wtype, record.id)


# --- child changes and releases (WP-045d S1; REQ-CHG-096) ----------------------------------------

CHILD_TYPES = frozenset({WorkItemTypeCode.CHANGE, WorkItemTypeCode.RELEASE})
CHANGE = TYPES[WorkItemTypeCode.CHANGE]


def _not_closed(change: WorkItem) -> None:
    """A closed or canceled change is locked (REQ-CHG-097): its children stay as they are."""
    if items.is_closed(change):
        raise Conflict(code=items.RECORD_CLOSED, params={"status": change.status})


async def _parent_of(session: AsyncSession, record_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(WorkItemLink.target_id).where(
            WorkItemLink.source_id == record_id,
            WorkItemLink.kind == LinkKind.PART_OF_CHANGE.value,
            WorkItemLink.deleted_at.is_(None),
        )
    )


async def children(
    session: AsyncSession, subject: Subject, change_id: uuid.UUID
) -> tuple[WorkItem, list[tuple[WorkItemLink, WorkItem]]]:
    """The change's child changes and releases (the ones you may see), by number."""
    change = await items.visible_record(session, subject, CHANGE, change_id)
    rows = await session.execute(
        select(WorkItemLink, WorkItem)
        .join(WorkItem, WorkItem.id == WorkItemLink.source_id)
        .where(
            WorkItemLink.target_id == change.id,
            WorkItemLink.kind == LinkKind.PART_OF_CHANGE.value,
            WorkItemLink.deleted_at.is_(None),
            WorkItem.deleted_at.is_(None),
        )
        .order_by(WorkItem.display_id)
    )
    found: list[tuple[WorkItemLink, WorkItem]] = []
    for link, child in rows:
        try:
            await items.visible_record(
                session, subject, TYPES[WorkItemTypeCode(child.type)], child.id
            )
        except NotFound:
            continue  # a child you may not see is never listed (nor named)
        found.append((link, child))
    return change, found


async def add_child(
    session: AsyncSession,
    subject: Subject,
    change_id: uuid.UUID,
    child_id: uuid.UUID,
    *,
    source: Source,
) -> WorkItemLink:
    """Make a change or a release part of this change (editing the change; seeing the child).

    One parent each, never the change itself or one of its own parents (no loops). Closing the
    change then waits for it (the guard, REQ-CHG-096).
    """
    change = await items.record_for_action(session, subject, CHANGE, "edit", change_id)
    _not_closed(change)
    found = await session.get(WorkItem, child_id)
    code = WorkItemTypeCode(found.type) if found is not None else None
    if found is None or code not in CHILD_TYPES or found.deleted_at is not None:
        raise items.field_errors([("child_id", "record_not_found")])
    try:
        child = await items.visible_record(session, subject, TYPES[code], child_id)
    except NotFound as error:
        raise items.field_errors([("child_id", "record_not_found")]) from error
    if child.id == change.id:
        raise items.field_errors([("child_id", "cannot_link_itself")])
    if await _parent_of(session, child.id) is not None:
        raise items.field_errors([("child_id", "already_linked")])
    ancestor = await _parent_of(session, change.id)
    seen = {change.id}
    while ancestor is not None and ancestor not in seen:
        if ancestor == child.id:
            raise items.field_errors([("child_id", "change_would_loop")])
        seen.add(ancestor)
        ancestor = await _parent_of(session, ancestor)
    link = await parts.LinkRepository(session).add(
        WorkItemLink(source_id=child.id, target_id=change.id, kind=LinkKind.PART_OF_CHANGE.value)
    )
    await parts.link_recorded(session, change, child, link, "child_added", source)
    return link


async def remove_child(
    session: AsyncSession,
    subject: Subject,
    change_id: uuid.UUID,
    link_id: uuid.UUID,
    *,
    source: Source,
) -> None:
    """Take a child off the change (kept as history; the link is soft-deleted)."""
    change = await items.record_for_action(session, subject, CHANGE, "edit", change_id)
    _not_closed(change)
    link = await session.scalar(
        select(WorkItemLink).where(
            WorkItemLink.id == link_id,
            WorkItemLink.target_id == change.id,
            WorkItemLink.kind == LinkKind.PART_OF_CHANGE.value,
            WorkItemLink.deleted_at.is_(None),
        )
    )
    if link is None:
        raise NotFound(code="link_not_found")
    child = await session.get(WorkItem, link.source_id)
    removed = await parts.LinkRepository(session).soft_delete(
        link.id, expected_version=link.version
    )
    if child is not None:
        await parts.link_recorded(session, change, child, removed, "child_removed", source)
