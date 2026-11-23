"""Merging duplicate assets (WP-049b S4b; REQ-AST-052).

- **Who:** `assets.manage` on BOTH assets, checked by the server within its scope: an asset the
  person may not manage is refused (403 when they see it, 404 otherwise). Assets at two sites
  need both sites managed (`asset_merge_site_not_managed`). A merge never crosses tenants: the
  other tenant's asset is simply not found (RLS).
- **Preview:** for each field in MERGE_FIELDS, both values and the suggested side (the
  survivor's value unless it has none). The suggested survivor is the discovered asset, then the
  newest scan (the spec's default); the person may swap them. Money is shown and chosen only
  with `assets.view_financials` (D-157); without it the survivor's money stays.
- **The merge, one transaction:** the survivor takes the chosen values through the ordinary
  update (every rule holds); work-item links move through lane A's `repoint_asset_links`
  (registered with the linked-records port); cost lines, notes, fitted components, static
  group memberships and relationships move too; the merged asset goes to the trash (soft
  delete) with a "merged into" history line, and keeps its tag, serial and barcode, copied
  into the merge as an alias: they find the survivor (list search, and the record's ID).
  The route writes ONE `asset.merged` audit entry with the field-by-field mapping.
- **Restore:** the merged asset can be restored from the trash, but only after a warning
  (`asset_restore_merged`, 409, then `confirm_merged`): the restore ends the alias and never
  moves anything back (assets.py `restore_asset`).
- An asset on an open loan, booked ahead, or fitted to the other one is not merged (codes).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied
from app.core.logging import get_logger
from app.modules.assets.domain.batch import (
    MERGE_FIELDS,
    MONEY_CHOICES,
    MergeCandidate,
    MergeSide,
    default_side,
    merge_choice_problems,
    suggest_survivor,
)
from app.modules.assets.infra.models import (
    Asset,
    AssetBooking,
    AssetCost,
    AssetGroup,
    AssetGroupMember,
    AssetLoanItem,
    AssetMerge,
    AssetNote,
    AssetRelationship,
)
from app.modules.assets.service import valuations
from app.modules.assets.service.assets import (
    MANAGE,
    RECORD_TYPE,
    _json,
    _refuse,
    _require,
    _saved,
    _tenant,
    _visible,
    sees_money,
    update_asset,
)
from app.modules.assets.service.linked import linked_port
from app.modules.assets.service.ownership import Holder, set_holder
from app.modules.identity_access import Subject
from app.shared.history import Change, Source
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

log = get_logger(__name__)

MERGED_INTO = "merged_into"  # the merged asset's history line
MERGED_FROM = "merged_from"  # the survivor's
SITE_NOT_MANAGED = "asset_merge_site_not_managed"


def label(row: Asset) -> str:
    """How a history line names an asset: its tag, else its name."""
    return row.tag or row.name


@dataclass(frozen=True, slots=True)
class MergeField:
    """One field of the preview: both values, the suggested side; money hidden without the right."""

    field: str
    survivor: Any
    merged: Any
    side: MergeSide
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class MergePreview:
    """The two assets in the suggested order, and the field-by-field choice."""

    survivor: Asset
    merged: Asset
    fields: list[MergeField]
    swapped: bool  # the suggestion reversed the order asked for


@dataclass(slots=True)
class MergeResult:
    """The survivor after the merge, the merge row, and what moved (counts)."""

    survivor: Asset
    merge: AssetMerge
    mapping: list[dict[str, str]]
    moved: dict[str, int] = field(default_factory=dict)


async def _manageable(
    session: AsyncSession, subject: Subject, first_id: uuid.UUID, second_id: uuid.UUID
) -> tuple[Asset, Asset]:
    """Both assets, locked, each managed by the subject; refused otherwise (never a hint)."""
    _require(subject, MANAGE)
    if first_id == second_id:
        raise Conflict(code="asset_merge_same")
    first = await _visible(session, subject, first_id, permission=MANAGE)
    try:
        second = await _visible(session, subject, second_id, permission=MANAGE)
    except PermissionDenied:
        # Seen but not managed: at another site the person does not manage, say so plainly.
        seen = await session.scalar(select(Asset.site_id).where(Asset.id == second_id))
        if seen != first.site_id:
            raise PermissionDenied(code=SITE_NOT_MANAGED, params={"permission": MANAGE}) from None
        raise
    return first, second


def _candidate(row: Asset) -> MergeCandidate:
    return MergeCandidate(
        discovered=row.discovered_serial is not None, last_scanned_at=row.last_scanned_at
    )


def _fields(survivor: Asset, merged: Asset, *, money: bool) -> list[MergeField]:
    found: list[MergeField] = []
    for name in MERGE_FIELDS:
        mine, theirs = getattr(survivor, name), getattr(merged, name)
        if name in MONEY_CHOICES and not money:
            found.append(MergeField(name, None, None, MergeSide.SURVIVOR, hidden=True))
            continue
        found.append(MergeField(name, _json(mine), _json(theirs), default_side(mine, theirs)))
    return found


async def preview(
    session: AsyncSession, subject: Subject, first_id: uuid.UUID, second_id: uuid.UUID
) -> MergePreview:
    """What a merge of the two would keep, with the suggested survivor first."""
    first, second = await _manageable(session, subject, first_id, second_id)
    swapped = suggest_survivor(_candidate(first), _candidate(second)) == 1
    survivor, merged = (second, first) if swapped else (first, second)
    return MergePreview(
        survivor=survivor,
        merged=merged,
        fields=_fields(survivor, merged, money=sees_money(subject)),
        swapped=swapped,
    )


async def _blockers(session: AsyncSession, survivor: Asset, merged: Asset) -> None:
    on_loan = await session.scalar(
        select(AssetLoanItem.id).where(
            AssetLoanItem.asset_id == merged.id,
            AssetLoanItem.returned_at.is_(None),
            AssetLoanItem.deleted_at.is_(None),
        )
    )
    if on_loan is not None:
        raise Conflict(code="asset_merge_on_loan", params={"asset": label(merged)})
    booked = await session.scalar(
        select(AssetBooking.id).where(
            AssetBooking.asset_id == merged.id,
            AssetBooking.status == "booked",
            AssetBooking.deleted_at.is_(None),
        )
    )
    if booked is not None:
        raise Conflict(code="asset_merge_booked", params={"asset": label(merged)})
    if survivor.id == merged.parent_asset_id or merged.id == survivor.parent_asset_id:
        raise Conflict(code="asset_merge_nested")


def _mapping(
    survivor: Asset, merged: Asset, choices: Mapping[str, str], *, money: bool
) -> list[dict[str, str]]:
    mapping: list[dict[str, str]] = []
    for name in MERGE_FIELDS:
        mine, theirs = getattr(survivor, name), getattr(merged, name)
        if name in MONEY_CHOICES and not money:
            side = MergeSide.SURVIVOR  # D-157: money the person may not see stays as it is
        else:
            side = MergeSide(choices.get(name, default_side(mine, theirs)))
        mapping.append({"field": name, "side": side.value})
    return mapping


async def merge(  # noqa: PLR0913 - the two assets, their versions, the choices and the source
    session: AsyncSession,
    subject: Subject,
    survivor_id: uuid.UUID,
    merged_id: uuid.UUID,
    *,
    survivor_version: int,
    merged_version: int,
    choices: Mapping[str, str],
    source: Source,
) -> MergeResult:
    """Merge `merged_id` into `survivor_id` with the person's field choices (If-Match on both)."""
    survivor, merged = await _manageable(session, subject, survivor_id, merged_id)
    for row, expected in ((survivor, survivor_version), (merged, merged_version)):
        if row.version != expected:
            raise await stale_version(
                session, row, expected_version=expected, record_type=RECORD_TYPE,
                record_id=row.id,
            )  # fmt: skip
    money = sees_money(subject)
    _refuse(merge_choice_problems(choices, sees_money=money))
    await _blockers(session, survivor, merged)
    mapping = _mapping(survivor, merged, choices, money=money)
    values = {
        m["field"]: getattr(merged, m["field"])
        for m in mapping
        if m["side"] == MergeSide.MERGED
        and getattr(merged, m["field"]) != getattr(survivor, m["field"])
    }
    if values:
        survivor = await update_asset(
            session, subject, survivor.id, values, expected_version=survivor.version,
            source=source,
        )  # fmt: skip
    moved = await _move_parts(session, subject, survivor, merged, source)
    port = linked_port()
    if port is None:  # work items registers it at start-up; without it no link moves (lane A)
        log.warning("asset_merge_without_linked_port", merged_id=str(merged.id))
    moved["work_items"] = (
        await port.repoint_links(
            session, merged.id, survivor.id, from_label=label(merged), to_label=label(survivor),
            source=source,
        )
        if port is not None
        else 0
    )  # fmt: skip
    merged.deleted_at = datetime.now(UTC)
    await _saved(
        session,
        subject,
        merged,
        [Change("deleted", old=False, new=True), Change(MERGED_INTO, None, label(survivor))],
        action="deleted",
        source=source,
    )
    await _saved(
        session, subject, survivor, [Change(MERGED_FROM, None, label(merged))],
        action="updated", source=source,
    )  # fmt: skip
    record = AssetMerge(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        survivor_id=survivor.id,
        merged_id=merged.id,
        merged_tag=merged.tag,
        merged_serial=merged.serial_number,
        merged_barcode=merged.barcode,
        mapping=mapping,
    )
    session.add(record)
    await session.flush()
    return MergeResult(survivor=survivor, merge=record, mapping=mapping, moved=moved)


async def _move_parts(
    session: AsyncSession, subject: Subject, survivor: Asset, merged: Asset, source: Source
) -> dict[str, int]:
    """Cost lines, notes, components, static groups and relationships go to the survivor."""
    moved: dict[str, int] = {}
    for model, key in ((AssetCost, "costs"), (AssetNote, "notes")):
        result = await session.execute(
            update(model)
            .where(model.asset_id == merged.id, model.deleted_at.is_(None))
            .values(asset_id=survivor.id, version=model.version + 1, updated_by=subject.user_id)
        )
        moved[key] = int(result.rowcount)  # type: ignore[attr-defined]  # a CursorResult
    if moved["costs"]:
        await valuations.refresh(session, survivor)  # its cost of ownership grows at once
    children = list(
        await session.scalars(
            select(Asset).where(Asset.parent_asset_id == merged.id, Asset.deleted_at.is_(None))
        )
    )
    for child in children:  # through the holder change, so holdings and history stay right
        await set_holder(
            session, subject, child.id, Holder("asset", survivor.id),
            expected_version=child.version, source=source,
        )  # fmt: skip
    moved["components"] = len(children)
    moved["groups"] = await _move_groups(session, subject, survivor, merged)
    moved["relationships"] = await _move_relationships(session, subject, survivor, merged)
    return moved


async def _move_groups(
    session: AsyncSession, subject: Subject, survivor: Asset, merged: Asset
) -> int:
    """The survivor joins the merged asset's static groups (the merged keeps its own)."""
    groups = list(
        await session.scalars(
            select(AssetGroupMember.group_id)
            .join(AssetGroup, AssetGroup.id == AssetGroupMember.group_id)
            .where(AssetGroupMember.asset_id == merged.id, AssetGroup.deleted_at.is_(None))
        )
    )
    joined = 0
    for group_id in groups:
        has = await session.scalar(
            select(AssetGroupMember.group_id).where(
                AssetGroupMember.group_id == group_id, AssetGroupMember.asset_id == survivor.id
            )
        )
        if has is None:
            session.add(
                AssetGroupMember(
                    tenant_id=survivor.tenant_id,
                    group_id=group_id,
                    asset_id=survivor.id,
                    created_by=subject.user_id,
                )
            )
            joined += 1
    await session.flush()
    return joined


async def _move_relationships(
    session: AsyncSession, subject: Subject, survivor: Asset, merged: Asset
) -> int:
    """The merged asset's relationships move to the survivor (a duplicate or self-link goes).

    A relationship that would duplicate one or link the survivor to itself is soft-deleted.
    """
    rows = list(
        await session.scalars(
            select(AssetRelationship).where(
                or_(
                    AssetRelationship.from_asset_id == merged.id,
                    AssetRelationship.to_asset_id == merged.id,
                ),
                AssetRelationship.deleted_at.is_(None),
            )
        )
    )
    moved = 0
    for rel in rows:
        start = survivor.id if rel.from_asset_id == merged.id else rel.from_asset_id
        end = survivor.id if rel.to_asset_id == merged.id else rel.to_asset_id
        twin = await session.scalar(
            select(func.count())
            .select_from(AssetRelationship)
            .where(
                AssetRelationship.from_asset_id == start,
                AssetRelationship.to_asset_id == end,
                AssetRelationship.kind == rel.kind,
                AssetRelationship.deleted_at.is_(None),
                AssetRelationship.id != rel.id,
            )
        )
        rel.version += 1
        rel.updated_by = subject.user_id
        if start == end or twin:
            rel.deleted_at = datetime.now(UTC)
            continue
        rel.from_asset_id, rel.to_asset_id = start, end
        moved += 1
    await session.flush()
    return moved


# --- the alias: a merged asset's identifiers and ID find the survivor ---------------------------


def alias_survivors(text: str) -> Any:  # noqa: ANN401 - a SQLAlchemy select of survivor IDs
    """The survivors whose merged assets' tag, serial or barcode is `text` (any case)."""
    wanted = text.strip().lower()
    return select(AssetMerge.survivor_id).where(
        AssetMerge.restored_at.is_(None),
        AssetMerge.deleted_at.is_(None),
        or_(
            func.lower(AssetMerge.merged_tag) == wanted,
            func.lower(AssetMerge.merged_serial) == wanted,
            func.lower(AssetMerge.merged_barcode) == wanted,
        ),
    )


async def survivor_of(session: AsyncSession, merged_id: uuid.UUID) -> uuid.UUID | None:
    """The live asset a merged asset went into (following a chain of merges), or None."""
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = None
    wanted = merged_id
    while wanted not in seen:
        seen.add(wanted)
        found = await session.scalar(
            select(AssetMerge.survivor_id).where(
                AssetMerge.merged_id == wanted,
                AssetMerge.restored_at.is_(None),
                AssetMerge.deleted_at.is_(None),
            )
        )
        if found is None:
            break
        current = wanted = found
    return current


async def live_merge_of(session: AsyncSession, merged_id: uuid.UUID) -> AssetMerge | None:
    """The merge that put this asset in the trash, while its alias holds."""
    found: AssetMerge | None = await session.scalar(
        select(AssetMerge)
        .where(
            AssetMerge.merged_id == merged_id,
            AssetMerge.restored_at.is_(None),
            AssetMerge.deleted_at.is_(None),
        )
        .with_for_update()
    )
    return found
