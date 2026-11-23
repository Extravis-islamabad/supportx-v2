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

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    FieldError,
    NotFound,
    PermissionDenied,
    PreconditionRequired,
    ValidationFailed,
)
from app.modules import metadata
from app.modules.identity_access import Subject, restricted_fields
from app.modules.organization import existing_unit_ids, led_groups
from app.modules.work_items.domain import field_access as field_rules
from app.modules.work_items.domain.lists import (
    CUSTOM_VIEW,
    MAX_COLUMNS,
    MAX_VIEW_GROUPS,
    PAGE_SIZES,
    BoardGroupBy,
    ListLayout,
    RowColourBy,
    ViewVisibility,
    view_key_valid,
    width_valid,
)
from app.modules.work_items.domain.templates import PickList
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import (
    WorkItemListSettingsChanged,
    WorkItemSettingsChanged,
    WorkItemViewChanged,
)
from app.modules.work_items.infra.models import (
    WorkItemListSetting,
    WorkItemTypeSettings,
    WorkItemView,
    WorkItemViewFavourite,
)
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import view_filters
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import FIELDS, SHARE_VIEWS, SHARE_VIEWS_WIDE, type_fields
from app.modules.work_items.service.reporting import DIMENSIONS, TYPE_DIMENSIONS
from app.shared.api.filters import FieldType, ResourceFields, compile_filter
from app.shared.api.listing import parse_sort
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.ids import new_id
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
    """The list's allowlist for this tenant: built-in, the type's own and custom fields (WP-026).

    The type's own fields (a problem's type, a change's risk or outcome) are here so a report's
    drill-down opens the list with the filter the chart counted (REQ-CHG-116 AC2).
    """
    custom = await metadata.filter_fields(session, wtype.code.value, "work_items")
    return replace(FIELDS, fields={**FIELDS.fields, **type_fields(wtype), **custom})


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


# Built-in fields whose codes come from the tenant's pick lists: the list offers them as choices
# named like the record does, never as free text (WP-020f QA BUG-05).
PICK_LIST_FIELDS = {
    "level": PickList.LEVEL,
    "closure_code": PickList.CLOSURE_CODE,
    # A change's own lists (WP-045d S4c): only the change list has these fields.
    "change_type": PickList.CHANGE_TYPE,
    "change_reason": PickList.CHANGE_REASON,
}


async def list_fields(
    session: AsyncSession, subject: Subject, wtype: WorkItemType
) -> list[ListField]:
    """Every field the list filters, sorts or shows, with the tenant's custom fields."""
    _require_view(subject, wtype)
    allowed = await allowed_fields(session, wtype)
    # Not the fields the caller's roles hide or mask (ADR-047 AC2): the list refuses them too.
    withheld = field_rules.unseen(subject.field_access, wtype.code.value).all
    cat = await config.load(session, wtype)
    # Retired codes too: old records keep them and a filter must still find those records.
    picked = {
        name: [v.code for v in cat.list_values(pick_list)]
        for name, pick_list in PICK_LIST_FIELDS.items()
    }
    found: list[ListField] = []
    for name, spec in allowed.fields.items():
        if not spec.filterable or name in withheld:
            continue
        dimension = DIMENSIONS.get(name) or TYPE_DIMENSIONS.get(wtype.code, {}).get(name)
        if dimension is None and name.startswith("custom.") and spec.type == FieldType.ENUM:
            dimension = Dimension(DimensionKind.ADMIN_CODE)
        found.append(
            ListField(
                name=name,
                type=str(spec.type.value),
                values=picked.get(name) or sorted(spec.values),
                multiple=spec.array,
                sortable=spec.sortable,
                dimension=dimension,
            )
        )
    return found


# --- saved views (REQ-INC-106) --------------------------------------------------------------------


def _seen_by(subject: Subject) -> ColumnElement[bool]:
    """The subject's own views, views shared with everyone, and those of their groups."""
    seen = [
        WorkItemView.owner_id == subject.user_id,
        WorkItemView.visibility == ViewVisibility.EVERYONE,
    ]
    groups = sorted(subject.group_ids)
    if groups:
        seen.append(
            and_(
                WorkItemView.visibility == ViewVisibility.GROUPS,
                WorkItemView.group_ids.overlap(groups),
            )
        )
    return or_(*seen)


async def shown_filter(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, row: WorkItemView
) -> Any:  # noqa: ANN401 - the filter DSL's JSON tree
    """A view's filter as this reader gets it, never as `sx2:` text.

    Sealed values are opened for the owner while they may see the field, else withheld; a
    non-owner never gets such a view (D-176), and would get them withheld anyway.
    """
    withheld = field_rules.unseen(subject.field_access, wtype.code.value).all
    if row.owner_id != subject.user_id:
        withheld = withheld | await sealed_fields(session, wtype)
    return await view_filters.opened(session, row.id, row.filter, withheld)


async def sealed_fields(session: AsyncSession, wtype: WorkItemType) -> frozenset[str]:
    """The type's sealed custom fields as filter fields (`custom.<key>`), ADR-050."""
    return frozenset(
        f"{field_rules.CUSTOM}{m.key}"
        for m in await metadata.field_marks(session, wtype.code.value, retired=True)
        if m.sensitive or m.seal_state != "plain"
    )


async def withheld_from(
    session: AsyncSession, subject: Subject, wtype: WorkItemType
) -> frozenset[str]:
    """The filter fields this reader may not see (D-176).

    Their role rules (ADR-047), the permission gates (a problem's root cause) and every sealed
    custom field (ADR-050).
    """
    rules = field_rules.unseen(subject.field_access, wtype.code.value).all
    gates = frozenset(
        name
        for name, action in items.HIDDEN_WITHOUT.items()
        if wtype.code.value == "problem" and not subject.holds(wtype.permission(action))
    )
    sealed = frozenset(
        f"{field_rules.CUSTOM}{m.key}"
        for m in await metadata.field_marks(session, wtype.code.value, retired=True)
        if m.sensitive or m.seal_state != "plain"
    )
    return rules | gates | sealed


def usable(row: WorkItemView, subject: Subject, withheld: frozenset[str]) -> bool:
    """Their own view always; someone else's only if its filter names nothing withheld from them.

    Checked on every read (lane C's D-176 condition 1): sharing is checked on save, but roles,
    groups and field rules change afterwards, so the read decides.
    """
    return row.owner_id == subject.user_id or not field_rules.withheld_in_filter(
        row.filter, withheld
    )


async def views(session: AsyncSession, subject: Subject, wtype: WorkItemType) -> list[WorkItemView]:
    """The subject's own views and those shared with them, by name."""
    _require_view(subject, wtype)
    rows = await session.scalars(
        select(WorkItemView)
        .where(
            WorkItemView.type == wtype.code,
            WorkItemView.deleted_at.is_(None),
            _seen_by(subject),
        )
        .order_by(func.lower(WorkItemView.name), WorkItemView.id)
    )
    withheld = await withheld_from(session, subject, wtype)
    return [r for r in rows if usable(r, subject, withheld)]


async def favourite_ids(
    session: AsyncSession, subject: Subject, wtype: WorkItemType
) -> set[uuid.UUID]:
    """The saved views the subject starred (REQ-INC-107 AC1), among those they may still use."""
    rows = await session.scalars(
        select(WorkItemViewFavourite.view_id)
        .join(WorkItemView, WorkItemView.id == WorkItemViewFavourite.view_id)
        .where(
            WorkItemViewFavourite.user_id == subject.user_id,
            WorkItemView.type == wtype.code,
            WorkItemView.deleted_at.is_(None),
            _seen_by(subject),
        )
    )
    return set(rows)


async def star_view(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    view_id: uuid.UUID,
    *,
    starred: bool,
) -> None:
    """Star or un-star a view the subject may use. Idempotent both ways.

    Personal, like list settings: no history and no event (nobody else ever sees a star).
    """
    await view(session, subject, wtype, view_id)  # 404 unless they may use it
    if starred:
        await session.execute(
            insert(WorkItemViewFavourite)
            .values(tenant_id=config.tenant_of(session), user_id=subject.user_id, view_id=view_id)
            .on_conflict_do_nothing()
        )
    else:
        await session.execute(
            delete(WorkItemViewFavourite).where(
                WorkItemViewFavourite.user_id == subject.user_id,
                WorkItemViewFavourite.view_id == view_id,
            )
        )


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
            _seen_by(subject),
        )
    )
    if row is None or not usable(row, subject, await withheld_from(session, subject, wtype)):
        raise NotFound(code="work_item_view_not_found")  # the same 404 either way
    return row


async def _audience(
    session: AsyncSession,
    visibility: ViewVisibility,
    given: list[Any],
    problems: list[tuple[str, str]],
) -> list[uuid.UUID]:
    """The groups a view is shared with: named for `groups`, none for the other visibilities."""
    if visibility != ViewVisibility.GROUPS:
        return []
    group_ids = [uuid.UUID(str(g)) for g in dict.fromkeys(given)]
    if not group_ids:
        problems.append(("group_ids", "required"))
    elif len(group_ids) > MAX_VIEW_GROUPS:
        problems.append(("group_ids", "too_many_items"))
    elif len(await existing_unit_ids(session, "group", group_ids)) != len(group_ids):
        problems.append(("group_ids", "group_not_found"))
    return group_ids


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
    visibility = ViewVisibility(values.get("visibility") or ViewVisibility.PRIVATE)
    group_ids = await _audience(session, visibility, values.get("group_ids") or [], problems)
    if problems:
        raise items.field_errors(problems)
    allowed = await allowed_fields(session, wtype)
    tree = values.get("filter")
    if tree is not None:  # 422 invalid_filter, exactly as the list refuses it
        compile_filter(view_filters.for_validation(tree), allowed, now=datetime.now(UTC))
    return {
        "name": name,
        "visibility": visibility.value,
        "group_ids": group_ids,
        "filter": tree,
        "columns": columns,
        "sort": _sort(values.get("sort"), allowed),
    }


async def _check_sharing(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    clean: dict[str, Any],
    before: WorkItemView | None,
) -> None:
    """D-176: the rights an audience needs, for what this save adds to it (existing kept).

    Private needs nothing beyond `view`. A group of theirs needs `share_views`; any other group
    `share_views_wide` (a team lead's `group` scope: only groups they lead); everyone needs
    `share_views_wide` everywhere. 403 `view_share_not_allowed` with the audience refused.
    """
    visibility = ViewVisibility(clean["visibility"])
    if visibility is ViewVisibility.PRIVATE:
        return
    was = ViewVisibility(before.visibility) if before is not None else ViewVisibility.PRIVATE
    wide = subject.broadest_scope(wtype.permission(SHARE_VIEWS_WIDE))

    def refuse(audience: ViewVisibility) -> PermissionDenied:
        return PermissionDenied(
            code="view_share_not_allowed",
            params={"audience": audience.value, "reason": "no_permission"},
        )

    if visibility is ViewVisibility.EVERYONE:
        if was is not ViewVisibility.EVERYONE and wide != "all":
            raise refuse(ViewVisibility.EVERYONE)
        return
    kept = set(before.group_ids) if before is not None and was is ViewVisibility.GROUPS else set()
    added = [g for g in clean["group_ids"] if g not in kept]
    if not added:
        return
    own = set(subject.group_ids)
    led = await led_groups(session, subject.user_id) if wide == "group" else frozenset()
    for group in added:
        if group in own and subject.holds(wtype.permission(SHARE_VIEWS)):
            continue
        if wide == "all" or (wide == "group" and group in led):
            continue
        raise refuse(ViewVisibility.GROUPS)


async def _check_shareable_filter(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, clean: dict[str, Any]
) -> None:
    """D-176 (lane C): a shared view's filter names no field some recipient may not see.

    Checked against the whole tenant, as search is (ADR-047 §6): a field any role restricts, or a
    sealed one, keeps the view private. The read decides exactly for each person (`usable`);
    this tells the owner on save. 422 `view_filter_not_shareable` {field, audience}.
    """
    if ViewVisibility(clean["visibility"]) is ViewVisibility.PRIVATE:
        return
    del subject
    withheld = await restricted_fields(session, wtype.code.value)
    sealed = frozenset(
        f"{field_rules.CUSTOM}{m.key}"
        for m in await metadata.field_marks(session, wtype.code.value, retired=True)
        if m.sensitive or m.seal_state != "plain"
    )
    found = field_rules.withheld_in_filter(clean["filter"], withheld | sealed)
    if found:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.filter",
                    code="view_filter_not_shareable",
                    message_key="errors.field.view_filter_not_shareable",
                    params={"field": found[0], "audience": clean["visibility"]},
                )
            ]
        )


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
    view_filters.refuse_ciphertext(values.get("filter"))  # sealed text never comes from outside
    clean = await _check_view(session, subject, wtype, values)
    await _check_sharing(session, subject, wtype, clean, None)
    await _check_shareable_filter(session, subject, wtype, clean)
    # Sealed values bound to this view's own ID (a copy is a new view: sealed afresh).
    view_id = new_id()
    clean["filter"] = await view_filters.seal(
        session, view_id, clean["filter"], await sealed_fields(session, wtype)
    )
    row = await ViewRepository(session).add(
        WorkItemView(id=view_id, type=wtype.code, owner_id=subject.user_id, **clean)
    )
    await _view_changed(session, row, "created", [Change("name", None, row.name)], source)
    return row


def _plain(value: object) -> object:
    """A value as history stores it (JSON): group IDs as text."""
    if isinstance(value, list):
        return [str(v) if isinstance(v, uuid.UUID) else v for v in value]
    return value


async def _own(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, view_id: uuid.UUID
) -> WorkItemView:
    row = await view(session, subject, wtype, view_id)
    if row.owner_id != subject.user_id:  # a shared view is changed by its owner only
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
    if "filter" in values:
        view_filters.refuse_ciphertext(values["filter"])
        # A condition the owner could not see, sent back untouched, keeps what is stored.
        values = {**values, "filter": view_filters.restore_withheld(values["filter"], row.filter)}
    merged = {
        "name": row.name,
        "visibility": row.visibility,
        "group_ids": row.group_ids,
        "filter": row.filter,
        "columns": row.columns,
        "sort": row.sort,
        **values,
    }
    clean = await _check_view(session, subject, wtype, merged, except_id=row.id)
    await _check_sharing(session, subject, wtype, clean, row)
    await _check_shareable_filter(session, subject, wtype, clean)
    sealed = await sealed_fields(session, wtype)
    # Same view, same binding: a value sent back unchanged keeps its stored ciphertext.
    clean["filter"] = await view_filters.seal(
        session, row.id, clean["filter"], sealed, before=row.filter
    )

    def kept(field: str, value: object) -> object:
        # History keeps a sealed filter's field names only (lane C's condition 6).
        return view_filters.history_value(value, sealed) if field == "filter" else _plain(value)

    changes = [
        Change(field, kept(field, getattr(row, field)), kept(field, value))
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


def _view_key(wtype: WorkItemType, key: str) -> str:
    if not view_key_valid(key, (*items.view_codes(wtype), *items.counter_codes(wtype), ALL)):
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
            WorkItemListSetting.view_key == _view_key(wtype, view_key),
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
            session, subject, wtype, uuid.UUID(_view_key(wtype, view_key).removeprefix(CUSTOM_VIEW))
        )
    existing = await list_setting(session, subject, wtype, view_key)
    problems: list[tuple[str, str]] = []
    columns = _columns(values.get("columns") or [], problems)
    page_size = values.get("page_size")
    if page_size not in PAGE_SIZES:
        problems.append(("page_size", "invalid_choice"))
    colour = values.get("row_colour_by")
    if colour is not None and colour not in {c.value for c in RowColourBy}:
        problems.append(("row_colour_by", "invalid_choice"))
    # REQ-INC-111 (0182): the layout and the board's columns, codes only.
    layout = values.get("layout")
    if layout is not None and layout not in {c.value for c in ListLayout}:
        problems.append(("layout", "invalid_choice"))
    group_by = values.get("group_by")
    if group_by is not None and group_by not in {c.value for c in BoardGroupBy}:
        problems.append(("group_by", "invalid_choice"))
    if problems:
        raise items.field_errors(problems)
    clean = {
        "columns": columns,
        "sort": _sort(values.get("sort"), await allowed_fields(session, wtype)),
        "page_size": page_size,
        "row_colour_by": colour,
        "layout": layout,
        "group_by": group_by,
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


# --- row colours (REQ-INC-115 AC1) ----------------------------------------------------------------


async def set_row_colour_default(  # noqa: PLR0913 - the type, the choice, its version and who
    session: AsyncSession,
    wtype: WorkItemType,
    value: str,
    *,
    expected_version: int,
    source: Source,
    user_id: uuid.UUID,
) -> tuple[config.Catalogue, str, str]:
    """The tenant's default row colouring (If-Match on the type's settings).

    Returns the new catalogue and the before and after codes for the audit entry.
    """
    from app.modules.work_items.service import settings as settings_service  # noqa: PLC0415 - cycle

    if value not in {c.value for c in RowColourBy}:
        raise items.field_errors([("row_colour_by", "invalid_choice")])
    current = await config.load(session, wtype)
    if current.settings_version != expected_version:
        raise await settings_service.stale_settings(session, wtype, current, expected_version)
    before = current.row_colour_by
    if before == value:
        return current, before, value
    await session.execute(
        update(WorkItemTypeSettings)
        .where(WorkItemTypeSettings.type == wtype.code)
        .values(row_colour_by=value, version=WorkItemTypeSettings.version + 1, updated_by=user_id)
    )
    settings_id = config.settings_record_id(wtype.code)
    await record_changes(
        session,
        record_type=settings_service.SETTINGS_RECORD_TYPE,
        record_id=settings_id,
        version=expected_version + 1,
        kind="updated",
        changes=[Change("row_colour_by", before, value)],
        source=source,
    )
    await record_event(
        session,
        WorkItemSettingsChanged(type=wtype.code, changed_fields=["row_colour_by"]),
        aggregate_id=settings_id,
        aggregate_version=expected_version + 1,
    )
    session.expire_all()
    return await config.load(session, wtype), before, value
