"""Merging duplicate incidents, with a preview and undo (WP-046b S2; REQ-INC-088, -150).

The duplicate goes to the system status `merged` with a `merged_into` link to the survivor; it
stays readable, its history, audit and SLA records stay with it (coordinator). What it brings:

- its conversation, by reference: the survivor's timeline lists it, each entry under its own
  visibility, re-checked against the duplicate (lane B; never copied, so nothing is re-sealed);
- its children, which become the survivor's (one level: refused when the survivor is a child);
- its requester and the people it was raised for, as followers with portal access only when both
  records are in the same department; anyone else is listed as not added (coordinator).

Merging can widen who sees the duplicate: the preview counts the people who can see the
survivor and not the duplicate (staff, by their own access; and the survivor's requesters, who
gain the duplicate's public side), counts only, and the merge asks the person to confirm when
any (lane B). What moved is kept in the duplicate's history (`merge`), so undo can put it back
exactly or refuse.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied
from app.modules import identity_access
from app.modules.identity_access import Subject
from app.modules.work_items.domain.conversation import FollowReason
from app.modules.work_items.domain.lifecycle import (
    FINAL_CATEGORIES,
    DefaultStatus,
    StatusCategory,
    WorkItemAction,
)
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem, WorkItemLink
from app.modules.work_items.service import followers, parts
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import UNDO_MERGE
from app.shared.history import Change, FieldChange, Source

MERGED = DefaultStatus.MERGED.value
MERGE_FIELD = "merge"  # the history change that records what moved
AUDIENCE_MAX = 2000  # staff checked one by one for the preview; beyond, "at least"


@dataclass(frozen=True)
class MergePreview:
    """What a merge would do, in counts and IDs the person may see (never names of others)."""

    duplicate: WorkItem
    survivor: WorkItem
    children: list[uuid.UUID]
    followers_added: list[uuid.UUID]
    followers_not_added: list[uuid.UUID]
    staff_newly_seeing: int
    requesters_newly_seeing: int
    audience_complete: bool  # False: more staff than AUDIENCE_MAX, the count is "at least"

    @property
    def widens(self) -> bool:
        """Whether anyone would see the duplicate who cannot now."""
        return bool(self.staff_newly_seeing or self.requesters_newly_seeing)


@dataclass(frozen=True)
class MergeOutcome:
    """The duplicate after the merge or undo, and what moved (or stayed)."""

    record: WorkItem
    moved: list[uuid.UUID] = field(default_factory=list)
    into_id: uuid.UUID | None = None  # the survivor
    stayed: list[uuid.UUID] = field(default_factory=list)


def _open(record: WorkItem) -> bool:
    return StatusCategory(record.status_category) not in FINAL_CATEGORIES


async def _children(session: AsyncSession, parent_id: uuid.UUID) -> list[WorkItemLink]:
    return list(
        await session.scalars(
            select(WorkItemLink)
            .where(
                WorkItemLink.target_id == parent_id,
                WorkItemLink.kind == LinkKind.CHILD_OF.value,
                WorkItemLink.deleted_at.is_(None),
            )
            .order_by(WorkItemLink.created_at, WorkItemLink.id)
        )
    )


async def _is_child(session: AsyncSession, record_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(WorkItemLink.id).where(
            WorkItemLink.source_id == record_id,
            WorkItemLink.kind == LinkKind.CHILD_OF.value,
            WorkItemLink.deleted_at.is_(None),
        )
    )
    return found is not None


async def _portal_people(session: AsyncSession, record: WorkItem) -> set[uuid.UUID]:
    """Who sees the record's public side in the portal: requesters and access-granting follows."""
    people = {u for u in (record.requester_id, record.on_behalf_of_id) if u is not None}
    people |= {f.user_id for f in await followers.of_record(session, record.id) if f.grants_access}
    return people


async def _staff_newly_seeing(
    session: AsyncSession,
    holders: items.PermissionHolders,
    duplicate: WorkItem,
    survivor: WorkItem,
) -> tuple[int, bool]:
    """Staff who may view the survivor but not the duplicate, and whether all were checked.

    Each by their own access (the same check their screens make).
    """
    tenant = duplicate.tenant_id
    staff = await holders.holders(
        session, tenant, INCIDENT.permission("view"), limit=AUDIENCE_MAX + 1
    )
    count = 0
    for user_id, _ in staff[:AUDIENCE_MAX]:
        who = await identity_access.subject_for(session, tenant, user_id)
        if await items.may(session, who, INCIDENT, "view", survivor.id) and not await items.may(
            session, who, INCIDENT, "view", duplicate.id
        ):
            count += 1
    return count, len(staff) <= AUDIENCE_MAX


async def _checked(
    session: AsyncSession, subject: Subject, duplicate_id: uuid.UUID, survivor_id: uuid.UUID
) -> tuple[WorkItem, WorkItem, list[WorkItemLink]]:
    """Both incidents, editable by the person, open; the survivor no child if children move."""
    if duplicate_id == survivor_id:
        raise items.field_errors([("into_id", "cannot_merge_itself")])
    duplicate = await items.record_for_action(session, subject, INCIDENT, "edit", duplicate_id)
    survivor = await items.record_for_action(session, subject, INCIDENT, "edit", survivor_id)
    for record in (duplicate, survivor):
        if not _open(record):
            raise Conflict(code="record_closed", params={"display_id": record.display_id})
    children = await _children(session, duplicate.id)
    if children and await _is_child(session, survivor.id):
        # One level: the duplicate's children cannot go under a record that is itself a child.
        raise Conflict(code="survivor_is_a_child", params={"display_id": survivor.display_id})
    if any(link.source_id == survivor.id for link in children):
        raise Conflict(code="survivor_is_a_child", params={"display_id": survivor.display_id})
    return duplicate, survivor, children


async def preview(
    session: AsyncSession,
    subject: Subject,
    duplicate_id: uuid.UUID,
    survivor_id: uuid.UUID,
    *,
    holders: items.PermissionHolders,
) -> MergePreview:
    """What merging the duplicate into the survivor would do (nothing is changed)."""
    duplicate, survivor, children = await _checked(session, subject, duplicate_id, survivor_id)
    same_department = (
        duplicate.department_id is not None and duplicate.department_id == survivor.department_id
    )
    theirs = {u for u in (duplicate.requester_id, duplicate.on_behalf_of_id) if u is not None}
    already = await _portal_people(session, survivor)
    incoming = sorted(theirs - already, key=str)
    survivor_people = already - await _portal_people(session, duplicate)
    staff, complete = await _staff_newly_seeing(session, holders, duplicate, survivor)
    return MergePreview(
        duplicate=duplicate,
        survivor=survivor,
        children=[link.source_id for link in children],
        followers_added=incoming if same_department else [],
        followers_not_added=[] if same_department else incoming,
        staff_newly_seeing=staff,
        requesters_newly_seeing=len(survivor_people),
        audience_complete=complete,
    )


async def merge(  # noqa: PLR0913 - both incidents, the version, the confirmation and the source
    session: AsyncSession,
    subject: Subject,
    duplicate_id: uuid.UUID,
    survivor_id: uuid.UUID,
    *,
    expected_version: int,
    confirm_wider_audience: bool,
    holders: items.PermissionHolders,
    source: Source,
) -> MergeOutcome:
    """Merge the duplicate into the survivor.

    409 when either is closed, or when the audience widens and the person has not confirmed it.
    """
    shown = await preview(session, subject, duplicate_id, survivor_id, holders=holders)
    duplicate, survivor = shown.duplicate, shown.survivor
    if duplicate.version != expected_version:
        raise await items.stale_record(session, duplicate, expected_version)
    if shown.widens and not confirm_wider_audience:
        raise Conflict(
            code="merge_widens_audience",
            params={
                "staff": str(shown.staff_newly_seeing),
                "requesters": str(shown.requesters_newly_seeing),
                "complete": str(shown.audience_complete).lower(),
            },
        )
    links = parts.LinkRepository(session)
    for link in await _children(session, duplicate.id):
        child = await session.get(WorkItem, link.source_id)
        if child is None:  # pragma: no cover - a link always has its records (FK)
            continue
        removed = await links.soft_delete(link.id, expected_version=link.version)
        await parts.link_recorded(session, child, duplicate, removed, "child_removed", source)
        added = await links.add(
            WorkItemLink(source_id=child.id, target_id=survivor.id, kind=LinkKind.CHILD_OF.value)
        )
        await parts.link_recorded(session, child, survivor, added, "child_added", source)
    followed: list[uuid.UUID] = []
    for user_id in shown.followers_added:
        _, changed = await followers.follow(
            session,
            survivor,
            user_id,
            reason=FollowReason.ADDED,
            grants_access=True,
            source=source,
        )
        if changed:
            followed.append(user_id)
    merged = await links.add(
        WorkItemLink(source_id=duplicate.id, target_id=survivor.id, kind=LinkKind.MERGED_INTO.value)
    )
    await parts.link_recorded(session, duplicate, survivor, merged, "child_added", source)
    what: dict[str, Any] = {
        "into": str(survivor.id),
        "into_display_id": survivor.display_id,
        "status": duplicate.status,
        "children": [str(c) for c in shown.children],
        "followers": [str(u) for u in followed],
    }
    fresh = await session.get(WorkItem, duplicate.id, populate_existing=True)
    assert fresh is not None  # noqa: S101 - just read above
    updated = await items.set_status(
        session,
        INCIDENT,
        fresh,
        WorkItemAction.MERGE,
        target=MERGED,
        expected_version=fresh.version,
        source=source,
        extra=[Change(MERGE_FIELD, None, what)],
    )
    return MergeOutcome(updated, moved=list(shown.children), into_id=survivor.id)


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


async def _child_back(
    session: AsyncSession,
    link: WorkItemLink,
    survivor: WorkItem,
    duplicate: WorkItem,
    source: Source,
) -> None:
    """A child the merge moved goes back under the duplicate, with history on all three."""
    child = await session.get(WorkItem, link.source_id)
    if child is None:  # pragma: no cover - a link always has its records (FK)
        return
    links = parts.LinkRepository(session)
    gone = await links.soft_delete(link.id, expected_version=link.version)
    await parts.link_recorded(session, child, survivor, gone, "child_removed", source)
    back = await links.add(
        WorkItemLink(source_id=child.id, target_id=duplicate.id, kind=LinkKind.CHILD_OF.value)
    )
    await parts.link_recorded(session, child, duplicate, back, "child_added", source)


def _not_exact(duplicate: WorkItem, why: str) -> Conflict:
    return Conflict(
        code="merge_undo_not_exact", params={"display_id": duplicate.display_id, "why": why}
    )


async def undo_merge(
    session: AsyncSession,
    subject: Subject,
    duplicate_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> MergeOutcome:
    """Put a merged incident back exactly as it was, or refuse (lane B).

    Needs `incidents.undo_merge` (the route also asks for a recent sign-in). Refused with
    `merge_undo_not_exact` when the survivor has since closed, merged or been converted, or a
    child that moved has since been linked elsewhere: a partial undo would leave records where
    nobody put them.
    """
    duplicate = await items.record_for_action(session, subject, INCIDENT, "view", duplicate_id)
    if not await items.may(session, subject, INCIDENT, UNDO_MERGE, duplicate.id):
        raise PermissionDenied(params={"permission": INCIDENT.permission(UNDO_MERGE)})
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
    survivor = await items.record_for_action(session, subject, INCIDENT, "edit", link.target_id)
    if not _open(survivor):
        raise _not_exact(duplicate, "survivor_closed")
    wanted = {uuid.UUID(i) for i in what.get("children", [])}
    now_under = {c.source_id: c for c in await _children(session, survivor.id)}
    if not wanted <= set(now_under):
        raise _not_exact(duplicate, "children_moved")
    links = parts.LinkRepository(session)
    removed = await links.soft_delete(link.id, expected_version=link.version)
    await parts.link_recorded(session, duplicate, survivor, removed, "child_removed", source)
    for child_id in sorted(wanted, key=str):
        await _child_back(session, now_under[child_id], survivor, duplicate, source)
    for user in what.get("followers", []):
        row = await followers.current(session, survivor.id, uuid.UUID(user))
        if row is not None:  # since removed by someone: nothing to take back
            await followers.unfollow(session, survivor, row, source=source)
    fresh = await session.get(WorkItem, duplicate.id, populate_existing=True)
    assert fresh is not None  # noqa: S101 - just read above
    updated = await items.set_status(
        session,
        INCIDENT,
        fresh,
        WorkItemAction.UNDO_MERGE,
        target=str(what.get("status") or DefaultStatus.NEW.value),
        expected_version=fresh.version,
        source=source,
        extra=[Change(MERGE_FIELD, what, None)],
    )
    return MergeOutcome(updated, moved=sorted(wanted, key=str), into_id=survivor.id)
