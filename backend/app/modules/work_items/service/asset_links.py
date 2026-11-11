"""Assets linked to work items (REQ-AST-025; the plan the coordinator approved 2026-11-10).

A record lists the assets it is about: the requester's laptop on an incident, the monitor a
request is for. Work items keep their own link table and never read asset tables (CLAUDE.md rule
e): `assets.can_see` before a person links one, `assets.asset_refs` to name them, so an asset
that was removed or that the reader may not see comes back marked, never named.

- Linking needs the record's edit right and the `assets` feature; at most `MAX_LINKS` per record.
- Each link and unlink is a history line naming the asset by its tag and name, and an outbox
  event with IDs only (the record's Assets section follows live).
- An e-mailed incident gets the requester's asset when the tenant says so and they hold exactly
  one (AC2).
- `linked_asset_ids_select` is the assets module's "linked to my tickets" scope (D-153): a sync
  SQL builder it registers, so assets never imports work_items or names its tables.
- For the asset record's linked records (WP-049b S4, lane B): `linked_counts` and `linked_page`
  over the records the reader may see only (a hidden record is neither counted nor listed: the
  coordinator, 2026-11-11), `asset_ids_of` for a record's live links, and
  `repoint_asset_links` for an asset merge.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound
from app.modules import assets, licensing
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.events import WorkItemAssetLinkChanged
from app.modules.work_items.infra.models import WorkItem, WorkItemAsset
from app.modules.work_items.service import work_items as items
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

FEATURE = "assets"
MAX_LINKS = 20  # per record: a request is about a few things, never an inventory
RECORD_TYPE = "work_item"
FIELD = "asset"  # the history line's field: "Asset: + AST-12 Dell laptop"
# D-153 (the coordinator, 2026-11-10): records still being worked count for "my tickets";
# closed, canceled and trashed ones do not.
_WORKING = (StatusCategory.OPEN.value, StatusCategory.PAUSED.value, StatusCategory.RESOLVED.value)


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


class AssetLinkRepository(Repository[WorkItemAsset]):
    """Asset links of the session's tenant."""

    model = WorkItemAsset


def _label(ref: assets.AssetRef | None) -> str:
    """How history names an asset: its tag and name when known, never its ID alone."""
    if ref is None or ref.tag is None:
        return ""
    return f"{ref.tag} {ref.name}" if ref.name else ref.tag


async def _live(session: AsyncSession, record_id: uuid.UUID) -> list[WorkItemAsset]:
    rows = await session.scalars(
        select(WorkItemAsset)
        .where(WorkItemAsset.work_item_id == record_id, WorkItemAsset.deleted_at.is_(None))
        .order_by(WorkItemAsset.created_at, WorkItemAsset.id)
    )
    return list(rows)


async def linked(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[tuple[WorkItemAsset, assets.AssetRef]]:
    """The record's linked assets, each as the reader may see it (gone and hidden marked)."""
    await items.visible_record(session, subject, wtype, record_id)
    rows = await _live(session, record_id)
    refs = await assets.asset_refs(session, subject, [r.asset_id for r in rows])
    return [(row, refs[row.asset_id]) for row in rows]


async def _write(  # noqa: PLR0913 - the link, its source and when it was made, explicit
    session: AsyncSession,
    record: WorkItem,
    asset_id: uuid.UUID,
    ref: assets.AssetRef | None,
    *,
    source: Source,
    at_creation: bool = False,
) -> WorkItemAsset:
    row = await AssetLinkRepository(session).add(
        WorkItemAsset(work_item_id=record.id, asset_id=asset_id, source=source)
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_added",
        changes=[Change(FIELD, None, _label(ref))],
        source=source,
    )
    await record_event(
        session,
        WorkItemAssetLinkChanged(
            work_item_id=record.id, asset_id=asset_id, change="added", at_creation=at_creation
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return row


async def link(  # noqa: PLR0913 - the record, the assets and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    asset_ids: Sequence[uuid.UUID],
    *,
    source: Source,
) -> list[WorkItemAsset]:
    """Link assets the person may see; ones already linked are left as they are."""
    await licensing.require_feature(_tenant(session), FEATURE)
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    return await attach(session, subject, record, asset_ids, source=source)


async def link_new(
    session: AsyncSession,
    subject: Subject,
    record: WorkItem,
    asset_ids: Sequence[uuid.UUID],
    *,
    source: Source,
) -> list[WorkItemAsset]:
    """Link assets to a record just created (its create body's `asset_ids`)."""
    await licensing.require_feature(_tenant(session), FEATURE)
    return await attach(session, subject, record, asset_ids, source=source, at_creation=True)


async def attach(  # noqa: PLR0913 - the record, the assets and how they came, explicit
    session: AsyncSession,
    subject: Subject,
    record: WorkItem,
    asset_ids: Sequence[uuid.UUID],
    *,
    source: Source,
    at_creation: bool = False,
) -> list[WorkItemAsset]:
    """Link assets to a record already checked (its create, or `link`): visibility and the cap."""
    wanted = list(dict.fromkeys(asset_ids))
    if not wanted:
        return []
    have = {r.asset_id for r in await _live(session, record.id)}
    new = [a for a in wanted if a not in have]
    if len(have) + len(new) > MAX_LINKS:
        raise items.field_errors([("asset_ids", "too_many_assets")], asset_ids={"max": MAX_LINKS})
    unseen = [a for a in new if not await assets.can_see(session, subject, a)]
    if unseen:
        raise items.field_errors([("asset_ids", "asset_not_found")])
    refs = await assets.asset_refs(session, subject, new)
    return [
        await _write(session, record, a, refs.get(a), source=source, at_creation=at_creation)
        for a in new
    ]


async def unlink(  # noqa: PLR0913 - the record, the link, its version and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    link_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Unlink one asset (If-Match on the link); history names what was taken off."""
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    row = await session.scalar(
        select(WorkItemAsset).where(
            WorkItemAsset.id == link_id,
            WorkItemAsset.work_item_id == record_id,
            WorkItemAsset.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFound(code="work_item_asset_not_found")
    if row.version != expected_version:
        raise Conflict(code="version_conflict", params={"current_version": row.version})
    refs = await assets.asset_refs(session, subject, [row.asset_id])
    await AssetLinkRepository(session).soft_delete(row.id, expected_version=expected_version)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_removed",
        changes=[Change(FIELD, _label(refs.get(row.asset_id)), None)],
        source=source,
    )
    await record_event(
        session,
        WorkItemAssetLinkChanged(work_item_id=record.id, asset_id=row.asset_id, change="removed"),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )


async def attach_emailed(session: AsyncSession, record: WorkItem) -> None:
    """AC2: an e-mailed incident gets its requester's asset when they hold exactly one.

    Only when the tenant's asset settings say so and the plan includes assets; history says it
    came with the e-mail.
    """
    if not await licensing.has_feature(_tenant(session), FEATURE):
        return
    if not await assets.email_includes_assets(session):
        return
    held = await assets.assets_of(session, record.requester_id)
    if len(held) != 1:
        return
    await _write(session, record, held[0].id, held[0], source="email")


def linked_asset_ids_select(user_id: uuid.UUID) -> Select[uuid.UUID]:
    """The assets linked to records assigned to `user_id` that are still being worked (D-153).

    For the assets module's "linked to my tickets" scope: a SQL subquery it filters assets by,
    in the caller's tenant session (both tables force RLS).
    """
    return (
        select(WorkItemAsset.asset_id)
        .join(
            WorkItem,
            (WorkItem.tenant_id == WorkItemAsset.tenant_id)
            & (WorkItem.id == WorkItemAsset.work_item_id),
        )
        .where(
            WorkItemAsset.deleted_at.is_(None),
            WorkItem.deleted_at.is_(None),
            WorkItem.technician_id == user_id,
            WorkItem.status_category.in_(_WORKING),
        )
    )


# --- the asset's side (WP-049b S4, lane B's ports) ---------------------------------------------

# The record types an asset's linked records are listed by, in the panel's order.
LINKED_KINDS: tuple[WorkItemTypeCode, ...] = tuple(
    code
    for code in (
        WorkItemTypeCode.INCIDENT,
        WorkItemTypeCode.SERVICE_REQUEST,
        WorkItemTypeCode.PROBLEM,
        WorkItemTypeCode.CHANGE,
        WorkItemTypeCode.RELEASE,
    )
    if code in TYPES
)
PAGE_MAX = 100


def _linked_to(asset_id: uuid.UUID) -> Select[uuid.UUID]:
    return select(WorkItemAsset.work_item_id).where(
        WorkItemAsset.asset_id == asset_id, WorkItemAsset.deleted_at.is_(None)
    )


async def asset_ids_of(session: AsyncSession, work_item_id: uuid.UUID) -> list[uuid.UUID]:
    """The assets a record links now (its live links), for the assets module's live counters."""
    return [row.asset_id for row in await _live(session, work_item_id)]


async def linked_counts(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID
) -> dict[str, tuple[int, int]]:
    """Per record type: (still worked, all) of the records linking the asset that you may see.

    A record you may not see is neither counted nor listed (the coordinator, 2026-11-11).
    "Still worked" is the D-153 rule: open, paused or resolved, not closed, canceled or trashed.
    """
    found: dict[str, tuple[int, int]] = {}
    for code in LINKED_KINDS:
        wtype = TYPES[code]
        visible = items.staff_rows(subject, wtype).where(WorkItem.id.in_(_linked_to(asset_id)))
        row = (
            await session.execute(
                visible.with_only_columns(
                    func.count().filter(WorkItem.status_category.in_(_WORKING)),
                    func.count(),
                )
            )
        ).one()
        found[code.value] = (int(row[0] or 0), int(row[1] or 0))
    return found


async def linked_page(  # noqa: PLR0913 - the asset, the kind and the page, explicit
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    kind: str,
    *,
    cursor: uuid.UUID | None = None,
    limit: int = 25,
) -> tuple[list[WorkItem], uuid.UUID | None]:
    """One page of the records of `kind` linking the asset that you may see, newest first.

    Keyset by ID (UUIDv7, time-ordered); returns the rows and the next cursor (None at the end).
    """
    try:
        wtype = TYPES[WorkItemTypeCode(kind)]
    except (KeyError, ValueError):
        raise NotFound(code="work_item_type_not_found") from None
    size = max(1, min(limit, PAGE_MAX))
    query = items.staff_rows(subject, wtype).where(WorkItem.id.in_(_linked_to(asset_id)))
    if cursor is not None:
        query = query.where(WorkItem.id < cursor)
    rows = list(await session.scalars(query.order_by(WorkItem.id.desc()).limit(size + 1)))
    more = len(rows) > size
    page = rows[:size]
    return page, (page[-1].id if more and page else None)


async def repoint_asset_links(  # noqa: PLR0913 - the merge's two assets and their names, explicit
    session: AsyncSession,
    from_asset_id: uuid.UUID,
    to_asset_id: uuid.UUID,
    *,
    from_label: str,
    to_label: str,
    source: Source = "system",
) -> int:
    """An asset merge (WP-049b S4b): every live link to `from_asset_id` moves to `to_asset_id`.

    A record already linking the target keeps one link (the old one is taken off, never
    duplicated). Each moved record gets its history line, and the link events go out (removed
    and added), so open records follow live. The merge itself is audited by the assets module.
    Returns how many records were touched.
    """
    if from_asset_id == to_asset_id:
        return 0
    moving = list(
        await session.scalars(
            select(WorkItemAsset).where(
                WorkItemAsset.asset_id == from_asset_id, WorkItemAsset.deleted_at.is_(None)
            )
        )
    )
    touched = 0
    for row in moving:
        record = await session.get(WorkItem, row.work_item_id)
        if record is None:
            continue
        has_target = await session.scalar(
            select(WorkItemAsset.id).where(
                WorkItemAsset.work_item_id == row.work_item_id,
                WorkItemAsset.asset_id == to_asset_id,
                WorkItemAsset.deleted_at.is_(None),
            )
        )
        await AssetLinkRepository(session).soft_delete(row.id, expected_version=row.version)
        await record_event(
            session,
            WorkItemAssetLinkChanged(
                work_item_id=record.id, asset_id=from_asset_id, change="removed"
            ),
            aggregate_id=record.id,
            aggregate_version=record.version,
        )
        if has_target is None:
            await AssetLinkRepository(session).add(
                WorkItemAsset(work_item_id=record.id, asset_id=to_asset_id, source=source)
            )
            await record_event(
                session,
                WorkItemAssetLinkChanged(
                    work_item_id=record.id, asset_id=to_asset_id, change="added"
                ),
                aggregate_id=record.id,
                aggregate_version=record.version,
            )
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="updated",
            changes=[Change(FIELD, from_label, None if has_target else to_label)],
            source=source,
        )
        touched += 1
    return touched
