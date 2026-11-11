"""The shared list-settings store (WP-049b s4a; REQ-AST-047, after REQ-INC-104, 106, 107).

Generic on purpose (the coordinator's decision): a list registers itself once (`register_list`,
with its permission, built-in views and fields) and every person then keeps, per view of that
list, their columns and widths, sort, page size and a favourite star, and may save views of
their own (a name and the list API's own `filter`). Assets use it from WP-049b s4a; work-item
lists keep their own store (`work_items.list_settings`) until lane A moves them here.

Settings are always the caller's own: the person is the session's user, never a parameter a
client sends. A saved view's filter is checked against the list's allowlist exactly as the list
checks it, so a view can never hold a filter the list would refuse (REQ-INC-106 AC3). Every
change writes `system.list_settings.changed` to the outbox in the same transaction (rule 5b);
the person's other windows follow on their own channel (rule 5c).
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    Conflict,
    FieldError,
    NotFound,
    PreconditionRequired,
    ValidationFailed,
)
from app.shared.api.filters import FilterField, ResourceFields, compile_filter
from app.shared.api.listing import parse_sort
from app.shared.clock import system_clock
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.ids import new_id
from app.shared.list_settings import domain as rules
from app.shared.list_settings.events import ListSettingsChanged
from app.shared.list_settings.infra.models import ListSetting

FieldsFor = Callable[[AsyncSession], Awaitable[Mapping[str, FilterField]]]


@dataclass(frozen=True, slots=True)
class ListSpec:
    """One list that keeps per-person settings here.

    `permission`: who may read the list (and so keep settings for it); the API checks it.
    `views`: the built-in view codes (`all` is always there). `fields`: the list's allowlist for
    saved views' filters and sorts; `fields_for` adds the tenant's custom fields, as the list
    endpoint does. `feature`: the licence feature the list needs (the API asks the entitlement
    interface, rule 5f).
    """

    key: str
    permission: str
    views: tuple[str, ...]
    fields: ResourceFields
    fields_for: FieldsFor | None = None
    feature: str | None = None


_LISTS: dict[str, ListSpec] = {}


def register_list(spec: ListSpec) -> None:
    """Make a list known to the store (at import of the module that owns the list)."""
    if not rules.list_key_valid(spec.key):
        msg = f"list key {spec.key!r} must be lowercase snake case"
        raise ValueError(msg)
    _LISTS[spec.key] = spec


def unregister_list(key: str) -> None:
    """Forget a list (tests)."""
    _LISTS.pop(key, None)


def list_spec(key: str) -> ListSpec:
    """The registered list, or 404 `list_not_found`."""
    spec = _LISTS.get(key)
    if spec is None:
        raise NotFound(code="list_not_found")
    return spec


class _Settings(Repository[ListSetting]):
    model = ListSetting


def _refuse(problems: Iterable[rules.Problem]) -> None:
    found = [
        FieldError(
            field=f"body.{p.field}",
            code=p.code,
            message_key=f"errors.field.{p.code}",
            params=dict(p.params),
        )
        for p in problems
    ]
    if found:
        raise ValidationFailed(errors=found)


def _stale(current: int, expected: int) -> Conflict:
    return Conflict(
        code="version_conflict", params={"expected_version": expected, "current_version": current}
    )


async def _allowed(session: AsyncSession, spec: ListSpec) -> ResourceFields:
    if spec.fields_for is None:
        return spec.fields
    extra = await spec.fields_for(session)
    return replace(spec.fields, fields={**spec.fields.fields, **extra})


def _sort(sort: object, allowed: ResourceFields) -> str | None:
    """The sort as the list API takes it; refused as the list would refuse it."""
    if sort is None or not str(sort).strip():
        return None
    clean = ",".join(t.strip() for t in str(sort).split(",") if t.strip())
    if len(clean) > rules.SORT_MAX:
        _refuse([rules.Problem("sort", "value_too_long", (("max", rules.SORT_MAX),))])
    parse_sort(clean, allowed)  # 422 invalid_sort, as the list
    return clean


def _filter(tree: object, allowed: ResourceFields) -> dict[str, Any] | None:
    if tree is None:
        return None
    if not isinstance(tree, dict):
        _refuse([rules.Problem("filter", "invalid_choice")])
        return None
    compile_filter(tree, allowed, now=system_clock.now())  # 422 invalid_filter, as the list
    return tree


def _view_key(spec: ListSpec, view_key: str) -> str:
    if len(view_key) > rules.VIEW_KEY_MAX or not rules.view_key_valid(view_key, spec.views):
        _refuse([rules.Problem("view_key", "invalid_choice")])
    return view_key


async def _row(
    session: AsyncSession, user_id: uuid.UUID, spec: ListSpec, view_key: str
) -> ListSetting | None:
    found: ListSetting | None = await session.scalar(
        select(ListSetting).where(
            ListSetting.user_id == user_id,
            ListSetting.list_key == spec.key,
            ListSetting.view_key == view_key,
            ListSetting.deleted_at.is_(None),
        )
    )
    return found


async def _changed(session: AsyncSession, row: ListSetting, change: str) -> None:
    await record_event(
        session,
        ListSettingsChanged(
            user_id=row.user_id, list_key=row.list_key, view_key=row.view_key, change=change
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


# --- reading ----------------------------------------------------------------------------------


async def settings_of(
    session: AsyncSession, user_id: uuid.UUID, spec: ListSpec
) -> list[ListSetting]:
    """Every row the person keeps for the list: settings of views, saved views, favourites.

    Saved views by name, then the built-in views' settings by key.
    """
    rows = await session.scalars(
        select(ListSetting)
        .where(
            ListSetting.user_id == user_id,
            ListSetting.list_key == spec.key,
            ListSetting.deleted_at.is_(None),
        )
        .order_by(ListSetting.name.is_(None), func.lower(ListSetting.name), ListSetting.view_key)
    )
    return list(rows)


async def view_setting(
    session: AsyncSession, user_id: uuid.UUID, spec: ListSpec, view_key: str
) -> ListSetting | None:
    """The person's settings for one view, or None (the screen's defaults apply).

    A saved view that is not the person's (or no longer exists) is 404 `saved_view_not_found`.
    """
    row = await _row(session, user_id, spec, _view_key(spec, view_key))
    if row is None and rules.saved_view_id(view_key) is not None:
        raise NotFound(code="saved_view_not_found")
    return row


# --- the settings of one view -----------------------------------------------------------------


async def save_view_setting(  # noqa: PLR0913 - the view, its version and the settings, explicit
    session: AsyncSession,
    user_id: uuid.UUID,
    spec: ListSpec,
    view_key: str,
    values: Mapping[str, Any],
    *,
    expected_version: int | None,
) -> ListSetting:
    """Create or replace the person's columns, sort and page size of one view; star it or not.

    The first save of a built-in view has no version (If-Match absent); later saves need the
    version read, so two windows of one person never silently overwrite each other. A saved
    view always exists first (`create_saved_view`). `favourite` left out (None) keeps the star.
    """
    existing = await view_setting(session, user_id, spec, view_key)
    columns, problems = rules.clean_columns(values.get("columns"))
    page_size = values.get("page_size", rules.DEFAULT_PAGE_SIZE)
    problems += rules.page_size_problems(page_size)
    _refuse(problems)
    clean: dict[str, Any] = {
        "columns": columns,
        "sort": _sort(values.get("sort"), await _allowed(session, spec)),
        "page_size": page_size,
    }
    if (favourite := values.get("favourite")) is not None:
        clean["favourite"] = bool(favourite)
    repository = _Settings(session)
    if existing is None:
        if expected_version is not None:  # it was removed since it was read
            raise _stale(0, expected_version)
        row = await repository.add(
            ListSetting(user_id=user_id, list_key=spec.key, view_key=view_key, **clean)
        )
    else:
        if expected_version is None:
            raise PreconditionRequired(params={"header": "If-Match"})
        row = await repository.update(existing.id, expected_version=expected_version, changes=clean)
    await _changed(session, row, "saved")
    return row


# --- saved views ------------------------------------------------------------------------------


async def _name(
    session: AsyncSession,
    user_id: uuid.UUID,
    spec: ListSpec,
    raw: object,
    *,
    other_than: uuid.UUID | None = None,
) -> str:
    name, problems = rules.clean_name(raw)
    _refuse(problems)
    assert name is not None  # noqa: S101 - _refuse raised otherwise
    taken = select(ListSetting.id).where(
        ListSetting.user_id == user_id,
        ListSetting.list_key == spec.key,
        ListSetting.deleted_at.is_(None),
        func.lower(ListSetting.name) == name.lower(),
    )
    if other_than is not None:
        taken = taken.where(ListSetting.id != other_than)
    if await session.scalar(taken.limit(1)) is not None:
        _refuse([rules.Problem("name", "duplicate_name")])
    return name


async def create_saved_view(
    session: AsyncSession, user_id: uuid.UUID, spec: ListSpec, values: Mapping[str, Any]
) -> ListSetting:
    """Save a view of the list for the person: a name, the list's filter, columns and sort."""
    count = await session.scalar(
        select(func.count()).where(
            ListSetting.user_id == user_id,
            ListSetting.list_key == spec.key,
            ListSetting.name.is_not(None),
            ListSetting.deleted_at.is_(None),
        )
    )
    if (count or 0) >= rules.MAX_SAVED_VIEWS:
        _refuse([rules.Problem("name", "too_many_items", (("max", rules.MAX_SAVED_VIEWS),))])
    name = await _name(session, user_id, spec, values.get("name"))
    columns, problems = rules.clean_columns(values.get("columns"))
    _refuse(problems)
    allowed = await _allowed(session, spec)
    view_id = new_id()
    row = await _Settings(session).add(
        ListSetting(
            id=view_id,
            user_id=user_id,
            list_key=spec.key,
            view_key=rules.custom_key(view_id),
            name=name,
            filter=_filter(values.get("filter"), allowed),
            columns=columns,
            sort=_sort(values.get("sort"), allowed),
            page_size=rules.DEFAULT_PAGE_SIZE,
            favourite=bool(values.get("favourite", False)),
        )
    )
    await _changed(session, row, "saved")
    return row


async def _saved(
    session: AsyncSession, user_id: uuid.UUID, spec: ListSpec, view_id: uuid.UUID
) -> ListSetting:
    row = await _row(session, user_id, spec, rules.custom_key(view_id))
    if row is None:
        raise NotFound(code="saved_view_not_found")
    return row


async def update_saved_view(  # noqa: PLR0913 - the view, its version and the change, explicit
    session: AsyncSession,
    user_id: uuid.UUID,
    spec: ListSpec,
    view_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
) -> ListSetting:
    """Rename a saved view or change its filter, columns, sort or star (only the fields sent)."""
    row = await _saved(session, user_id, spec, view_id)
    if row.version != expected_version:
        raise _stale(row.version, expected_version)
    allowed = await _allowed(session, spec)
    changes: dict[str, Any] = {}
    if "name" in values:
        changes["name"] = await _name(session, user_id, spec, values["name"], other_than=row.id)
    if "filter" in values:
        changes["filter"] = _filter(values["filter"], allowed)
    if "columns" in values:
        columns, problems = rules.clean_columns(values["columns"])
        _refuse(problems)
        changes["columns"] = columns
    if "sort" in values:
        changes["sort"] = _sort(values["sort"], allowed)
    if values.get("favourite") is not None:
        changes["favourite"] = bool(values["favourite"])
    if not changes:
        return row
    updated = await _Settings(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    await _changed(session, updated, "saved")
    return updated


async def delete_saved_view(
    session: AsyncSession,
    user_id: uuid.UUID,
    spec: ListSpec,
    view_id: uuid.UUID,
    *,
    expected_version: int,
) -> None:
    """Remove a saved view (soft delete, with its settings and star)."""
    row = await _saved(session, user_id, spec, view_id)
    removed = await _Settings(session).soft_delete(row.id, expected_version=expected_version)
    await _changed(session, removed, "removed")
