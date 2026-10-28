"""Saved views and list settings (WP-020d; REQ-INC-104, 106, 110).

A saved view stores the list API's own `filter` and `sort` as sent, so the view a user saved
returns the same rows when its filter is sent to the list API unchanged (REQ-INC-106 AC3). Both
are checked against the same allowlist as the list (built-in fields plus the tenant's custom
fields as `custom.<key>`), so a view can never hold a filter the list would refuse.

List settings are one user's columns, sort and page size for one view (`view_key`: a built-in
view code or `custom:<view id>`), so column choices never leak into another view (REQ-INC-104
AC3) or to another user (AC1). Column keys are checked for shape only: a column of a custom
field that was removed later is dropped by the screen, not refused here.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied, PreconditionRequired
from app.modules import metadata
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lists import (
    CUSTOM_VIEW,
    MAX_COLUMNS,
    PAGE_SIZES,
    ViewVisibility,
    view_key_valid,
    width_valid,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import WorkItemListSettingsChanged, WorkItemViewChanged
from app.modules.work_items.infra.models import WorkItemListSetting, WorkItemView
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import FIELDS
from app.modules.work_items.service.reporting import DIMENSIONS
from app.shared.api.filters import FieldType, ResourceFields, compile_filter
from app.shared.api.listing import parse_sort
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.reporting import Dimension, DimensionKind

VIEW_NAME_MAX = 120
_COLUMN_KEY = re.compile(r"^[a-z][a-z0-9_.]{0,79}$")
# A view key for the list with no view (everything the user may see).
ALL = "all"


class ViewRepository(Repository[WorkItemView]):
    """Saved views of the session's tenant."""

    model = WorkItemView


class SettingRepository(Repository[WorkItemListSetting]):
    """List settings of the session's tenant."""

    model = WorkItemListSetting


async def allowed_fields(session: AsyncSession, wtype: WorkItemType) -> ResourceFields:
    """The list's allowlist for this tenant: built-in fields and custom fields (WP-026)."""
    custom = await metadata.filter_fields(session, wtype.code.value, "work_items")
    return replace(FIELDS, fields={**FIELDS.fields, **custom})


def _require_view(subject: Subject, wtype: WorkItemType) -> None:
    if not subject.holds(wtype.permission("view")):
        raise PermissionDenied(
            params={"permission": wtype.permission("view"), "reason": "no_permission"}
        )


def _columns(columns: Sequence[dict[str, Any]], problems: list[tuple[str, str]]) -> list[Any]:
    """Each column once, `{"key", "width"}`; at most MAX_COLUMNS."""
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    if len(columns) > MAX_COLUMNS:
        problems.append(("columns", "too_many_items"))
        return clean
    for column in columns:
        key = column.get("key")
        width = column.get("width")
        if not isinstance(key, str) or not _COLUMN_KEY.match(key) or key in seen:
            problems.append(("columns", "invalid_choice"))
            return clean
        if width is not None and (not isinstance(width, int) or not width_valid(width)):
            problems.append(("columns", "out_of_range"))
            return clean
        seen.add(key)
        clean.append({"key": key, "width": width})
    return clean


def _sort(sort: str | None, allowed: ResourceFields) -> str | None:
    """The sort as the list API takes it; refused like the list would refuse it."""
    if sort is None or not sort.strip():
        return None
    clean = ",".join(t.strip() for t in sort.split(",") if t.strip())
    parse_sort(clean, allowed)
    return clean


# --- the list's fields (REQ-INC-104, 106) --------------------------------------------------------


@dataclass(frozen=True)
class ListField:
    """One field of the list as a filter, sort or column offers it.

    `dimension` says how its values are named (the report source's, so the console names them
    like a report does); `sortable` whether the list sorts by it across pages (REQ-INC-104 AC2).
    """

    name: str
    type: str
    values: list[str]
    multiple: bool
    sortable: bool
    dimension: Dimension | None


async def list_fields(
    session: AsyncSession, subject: Subject, wtype: WorkItemType
) -> list[ListField]:
    """Every field the list filters, sorts or shows, with the tenant's custom fields."""
    _require_view(subject, wtype)
    allowed = await allowed_fields(session, wtype)
    found: list[ListField] = []
    for name, spec in allowed.fields.items():
        if not spec.filterable:
            continue
        dimension = DIMENSIONS.get(name)
        if dimension is None and name.startswith("custom.") and spec.type == FieldType.ENUM:
            dimension = Dimension(DimensionKind.ADMIN_CODE)
        found.append(
            ListField(
                name=name,
                type=str(spec.type.value),
                values=sorted(spec.values),
                multiple=spec.array,
                sortable=spec.sortable,
                dimension=dimension,
            )
        )
    return found


# --- saved views (REQ-INC-106) --------------------------------------------------------------------


async def views(session: AsyncSession, subject: Subject, wtype: WorkItemType) -> list[WorkItemView]:
    """The subject's own views and the views shared with everyone, by name."""
    _require_view(subject, wtype)
    rows = await session.scalars(
        select(WorkItemView)
        .where(
            WorkItemView.type == wtype.code,
            WorkItemView.deleted_at.is_(None),
            or_(
                WorkItemView.owner_id == subject.user_id,
                WorkItemView.visibility == ViewVisibility.SHARED,
            ),
        )
        .order_by(func.lower(WorkItemView.name), WorkItemView.id)
    )
    return list(rows)


async def view(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, view_id: uuid.UUID
) -> WorkItemView:
    """One view the subject may use (their own or a shared one), else 404."""
    _require_view(subject, wtype)
    row: WorkItemView | None = await session.scalar(
        select(WorkItemView).where(
            WorkItemView.id == view_id,
            WorkItemView.type == wtype.code,
            WorkItemView.deleted_at.is_(None),
            or_(
                WorkItemView.owner_id == subject.user_id,
                WorkItemView.visibility == ViewVisibility.SHARED,
            ),
        )
    )
    if row is None:
        raise NotFound(code="work_item_view_not_found")
    return row


async def _check_view(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    values: dict[str, Any],
    *,
    except_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    problems: list[tuple[str, str]] = []
    name = " ".join(str(values.get("name") or "").split())
    if not name:
        problems.append(("name", "required"))
    elif len(name) > VIEW_NAME_MAX:
        problems.append(("name", "value_too_long"))
    else:
        same = select(WorkItemView.id).where(
            WorkItemView.type == wtype.code,
            WorkItemView.owner_id == subject.user_id,
            WorkItemView.deleted_at.is_(None),
            func.lower(WorkItemView.name) == name.lower(),
        )
        if except_id is not None:
            same = same.where(WorkItemView.id != except_id)
        if await session.scalar(same) is not None:
            problems.append(("name", "duplicate_name"))
    columns = _columns(values.get("columns") or [], problems)
    if problems:
        raise items.field_errors(problems)
    allowed = await allowed_fields(session, wtype)
    tree = values.get("filter")
    if tree is not None:  # 422 invalid_filter, exactly as the list refuses it
        compile_filter(tree, allowed, now=datetime.now(UTC))
    return {
        "name": name,
        "visibility": ViewVisibility(values.get("visibility") or ViewVisibility.PRIVATE).value,
        "filter": tree,
        "columns": columns,
        "sort": _sort(values.get("sort"), allowed),
    }


async def _view_changed(
    session: AsyncSession, row: WorkItemView, kind: str, changes: list[Change], source: Source
) -> None:
    await record_changes(
        session,
        record_type="work_item_view",
        record_id=row.id,
        version=row.version,
        kind="deleted" if kind == "deleted" else ("created" if kind == "created" else "updated"),
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        WorkItemViewChanged(
            view_id=row.id, type=row.type, owner_id=row.owner_id, visibility=row.visibility
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_view(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    values: dict[str, Any],
    *,
    source: Source,
) -> WorkItemView:
    """Save a view as the subject's (private or shared with everyone)."""
    _require_view(subject, wtype)
    clean = await _check_view(session, subject, wtype, values)
    row = await ViewRepository(session).add(
        WorkItemView(type=wtype.code, owner_id=subject.user_id, **clean)
    )
    await _view_changed(session, row, "created", [Change("name", None, row.name)], source)
    return row


async def _own(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, view_id: uuid.UUID
) -> WorkItemView:
    row = await view(session, subject, wtype, view_id)
    if row.owner_id != subject.user_id:  # shared views are changed by their owner only
        raise PermissionDenied(params={"reason": "not_view_owner"})
    return row


async def update_view(  # noqa: PLR0913 - the view, its version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    view_id: uuid.UUID,
    values: dict[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> WorkItemView:
    """Change the subject's own view (If-Match). Fields left out keep their value."""
    row = await _own(session, subject, wtype, view_id)
    merged = {
        "name": row.name,
        "visibility": row.visibility,
        "filter": row.filter,
        "columns": row.columns,
        "sort": row.sort,
        **values,
    }
    clean = await _check_view(session, subject, wtype, merged, except_id=row.id)
    changes = [
        Change(field, getattr(row, field), value)
        for field, value in clean.items()
        if getattr(row, field) != value
    ]
    updated = await ViewRepository(session).update(
        row.id, expected_version=expected_version, changes=clean
    )
    await _view_changed(session, updated, "updated", changes, source)
    return updated


async def delete_view(  # noqa: PLR0913 - the view and its version, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    view_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove the subject's own view (soft delete); its list settings go with it."""
    row = await _own(session, subject, wtype, view_id)
    removed = await ViewRepository(session).soft_delete(row.id, expected_version=expected_version)
    await _view_changed(session, removed, "deleted", [], source)


# --- list settings (REQ-INC-104, 110) -------------------------------------------------------------


def _view_key(key: str) -> str:
    if not view_key_valid(key, (*items.VIEW_CODES, *items.COUNTERS, ALL)):
        raise items.field_errors([("view_key", "invalid_choice")])
    return key


async def list_setting(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, view_key: str
) -> WorkItemListSetting | None:
    """The subject's settings for one view, or None (the screen's defaults apply)."""
    _require_view(subject, wtype)
    found: WorkItemListSetting | None = await session.scalar(
        select(WorkItemListSetting).where(
            WorkItemListSetting.type == wtype.code,
            WorkItemListSetting.user_id == subject.user_id,
            WorkItemListSetting.view_key == _view_key(view_key),
            WorkItemListSetting.deleted_at.is_(None),
        )
    )
    return found


async def save_list_setting(  # noqa: PLR0913 - the view, its version and the settings, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    view_key: str,
    values: dict[str, Any],
    *,
    expected_version: int | None,
) -> WorkItemListSetting:
    """Create or replace the subject's settings for one view.

    The first save has no version (If-Match absent); later saves need the version read, so two
    windows of the same user cannot silently overwrite each other.
    """
    if view_key.startswith(CUSTOM_VIEW):  # a saved view the subject may use
        await view(
            session, subject, wtype, uuid.UUID(_view_key(view_key).removeprefix(CUSTOM_VIEW))
        )
    existing = await list_setting(session, subject, wtype, view_key)
    problems: list[tuple[str, str]] = []
    columns = _columns(values.get("columns") or [], problems)
    page_size = values.get("page_size")
    if page_size not in PAGE_SIZES:
        problems.append(("page_size", "invalid_choice"))
    if problems:
        raise items.field_errors(problems)
    clean = {
        "columns": columns,
        "sort": _sort(values.get("sort"), await allowed_fields(session, wtype)),
        "page_size": page_size,
    }
    repository = SettingRepository(session)
    if existing is None:
        if expected_version is not None:  # it was removed since it was read
            raise items.stale(0, expected_version)
        row = await repository.add(
            WorkItemListSetting(
                type=wtype.code, user_id=subject.user_id, view_key=view_key, **clean
            )
        )
    else:
        if expected_version is None:
            raise PreconditionRequired(params={"header": "If-Match"})
        row = await repository.update(existing.id, expected_version=expected_version, changes=clean)
    await record_event(
        session,
        WorkItemListSettingsChanged(user_id=subject.user_id, type=row.type, view_key=row.view_key),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return row
