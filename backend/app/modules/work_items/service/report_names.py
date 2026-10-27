"""Names of categories, templates, statuses and levels for report files (WP-035).

Registered with the reporting port when this module is imported (the consumers worker runs no
startup hooks). Admin labels in the reader's language, else English, else the shipped label of
the code, as the console shows them (incidents/labels.ts).
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItemCategory, WorkItemTemplate
from app.modules.work_items.service.catalogue import load
from app.shared.labels import has_label, label
from app.shared.reporting import register_names

PATH_SEPARATOR = " \u203a "  # the single right-pointing angle quote of categoryPath (labels.ts)


def _pick(labels: Mapping[str, str] | None, language: str, shipped: str | None) -> str | None:
    found = (labels or {}).get(language) or (labels or {}).get("en")
    if found:
        return found
    if shipped is not None and has_label(shipped):
        return label(shipped, language)
    return None


def _ids(values: Sequence[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for value in values:
        try:
            out.append(uuid.UUID(value))
        except ValueError:
            continue
    return out


async def category_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """The full path (category, subcategory, item), as the incident screens show it."""
    del field
    rows = (
        await session.execute(
            select(
                WorkItemCategory.id,
                WorkItemCategory.parent_id,
                WorkItemCategory.code,
                WorkItemCategory.labels,
            ).where(WorkItemCategory.type == INCIDENT.code)
        )
    ).all()
    by_id = {row.id: row for row in rows}

    def name(row: Any) -> str:  # noqa: ANN401 - a result row
        shipped = f"work_item_category.{row.code}" if row.code else None
        return _pick(row.labels, language, shipped) or label("reports.unknown_value", language)

    out: dict[str, str] = {}
    for wanted in _ids(values):
        parts: list[str] = []
        current = by_id.get(wanted)
        seen: set[uuid.UUID] = set()
        while current is not None and current.id not in seen:  # a cycle would never end
            seen.add(current.id)
            parts.insert(0, name(current))
            current = by_id.get(current.parent_id) if current.parent_id else None
        if parts:
            out[str(wanted)] = PATH_SEPARATOR.join(parts)
    return out


async def template_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Template names."""
    del field
    rows = await session.execute(
        select(WorkItemTemplate.id, WorkItemTemplate.code, WorkItemTemplate.labels).where(
            WorkItemTemplate.id.in_(_ids(values))
        )
    )
    out: dict[str, str] = {}
    for row in rows:
        shipped = f"incident_template.{row.code}" if row.code else None
        if name := _pick(row.labels, language, shipped):
            out[str(row.id)] = name
    return out


async def status_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Incident statuses: the admin's labels, else the shipped one."""
    del field
    catalogue = await load(session, INCIDENT)
    wanted = set(values)
    out: dict[str, str] = {}
    for status in catalogue.statuses:
        if status.code in wanted:
            name = _pick(status.labels, language, f"work_item_status.{status.code}")
            if name:
                out[status.code] = name
    return out


async def level_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Support levels: the admin's labels, else the shipped one."""
    del field
    catalogue = await load(session, INCIDENT)
    wanted = set(values)
    out: dict[str, str] = {}
    for value in catalogue.reasons:
        if value.list == "level" and value.code in wanted:
            name = _pick(value.labels, language, f"level.{value.code}")
            if name:
                out[value.code] = name
    return out


def register() -> None:
    """Make these names available to report files (idempotent)."""
    register_names("category", category_names)
    register_names("template", template_names)
    register_names("incident.status", status_names)
    register_names("incident.level", level_names)
