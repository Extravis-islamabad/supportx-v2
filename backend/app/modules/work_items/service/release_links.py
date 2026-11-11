"""Parent and sub-releases (WP-058a s5; REQ-REL-037).

A release has at most one parent, linked as `sub_release_of` (child -> parent) in the shared
links table. Loops are refused (AC1). Both records keep the link in their history, through the
parts' own history helper, so the timelines read the same as for any link. The release guard
refuses moving a parent into deployment while a sub-release has not passed testing (AC2), naming
it. The parent's screens refresh when a sub-release moves (AC3, service/realtime.py).

Links of incidents, requests and problems to a release (REQ-REL-034) wait for lane A's
cross-type links (#211).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.stages import Move
from app.modules.work_items.domain.types import CHANGE, RELEASE, WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemLink
from app.modules.work_items.service import stages as stage_service
from app.shared.history import Change, Source

SUB = LinkKind.SUB_RELEASE_OF.value
SUB_RELEASES_NOT_TESTED = "sub_releases_not_tested"  # a guard refusal code
# The stage a parent may not enter before its sub-releases have passed testing, and the stage
# they must be past.
GUARDED_STAGE, PASSED_STAGE = "deployment", "testing"
MAX_DEPTH = 20


@dataclass(frozen=True)
class SubRelease:
    """A sub-release as its parent lists it (only what the viewer may see)."""

    id: uuid.UUID
    visible: bool
    display_id: str | None
    subject: str | None
    stage: str | None
    status: str | None


async def parent_of(session: AsyncSession, record_id: uuid.UUID) -> uuid.UUID | None:
    """The release's parent, if any."""
    return await session.scalar(
        select(WorkItemLink.target_id).where(
            WorkItemLink.source_id == record_id,
            WorkItemLink.kind == SUB,
            WorkItemLink.deleted_at.is_(None),
        )
    )


async def children_of(session: AsyncSession, record_id: uuid.UUID) -> list[WorkItem]:
    """The release's sub-releases, oldest link first."""
    return list(
        await session.scalars(
            select(WorkItem)
            .join(WorkItemLink, WorkItemLink.source_id == WorkItem.id)
            .where(
                WorkItemLink.target_id == record_id,
                WorkItemLink.kind == SUB,
                WorkItemLink.deleted_at.is_(None),
                WorkItem.deleted_at.is_(None),
            )
            .order_by(WorkItemLink.created_at, WorkItemLink.id)
        )
    )


async def _ancestors(session: AsyncSession, record_id: uuid.UUID) -> list[uuid.UUID]:
    found: list[uuid.UUID] = []
    current: uuid.UUID | None = record_id
    while current is not None and len(found) <= MAX_DEPTH:
        current = await parent_of(session, current)
        if current is not None:
            found.append(current)
    return found


# Links whose target holds their source: a sub-release in its parent, a child change or a release
# in the change it is part of (lane A's 0133), a change in its release (0138).
CONTAINED_IN = (SUB, LinkKind.PART_OF_CHANGE.value, LinkKind.IN_RELEASE.value)
CHANGE_WOULD_LOOP = "change_would_loop"  # lane A's code and label (WP-045d)


async def holds(session: AsyncSession, outer: uuid.UUID, inner: uuid.UUID) -> bool:
    """Whether `outer` already holds `inner`, through any chain of holding links (bounded).

    Shared with change_links.add_child (lane A, WP-046a S1 PR 2), which refuses the same loops.
    """
    seen: set[uuid.UUID] = {inner}
    level = [inner]
    for _ in range(MAX_DEPTH):
        if not level:
            return False
        ups = set(
            await session.scalars(
                select(WorkItemLink.target_id).where(
                    WorkItemLink.source_id.in_(level),
                    WorkItemLink.kind.in_(CONTAINED_IN),
                    WorkItemLink.deleted_at.is_(None),
                )
            )
        )
        if outer in ups:
            return True
        level = list(ups - seen)
        seen |= ups
    return False


async def sub_releases(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[SubRelease]:
    """The sub-releases of a release you may see, with their stage and status (AC3)."""
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    await items.visible_record(session, subject, wtype, record_id)
    shown: list[SubRelease] = []
    for child in await children_of(session, record_id):
        seen = await items.may(session, subject, wtype, "view", child.id)
        shown.append(
            SubRelease(
                child.id,
                seen,
                child.display_id if seen else None,
                child.subject if seen else None,
                child.stage if seen else None,
                child.status if seen else None,
            )
        )
    return shown


async def set_parent(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    *,
    source: Source,
) -> uuid.UUID | None:
    """Make the release a sub-release of `parent_id` (None: of nothing); loops are refused."""
    from app.modules.work_items.service import parts  # noqa: PLC0415 - cycle
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    if wtype.code is not RELEASE.code:
        raise NotFound(code="work_item_not_found")
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    current = await session.scalar(
        select(WorkItemLink).where(
            WorkItemLink.source_id == record_id,
            WorkItemLink.kind == SUB,
            WorkItemLink.deleted_at.is_(None),
        )
    )
    if (current.target_id if current else None) == parent_id:
        return parent_id
    parent = None
    if parent_id is not None:
        if parent_id == record_id or record_id in await _ancestors(session, parent_id):
            raise items.field_errors([("parent_id", "would_loop")])  # AC1
        try:
            parent = await items.visible_record(session, subject, wtype, parent_id)
        except NotFound as error:
            raise items.field_errors([("parent_id", "record_not_found")]) from error
    if current is not None:
        before = await session.get(WorkItem, current.target_id)
        removed = await parts.LinkRepository(session).soft_delete(
            current.id, expected_version=current.version
        )
        if before is not None:
            await _both(
                session,
                child=record,
                parent=before,
                link=removed,
                kind="child_removed",
                source=source,
            )
    if parent is not None:
        link = await parts.LinkRepository(session).add(
            WorkItemLink(source_id=record_id, target_id=parent.id, kind=SUB)
        )
        await _both(
            session, child=record, parent=parent, link=link, kind="child_added", source=source
        )
    return parent_id


async def _both(  # noqa: PLR0913 - both records, the link and what happened, explicit
    session: AsyncSession,
    *,
    child: WorkItem,
    parent: WorkItem,
    link: WorkItemLink,
    kind: str,
    source: Source,
) -> None:
    """History and signals on both records, as for any link (REQ-INC-084)."""
    from app.modules.work_items.service import parts  # noqa: PLC0415 - cycle

    for this, that in ((child, parent), (parent, child)):
        value = {"kind": SUB, "id": str(that.id), "display_id": that.display_id}
        changes = (
            [Change("link", None, value)]
            if kind == "child_added"
            else [Change("link", value, None)]
        )
        await parts.recorded(session, this, "link", link.id, kind, changes, source)  # type: ignore[arg-type]  # one of the part kinds


def _passed(child: WorkItem, order: list[str]) -> bool:
    """Past testing on its path, or finished (closed or canceled)."""
    if StatusCategory(child.status_category) in FINAL_CATEGORIES:
        return True
    if child.stage not in order or PASSED_STAGE not in order:
        return True  # a path without testing has nothing to pass
    return order.index(str(child.stage)) > order.index(PASSED_STAGE)


async def sub_release_refusals(
    session: AsyncSession, wtype: WorkItemType, record: WorkItem, move: Move
) -> list[stage_service.Refusal]:
    """A parent may not enter deployment while a sub-release has not passed testing (AC2)."""
    if GUARDED_STAGE not in move.entered:
        return []
    model = await stage_service.load_model(session, wtype, record.lifecycle_version)
    behind = []
    for child in await children_of(session, record.id):
        order = list(model.path(str(child.stage_path)).stages) if child.stage_path else []
        if not _passed(child, order):
            behind.append(child.display_id)
    if not behind:
        return []
    return [stage_service.Refusal(SUB_RELEASES_NOT_TESTED, {"releases": ", ".join(behind)})]


# --- changes in a release (WP-058b S1; REQ-REL-033) ---------------------------------------------

IN_RELEASE = LinkKind.IN_RELEASE.value
CHANGE_IN_OTHER_RELEASE = "change_in_other_release"  # AC2's refusal code (names the release)


@dataclass(frozen=True)
class ReleaseChange:
    """A change in a release as the release lists it: details only for those who may see it."""

    id: uuid.UUID
    link_id: uuid.UUID
    seen: bool
    display_id: str | None
    subject: str | None
    stage: str | None
    status: str | None
    status_category: str | None


async def _change_links(session: AsyncSession, release_id: uuid.UUID) -> list[WorkItemLink]:
    return list(
        await session.scalars(
            select(WorkItemLink)
            .where(
                WorkItemLink.target_id == release_id,
                WorkItemLink.kind == IN_RELEASE,
                WorkItemLink.deleted_at.is_(None),
            )
            .order_by(WorkItemLink.created_at)
        )
    )


async def release_changes(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[ReleaseChange]:
    """The changes in a release you may see (AC3: one you may not see shows only that it is)."""
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    if wtype.code is not RELEASE.code:
        raise NotFound(code="work_item_not_found")
    await items.visible_record(session, subject, wtype, record_id)
    shown: list[ReleaseChange] = []
    for link in await _change_links(session, record_id):
        change = await session.get(WorkItem, link.source_id)
        if change is None or change.deleted_at is not None:
            continue
        seen = await items.may(session, subject, CHANGE, "view", change.id)
        shown.append(
            ReleaseChange(
                change.id,
                link.id,
                seen,
                change.display_id if seen else None,
                change.subject if seen else None,
                change.stage if seen else None,
                change.status if seen else None,
                change.status_category if seen else None,
            )
        )
    return shown


async def _open_release_of(
    session: AsyncSession, change_id: uuid.UUID
) -> tuple[WorkItemLink, WorkItem] | None:
    """The open release a change is already in (closed or canceled ones do not hold it)."""
    rows = await session.execute(
        select(WorkItemLink, WorkItem)
        .join(WorkItem, WorkItem.id == WorkItemLink.target_id)
        .where(
            WorkItemLink.source_id == change_id,
            WorkItemLink.kind == IN_RELEASE,
            WorkItemLink.deleted_at.is_(None),
            WorkItem.deleted_at.is_(None),
        )
    )
    for link, release in rows:
        if StatusCategory(release.status_category) not in FINAL_CATEGORIES:
            return link, release
    return None


async def add_change(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    change_id: uuid.UUID,
    *,
    source: Source,
) -> WorkItemLink:
    """Put a change in the release; one open release per change (AC2), history on both (AC1).

    The change is locked first, so two releases taking it at once cannot both succeed.
    """
    from app.modules.work_items.service import parts  # noqa: PLC0415 - cycle
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    if wtype.code is not RELEASE.code:
        raise NotFound(code="work_item_not_found")
    release = await items.record_for_action(session, subject, wtype, "edit", record_id)
    try:
        change = await items.visible_record(session, subject, CHANGE, change_id)
    except NotFound as error:
        raise items.field_errors([("change_id", "record_not_found")]) from error
    await session.get(WorkItem, change.id, with_for_update=True)
    # The change already holds this release (the release is part of it, directly or through
    # its parents or child changes): putting the change in the release would loop (lane A).
    if await holds(session, change.id, release.id):
        raise items.field_errors([("change_id", CHANGE_WOULD_LOOP)])
    held = await _open_release_of(session, change.id)
    if held is not None:
        if held[1].id == release.id:
            return held[0]  # already in this release: nothing to do
        raise items.field_errors(
            [("change_id", CHANGE_IN_OTHER_RELEASE)],
            change_id={"release": held[1].display_id},
        )
    link = await parts.LinkRepository(session).add(
        WorkItemLink(source_id=change.id, target_id=release.id, kind=IN_RELEASE)
    )
    await _changed(
        session, change=change, release=release, link=link, kind="child_added", source=source
    )
    return link


async def remove_change(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    change_id: uuid.UUID,
    *,
    source: Source,
) -> None:
    """Take a change out of the release, with history on both."""
    from app.modules.work_items.service import parts  # noqa: PLC0415 - cycle
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    if wtype.code is not RELEASE.code:
        raise NotFound(code="work_item_not_found")
    release = await items.record_for_action(session, subject, wtype, "edit", record_id)
    link = next(
        (li for li in await _change_links(session, release.id) if li.source_id == change_id), None
    )
    change = await session.get(WorkItem, change_id)
    if link is None or change is None:
        raise NotFound(code="link_not_found")
    removed = await parts.LinkRepository(session).soft_delete(
        link.id, expected_version=link.version
    )
    await _changed(
        session, change=change, release=release, link=removed, kind="child_removed", source=source
    )


async def _changed(  # noqa: PLR0913 - both records, the link and what happened, explicit
    session: AsyncSession,
    *,
    change: WorkItem,
    release: WorkItem,
    link: WorkItemLink,
    kind: str,
    source: Source,
) -> None:
    """History and signals on both records, one label pair (REQ-INC-087)."""
    from app.modules.work_items.service import parts  # noqa: PLC0415 - cycle

    for this, that in ((change, release), (release, change)):
        value = {"kind": IN_RELEASE, "id": str(that.id), "display_id": that.display_id}
        changes = (
            [Change("link", None, value)]
            if kind == "child_added"
            else [Change("link", value, None)]
        )
        await parts.recorded(session, this, "link", link.id, kind, changes, source)  # type: ignore[arg-type]  # one of the part kinds
