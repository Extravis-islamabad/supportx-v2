"""Names of support groups, sites, departments and desks for report files (WP-035).

Registered with the reporting port (app/shared/reporting/names.py) when this module is imported,
so the consumers worker, which never runs startup hooks, has them too. Names of org units only:
anyone holding a report may read them (lane A's review, 2026-10-28).
"""

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.infra.models import Department, Desk, Site, SupportGroup
from app.shared.labels import has_label, label
from app.shared.reporting import register_names


def _ids(values: Sequence[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for value in values:
        try:
            out.append(uuid.UUID(value))
        except ValueError:
            continue
    return out


async def _named(
    session: AsyncSession, model: type[Site | SupportGroup | Department], values: Sequence[str]
) -> Mapping[str, str]:
    rows = await session.execute(select(model.id, model.name).where(model.id.in_(_ids(values))))
    return {str(row.id): row.name for row in rows}


async def group_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Support group names."""
    del language, field
    return await _named(session, SupportGroup, values)


async def site_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Site names."""
    del language, field
    return await _named(session, Site, values)


async def department_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Department names."""
    del language, field
    return await _named(session, Department, values)


async def desk_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Desk labels in the language, else English, else the shipped label of its code."""
    del field
    rows = await session.execute(
        select(Desk.id, Desk.code, Desk.labels).where(Desk.id.in_(_ids(values)))
    )
    out: dict[str, str] = {}
    for row in rows:
        labels = row.labels or {}
        shipped = f"desk.{row.code}"
        name = labels.get(language) or labels.get("en")
        if not name and has_label(shipped):
            name = label(shipped, language)
        if name:
            out[str(row.id)] = name
    return out


def register() -> None:
    """Make these names available to report files (idempotent)."""
    register_names("group", group_names)
    register_names("site", site_names)
    register_names("department", department_names)
    register_names("desk", desk_names)
