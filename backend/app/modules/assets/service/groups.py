"""Static and dynamic asset groups (WP-049a s4; REQ-AST-028).

- **Static:** its members are listed; filled from the list's selection in one step (AC2).
- **Dynamic:** a saved filter over the asset list's fields (the shared filter DSL), checked when
  saved and evaluated when shown, so an asset that now matches is in it at once (AC1); screens
  refresh on the asset list's live events.
- **Counts match the list (AC3):** both come from the same query, within what the person may see.
- Groups are configured by `assets.manage`; everyone with `assets.view` sees them.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.events import AssetGroupChanged
from app.modules.assets.infra.models import Asset, AssetGroup, AssetGroupMember
from app.modules.assets.service.assets import (
    ASSET_FIELDS,
    MANAGE,
    VIEW,
    _refuse,
    _require,
    _tenant,
    _visible,
    staff_rows,
)
from app.modules.identity_access import Subject
from app.shared.api.filters import compile_filter
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

NAME_MAX = 200
MEMBERS_MAX = 100  # one step's selection, like a bulk move
RECORD_TYPE = "asset_group"


@dataclass(frozen=True, slots=True)
class GroupView:
    """A group with how many of its assets the person may see."""

    row: AssetGroup
    count: int


def _members(subject: Subject, group: AssetGroup) -> Select[Any]:
    """The group's assets the subject may see: its members, or its filter's matches."""
    rows = staff_rows(subject)
    if group.kind == "dynamic":
        return rows.where(compile_filter(group.filter, ASSET_FIELDS, now=system_clock.now()))
    return rows.where(
        Asset.id.in_(select(AssetGroupMember.asset_id).where(AssetGroupMember.group_id == group.id))
    )


async def count_members(session: AsyncSession, subject: Subject, group: AssetGroup) -> int:
    """How many of the group's assets the subject may see (the same query as its list, AC3)."""
    found = await session.scalar(
        select(func.count()).select_from(_members(subject, group).subquery())
    )
    return int(found or 0)


def _cleaned(values: Mapping[str, Any]) -> tuple[dict[str, Any], list[Problem]]:
    problems: list[Problem] = []
    out: dict[str, Any] = {}
    if "name" in values:
        name = str(values["name"] or "").strip()
        if not name:
            problems.append(Problem("name", "required"))
        elif len(name) > NAME_MAX:
            problems.append(Problem("name", "value_too_long", (("max", NAME_MAX),)))
        out["name"] = name
    if "description" in values:
        out["description"] = str(values["description"] or "").strip() or None
    if "filter" in values and values["filter"] is not None:
        # 422 invalid_filter with the bad condition's path, as the list itself answers.
        compile_filter(values["filter"], ASSET_FIELDS, now=system_clock.now())
        out["filter"] = values["filter"]
    return out, problems


async def _by_name(session: AsyncSession, name: str, other_than: uuid.UUID | None) -> bool:
    query = select(AssetGroup.id).where(
        func.lower(AssetGroup.name) == name.lower(), AssetGroup.deleted_at.is_(None)
    )
    if other_than is not None:
        query = query.where(AssetGroup.id != other_than)
    return await session.scalar(query) is not None


async def create_group(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any]
) -> AssetGroup:
    """A static group, or a dynamic one with its filter."""
    _require(subject, MANAGE)
    kind = values.get("kind")
    cleaned, problems = _cleaned({"name": values.get("name"), **values})
    if kind not in ("static", "dynamic"):
        problems.append(Problem("kind", "invalid_choice"))
    if kind == "dynamic" and values.get("filter") is None:
        problems.append(Problem("filter", "required"))
    _refuse(problems)
    if await _by_name(session, cleaned["name"], None):
        raise Conflict(code="asset_group_name_taken")
    row = AssetGroup(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        name=cleaned["name"],
        description=cleaned.get("description"),
        kind=kind,
        filter=cleaned.get("filter") if kind == "dynamic" else None,
    )
    session.add(row)
    await session.flush()
    await _changed(session, row, "created")
    return row


async def _changed(
    session: AsyncSession,
    row: AssetGroup,
    change: Literal["created", "updated", "deleted", "members"],
) -> None:
    await record_event(
        session,
        AssetGroupChanged(group_id=row.id, change=change),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def _group(session: AsyncSession, group_id: uuid.UUID) -> AssetGroup:
    row = await session.get(AssetGroup, group_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code="asset_group_not_found")
    return row


async def update_group(
    session: AsyncSession,
    subject: Subject,
    group_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
) -> AssetGroup:
    """Rename, describe, or (dynamic) change the filter; the kind never changes."""
    _require(subject, MANAGE)
    row = await _group(session, group_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    cleaned, problems = _cleaned(values)
    if "filter" in cleaned and row.kind != "dynamic":
        problems.append(Problem("filter", "asset_group_static"))
    _refuse(problems)
    if "name" in cleaned and await _by_name(session, cleaned["name"], row.id):
        raise Conflict(code="asset_group_name_taken")
    for field, value in cleaned.items():
        setattr(row, field, value)
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _changed(session, row, "updated")
    return row


async def delete_group(
    session: AsyncSession, subject: Subject, group_id: uuid.UUID, *, expected_version: int
) -> None:
    """Moved out of sight (soft delete); its assets are untouched."""
    _require(subject, MANAGE)
    row = await _group(session, group_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    row.deleted_at = system_clock.now()
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _changed(session, row, "deleted")


async def add_members(
    session: AsyncSession, subject: Subject, group_id: uuid.UUID, asset_ids: Sequence[uuid.UUID]
) -> int:
    """A static group gains the selected assets in one step (AC2); how many were new."""
    _require(subject, MANAGE)
    row = await _group(session, group_id)
    if row.kind != "static":
        raise Conflict(code="asset_group_dynamic")
    unique = list(dict.fromkeys(asset_ids))
    if not unique or len(unique) > MEMBERS_MAX:
        raise Conflict(code="asset_bulk_too_many", params={"max": MEMBERS_MAX})
    for asset_id in unique:
        await _visible(session, subject, asset_id)  # every one must be the person's to see
    have = set(
        await session.scalars(
            select(AssetGroupMember.asset_id).where(
                AssetGroupMember.group_id == row.id, AssetGroupMember.asset_id.in_(unique)
            )
        )
    )
    added = [a for a in unique if a not in have]
    for asset_id in added:
        session.add(
            AssetGroupMember(
                tenant_id=row.tenant_id, group_id=row.id, asset_id=asset_id,
                created_by=subject.user_id,
            )
        )  # fmt: skip
    if added:
        row.version += 1
        row.updated_by = subject.user_id
    await session.flush()
    if added:
        await _changed(session, row, "members")
    return len(added)


async def remove_member(
    session: AsyncSession, subject: Subject, group_id: uuid.UUID, asset_id: uuid.UUID
) -> None:
    """A static group loses one asset."""
    _require(subject, MANAGE)
    row = await _group(session, group_id)
    if row.kind != "static":
        raise Conflict(code="asset_group_dynamic")
    gone = await session.execute(
        delete(AssetGroupMember).where(
            AssetGroupMember.group_id == row.id, AssetGroupMember.asset_id == asset_id
        )
    )
    if gone.rowcount:  # type: ignore[attr-defined]  # CursorResult of a DELETE
        row.version += 1
        row.updated_by = subject.user_id
        await session.flush()
        await _changed(session, row, "members")


async def list_groups(session: AsyncSession, subject: Subject) -> list[GroupView]:
    """Every group by name, each with its count as the person's list would show it (AC3)."""
    _require(subject, VIEW)
    rows = await session.scalars(
        select(AssetGroup)
        .where(AssetGroup.deleted_at.is_(None))
        .order_by(func.lower(AssetGroup.name))
    )
    return [GroupView(r, await count_members(session, subject, r)) for r in rows]


async def group_assets(
    session: AsyncSession, subject: Subject, group_id: uuid.UUID, *, limit: int = 200
) -> tuple[AssetGroup, list[Asset]]:
    """A group's assets the person may see, by name."""
    _require(subject, VIEW)
    row = await _group(session, group_id)
    assets = await session.scalars(
        _members(subject, row).order_by(Asset.name, Asset.id).limit(limit)
    )
    return row, list(assets)
