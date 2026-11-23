"""Business views: saved maps for one base CI (WP-053 S2; REQ-CMDB-009).

- **Who sees one:** anyone with `cmdb.view` who may see its base CI now; a view on a CI they may
  not see (or one in the trash) is never listed and is a 404. Its map is read through the
  VIEWER's own rights, never the owner's (lane C's condition 4): `GET …/neighbours` on the base
  with the view's filters, placeholders included. Pinned positions are given only for CIs the
  viewer may see, so a view never tells the ID of a CI hidden from them.
- **Who changes one:** creating (and "save as new") needs `cmdb.edit` (or `cmdb.manage`); the
  owner, or anyone with `cmdb.configure`, edits and removes it. Saving keeps the pinned positions
  of CIs the editor may not see, so an admin's save never drops what only the owner sees.
- **Save as new** makes a second view owned by the person, from the first with their changes;
  the first is left as it was (009 AC2).
- Every save writes field history (`ci_business_view`), raises `cmdb.business_view.changed`
  through the outbox, and moves to the successor when the owner is erased (person_data).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.events import BusinessViewChanged
from app.modules.cmdb.infra.models import BusinessView, Ci
from app.modules.cmdb.service.catalogue import CONFIGURE, EDIT, invalid
from app.modules.cmdb.service.cis import visible_rows, writer
from app.modules.identity_access import Subject, user_names
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes, stale_version

RECORD_TYPE = "ci_business_view"
EDITABLE = ("name", "description", "layout", "filters", "positions")
TEXT_FIELDS = ("name", "description", "layout")  # history keeps their values; the rest by name
FILTER_IDS_MAX = 50

VIEW_FIELDS = ResourceFields(
    name="business_views",
    fields={
        "id": FilterField(BusinessView.id, FieldType.UUID),
        "name": FilterField(BusinessView.name, FieldType.STRING, sortable=True),
        "base_ci_id": FilterField(BusinessView.base_ci_id, FieldType.UUID),
        "owner_id": FilterField(BusinessView.owner_id, FieldType.UUID),
        "updated_at": FilterField(
            BusinessView.updated_at, FieldType.DATETIME, sortable=True, simple=False
        ),
    },
    id_column=BusinessView.id,
    default_sort=("-updated_at",),
)


class BusinessViewRepository(Repository[BusinessView]):
    """Business views of the session's tenant."""

    model = BusinessView


@dataclass(frozen=True)
class BaseCi:
    """A view's base CI as its list and page name it."""

    id: uuid.UUID
    display_id: str
    name: str


@dataclass(frozen=True)
class ViewDetail:
    """One view as this reader may see it."""

    record: BusinessView
    positions: dict[str, Any]
    owner_name: str | None
    can_edit: bool
    can_delete: bool
    # Always the reader's: a view is seen only while its base CI is (lane C's condition 4); None
    # only if the CI was trashed during this very request.
    base_ci: BaseCi | None = None


def _seen_bases(subject: Subject) -> Any:  # noqa: ANN401 - a scalar subquery of CI IDs
    return visible_rows(subject).with_only_columns(Ci.id).scalar_subquery()


def visible_views(subject: Subject) -> Select[Any]:
    """Live views whose base CI the person may see now."""
    return select(BusinessView).where(
        BusinessView.deleted_at.is_(None), BusinessView.base_ci_id.in_(_seen_bases(subject))
    )


async def list_views(
    session: AsyncSession, subject: Subject, query: ListQuery
) -> PageResult[BusinessView]:
    """One page of views the person may see."""
    return await paginate(session, visible_views(subject), query)


async def _visible(session: AsyncSession, subject: Subject, view_id: uuid.UUID) -> BusinessView:
    row: BusinessView | None = await session.scalar(
        visible_views(subject).where(BusinessView.id == view_id)
    )
    if row is None:
        raise NotFound(code="cmdb_business_view_not_found")
    return row


def _may_change(subject: Subject, row: BusinessView) -> bool:
    return row.owner_id == subject.user_id or subject.holds(CONFIGURE)


async def _seen_ids(session: AsyncSession, subject: Subject, keys: Mapping[str, Any]) -> set[str]:
    ids = [uuid.UUID(k) for k in keys if _uuid(k)]
    if not ids:
        return set()
    query = visible_rows(subject).with_only_columns(Ci.id).where(Ci.id.in_(ids))
    return {str(i) for i in await session.scalars(query)}


def _uuid(text: str) -> bool:
    try:
        return str(uuid.UUID(text)) == text
    except ValueError:
        return False


async def base_cis(
    session: AsyncSession, subject: Subject, ids: list[uuid.UUID]
) -> dict[uuid.UUID, BaseCi]:
    """The base CIs of these views, through the reader's own rights (one query)."""
    if not ids:
        return {}
    query = (
        visible_rows(subject)
        .with_only_columns(Ci.id, Ci.display_id, Ci.name)
        .where(Ci.id.in_(set(ids)))
    )
    return {
        row.id: BaseCi(row.id, row.display_id, row.name) for row in await session.execute(query)
    }


async def detail(session: AsyncSession, subject: Subject, row: BusinessView) -> ViewDetail:
    """The view with only the positions of CIs this reader may see."""
    seen = await _seen_ids(session, subject, row.positions)
    names = await user_names(session, [str(row.owner_id)]) if row.owner_id else {}
    may = _may_change(subject, row)
    bases = await base_cis(session, subject, [row.base_ci_id])
    return ViewDetail(
        record=row,
        positions={k: v for k, v in row.positions.items() if k in seen},
        owner_name=names.get(str(row.owner_id)) if row.owner_id else None,
        can_edit=may,
        can_delete=may,
        base_ci=bases.get(row.base_ci_id),
    )


async def get_view(session: AsyncSession, subject: Subject, view_id: uuid.UUID) -> ViewDetail:
    """One view the person may see (404 otherwise)."""
    return await detail(session, subject, await _visible(session, subject, view_id))


def _filters(value: object) -> dict[str, Any]:
    """The map's filters as stored JSON (the route's schema checked their shape)."""
    if not isinstance(value, Mapping):
        raise invalid([domain.Problem("filters", "invalid_value")])
    out: dict[str, Any] = {}
    for key in ("relationship_type_ids", "ci_type_ids"):
        ids = value.get(key) or []
        if len(ids) > FILTER_IDS_MAX:
            raise invalid([domain.Problem(f"filters.{key}", "too_many")])
        out[key] = sorted({str(i) for i in ids})
    out["show_eol"] = bool(value.get("show_eol", False))
    depth = value.get("depth", 1)
    if not isinstance(depth, int) or not 1 <= depth <= rel.DEPTH_MAX:
        raise invalid([domain.Problem("filters.depth", "invalid_value")])
    out["depth"] = depth
    return out


def _text_problems(
    values: Mapping[str, Any], out: dict[str, Any], *, creating: bool
) -> list[domain.Problem]:
    problems: list[domain.Problem] = []
    if "name" in values or creating:
        name = values.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > domain.NAME_MAX:
            problems.append(domain.Problem("name", "invalid_value"))
        else:
            out["name"] = name.strip()
    if "description" in values:
        text = values["description"]
        if text is not None and (not isinstance(text, str) or len(text) > domain.DESCRIPTION_MAX):
            problems.append(domain.Problem("description", "value_too_long"))
        out["description"] = text or None
    if "layout" in values or creating:
        layout = values.get("layout", rel.BusinessViewLayout.RADIAL)
        if layout not in {item.value for item in rel.BusinessViewLayout}:
            problems.append(domain.Problem("layout", "invalid_choice"))
        out["layout"] = str(layout)
    return problems


def _position_problems(positions: object, out: dict[str, Any]) -> list[domain.Problem]:
    problems = rel.positions_problems(positions)
    if isinstance(positions, Mapping):
        if not all(_uuid(str(k)) for k in positions):
            problems.append(domain.Problem("positions", "invalid_key"))
        out["positions"] = {
            str(k): {"x": v["x"], "y": v["y"]}
            for k, v in positions.items()
            if isinstance(v, Mapping) and {"x", "y"} <= set(v)
        }
    return problems


def _check(values: Mapping[str, Any], *, creating: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    problems = _text_problems(values, out, creating=creating)
    if "positions" in values:
        problems += _position_problems(values["positions"] or {}, out)
    if problems:
        raise invalid(problems)
    if "filters" in values or creating:
        out["filters"] = _filters(values.get("filters") or {})
    return out


async def _positions_for(
    session: AsyncSession, subject: Subject, sent: Mapping[str, Any], stored: Mapping[str, Any]
) -> dict[str, Any]:
    """Sent positions of CIs the editor may see, plus the stored ones of CIs they may not."""
    seen_sent = await _seen_ids(session, subject, sent)
    seen_stored = await _seen_ids(session, subject, stored)
    kept = {k: v for k, v in stored.items() if k not in seen_stored}
    return {**kept, **{k: v for k, v in sent.items() if k in seen_sent}}


async def _history(  # noqa: PLR0913, PLR0917 - the view, the save and what changed, explicit
    session: AsyncSession,
    row: BusinessView,
    kind: Literal["created", "updated"],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    source: Source,
) -> list[str]:
    changed = [k for k in EDITABLE if before.get(k) != after.get(k)]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind=kind,
        changes=[
            Change(k, before.get(k), after.get(k)) if k in TEXT_FIELDS else Change(k, None, None)
            for k in changed
        ],
        source=source,
    )
    return changed


def _state(row: BusinessView) -> dict[str, Any]:
    return {k: getattr(row, k) for k in EDITABLE}


async def _event(session: AsyncSession, row: BusinessView, action: str, changed: list[str]) -> None:
    await record_event(
        session,
        BusinessViewChanged(
            view_id=row.id, base_ci_id=row.base_ci_id, action=action, changed_fields=changed
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


def _require_create(subject: Subject) -> None:
    if writer(subject, EDIT) is None:
        raise PermissionDenied(params={"permission": EDIT, "reason": "no_permission"})


async def _insert(
    session: AsyncSession,
    subject: Subject,
    base_ci_id: uuid.UUID,
    values: Mapping[str, Any],
    source: Source,
) -> BusinessView:
    if await session.scalar(visible_rows(subject).where(Ci.id == base_ci_id)) is None:
        raise NotFound(code="cmdb_ci_not_found")
    positions = values.get("positions") or {}
    seen = await _seen_ids(session, subject, positions)
    row = BusinessView(
        name=values["name"],
        description=values.get("description"),
        base_ci_id=base_ci_id,
        layout=values["layout"],
        filters=values["filters"],
        positions={k: v for k, v in positions.items() if k in seen},
        owner_id=subject.user_id,
    )
    await BusinessViewRepository(session).add(row)
    changed = await _history(session, row, "created", {}, _state(row), source)
    await _event(session, row, "created", changed)
    return row


async def create(
    session: AsyncSession,
    subject: Subject,
    base_ci_id: uuid.UUID,
    values: Mapping[str, Any],
    source: Source,
) -> ViewDetail:
    """A new view for a base CI the person may see, owned by them."""
    _require_create(subject)
    checked = _check(values, creating=True)
    return await detail(
        session, subject, await _insert(session, subject, base_ci_id, checked, source)
    )


async def save_as_new(
    session: AsyncSession,
    subject: Subject,
    view_id: uuid.UUID,
    values: Mapping[str, Any],
    source: Source,
) -> ViewDetail:
    """A second view from this one with the changes sent; this one is left as it was."""
    _require_create(subject)
    original = await _visible(session, subject, view_id)
    seen = await _seen_ids(session, subject, original.positions)
    base = {
        "name": original.name,
        "description": original.description,
        "layout": original.layout,
        "filters": original.filters,
        "positions": {k: v for k, v in original.positions.items() if k in seen},
    }
    checked = _check({**base, **values}, creating=True)
    checked.setdefault("positions", base["positions"])
    checked.setdefault("description", base["description"])
    row = await _insert(session, subject, original.base_ci_id, checked, source)
    return await detail(session, subject, row)


async def update(  # noqa: PLR0913 - the view, the version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    view_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> ViewDetail:
    """Change the fields sent (If-Match): the owner, or `cmdb.configure`."""
    row = await _visible(session, subject, view_id)
    if not _may_change(subject, row):
        raise PermissionDenied(code="cmdb_business_view_not_owner")
    checked = _check(values, creating=False)
    if "positions" in checked:
        checked["positions"] = await _positions_for(
            session, subject, checked["positions"], row.positions
        )
    before = _state(row)
    columns = {k: v for k, v in checked.items() if before.get(k) != v}
    if not columns:
        if row.version != expected_version:
            raise await stale_version(session, row, expected_version=expected_version)
        return await detail(session, subject, row)
    updated = await BusinessViewRepository(session).update(
        row.id, expected_version=expected_version, changes=columns
    )
    changed = await _history(session, updated, "updated", before, _state(updated), source)
    await _event(session, updated, "updated", changed)
    return await detail(session, subject, updated)


async def remove(
    session: AsyncSession,
    subject: Subject,
    view_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove (soft delete): the owner, or `cmdb.configure`."""
    row = await _visible(session, subject, view_id)
    if not _may_change(subject, row):
        raise PermissionDenied(code="cmdb_business_view_not_owner")
    deleted = await BusinessViewRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await _event(session, deleted, "deleted", [])
