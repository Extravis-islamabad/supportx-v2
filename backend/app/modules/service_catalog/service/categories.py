"""Catalog categories: a tree (WP-031 s1, plan D1; REQ-CAT-001).

Everyone signed in reads the categories; requesters only the enabled ones not below a disabled
one. Writing needs `catalog_items.manage`, follows If-Match, keeps field history and emits an
event in the same transaction. A category holding items or categories is not deleted (409 with
the counts); deleting is soft.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.identity_access import Subject
from app.modules.service_catalog.domain.catalog import (
    DESCRIPTION_MAX,
    category_problems,
    hidden_categories,
    icon_problems,
    text_problems,
)
from app.modules.service_catalog.domain.items import name_problems
from app.modules.service_catalog.events import ServiceCategoryChanged
from app.modules.service_catalog.infra.models import CatalogItem, ServiceCategory
from app.modules.service_catalog.service.common import invalid, is_staff, require_manage
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, ChangeKind, Source, record_changes

RECORD_TYPE = "service_category"
FIELDS = ("names", "descriptions", "sort_order", "parent_id", "icon", "enabled")


class CategoryRepository(Repository[ServiceCategory]):
    """Categories: versioned updates with If-Match."""

    model = ServiceCategory


async def tree(session: AsyncSession) -> dict[uuid.UUID, ServiceCategory]:
    """Every live category of the tenant, by ID."""
    rows = await session.scalars(
        select(ServiceCategory).where(ServiceCategory.deleted_at.is_(None))
    )
    return {row.id: row for row in rows}


async def hidden_ids(session: AsyncSession) -> set[uuid.UUID]:
    """Categories requesters do not see: disabled ones and everything below them."""
    rows = await tree(session)
    parents = {k: v.parent_id for k, v in rows.items()}
    return hidden_categories([k for k, v in rows.items() if not v.enabled], parents)


async def list_categories(session: AsyncSession, subject: Subject) -> list[ServiceCategory]:
    """Every live category in their order; requesters only the ones they may browse."""
    rows = sorted((await tree(session)).values(), key=lambda c: (c.sort_order, str(c.id)))
    if is_staff(subject):
        return rows
    hidden = await hidden_ids(session)
    return [row for row in rows if row.id not in hidden]


def _snapshot(row: ServiceCategory) -> dict[str, Any]:
    return {
        name: (str(v) if isinstance(v := getattr(row, name), uuid.UUID) else v) for name in FIELDS
    }


def _typed(values: Mapping[str, Any]) -> dict[str, Any]:
    """The API's JSON as the columns keep it (the parent as a UUID)."""
    out = dict(values)
    if out.get("parent_id") is not None:
        out["parent_id"] = uuid.UUID(str(out["parent_id"]))
    return out


def _shape_problems(values: Mapping[str, Any], *, creating: bool) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if creating or "names" in values:
        found += name_problems("names", values.get("names"), required=True)
    found += text_problems("descriptions", values.get("descriptions"), limit=DESCRIPTION_MAX)
    return found + icon_problems("icon", values.get("icon"))


async def _check_parent(
    session: AsyncSession, category_id: uuid.UUID | None, parent_id: uuid.UUID | None
) -> None:
    rows = await tree(session)
    problems = category_problems(category_id, parent_id, {k: v.parent_id for k, v in rows.items()})
    if problems:
        raise invalid(problems)


async def _emit(
    session: AsyncSession,
    row: ServiceCategory,
    changes: list[Change],
    *,
    kind: ChangeKind,
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind=kind,
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        ServiceCategoryChanged(category_id=row.id, changed_fields=[c.field for c in changes]),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_category(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> ServiceCategory:
    """A new category (an English name at least), at the root or under a parent."""
    require_manage(subject)
    values = _typed(values)
    if problems := _shape_problems(values, creating=True):
        raise invalid(problems)
    parent_id = values.get("parent_id")
    await _check_parent(session, None, parent_id)
    row = ServiceCategory(
        names=dict(values["names"]),
        descriptions=dict(values.get("descriptions") or {}),
        sort_order=values.get("sort_order", 0),
        parent_id=parent_id,
        icon=values.get("icon"),
        enabled=values.get("enabled", True),
    )
    await CategoryRepository(session).add(row)
    after = _snapshot(row)
    await _emit(
        session,
        row,
        [Change(k, None, v) for k, v in after.items() if v not in (None, {})],
        kind="created",
        source=source,
    )
    return row


async def _live(session: AsyncSession, category_id: uuid.UUID) -> ServiceCategory:
    row = await session.scalar(
        select(ServiceCategory).where(
            ServiceCategory.id == category_id, ServiceCategory.deleted_at.is_(None)
        )
    )
    if row is None:
        raise NotFound(code="service_category_not_found")
    return row


async def update_category(  # noqa: PLR0913 - the category, its version and the change
    session: AsyncSession,
    subject: Subject,
    category_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> ServiceCategory:
    """Change what is sent; unchanged input keeps the version and emits nothing."""
    require_manage(subject)
    row = await _live(session, category_id)
    values = _typed(values)
    if problems := _shape_problems(values, creating=False):
        raise invalid(problems)
    changes = {k: values[k] for k in FIELDS if k in values and getattr(row, k) != values[k]}
    if not changes:
        if row.version != expected_version:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": row.version},
            )
        return row
    if "parent_id" in changes:
        await _check_parent(session, row.id, changes["parent_id"])
    before = _snapshot(row)
    updated = await CategoryRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    after = _snapshot(updated)
    await _emit(
        session,
        updated,
        [Change(k, before[k], after[k]) for k in FIELDS if before[k] != after[k]],
        kind="updated",
        source=source,
    )
    return updated


async def category_usage(session: AsyncSession, category_id: uuid.UUID) -> dict[str, int]:
    """Live items (primary or extra) and categories below it."""
    items = await session.scalar(
        select(func.count())
        .select_from(CatalogItem)
        .where(
            CatalogItem.deleted_at.is_(None),
            or_(
                CatalogItem.category_id == category_id,
                CatalogItem.extra_category_ids.contains([category_id]),  # @> (GIN index)
            ),
        )
    )
    children = await session.scalar(
        select(func.count())
        .select_from(ServiceCategory)
        .where(ServiceCategory.parent_id == category_id, ServiceCategory.deleted_at.is_(None))
    )
    return {k: v for k, v in {"items": items or 0, "categories": children or 0}.items() if v}


async def delete_category(
    session: AsyncSession,
    subject: Subject,
    category_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Soft delete an empty category; 409 with the counts otherwise."""
    require_manage(subject)
    row = await _live(session, category_id)
    if used := await category_usage(session, row.id):
        raise Conflict(code="service_category_in_use", params=used)
    updated = await CategoryRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await _emit(
        session, updated, [Change("deleted_at", None, "deleted")], kind="deleted", source=source
    )


async def live_category_ids(session: AsyncSession, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of `ids` are live categories of the tenant."""
    if not ids:
        return set()
    rows = await session.scalars(
        select(ServiceCategory.id).where(
            ServiceCategory.id.in_(ids), ServiceCategory.deleted_at.is_(None)
        )
    )
    return set(rows)


__all__ = [
    "category_usage",
    "create_category",
    "delete_category",
    "hidden_ids",
    "list_categories",
    "live_category_ids",
    "tree",
    "update_category",
]
