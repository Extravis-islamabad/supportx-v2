"""Records that use a site, group, department or catalog item: such a thing cannot be removed.

Registered with the organization module's usage registry (WP-021) and the service catalog's
ports (WP-031), which cannot read this module's tables (CLAUDE.md rule e). Every live record
counts, closed ones too: removing the unit would leave them pointing at nothing. For a catalog
item every record counts, deleted ones too (the item is retired instead, plan D3).

The catalog also asks which templates may be its "report a problem" entries (REQ-CAT-003): a
live incident template marked for requesters.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization import register_usage
from app.modules.service_catalog import register_item_usage, register_template_check
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem, WorkItemTemplate


async def _records_using(column: Any, session: AsyncSession, unit_id: uuid.UUID) -> int:  # noqa: ANN401 - a WorkItem column
    count = await session.scalar(
        select(func.count())
        .select_from(WorkItem)
        .where(column == unit_id, WorkItem.deleted_at.is_(None))
    )
    return int(count or 0)


async def _at_site(session: AsyncSession, unit_id: uuid.UUID) -> int:
    return await _records_using(WorkItem.site_id, session, unit_id)


async def _in_group(session: AsyncSession, unit_id: uuid.UUID) -> int:
    return await _records_using(WorkItem.group_id, session, unit_id)


async def _in_department(session: AsyncSession, unit_id: uuid.UUID) -> int:
    return await _records_using(WorkItem.department_id, session, unit_id)


async def _from_item(session: AsyncSession, item_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count()).select_from(WorkItem).where(WorkItem.catalog_item_id == item_id)
    )
    return int(count or 0)


async def _entry_template(
    session: AsyncSession, template_id: uuid.UUID
) -> Mapping[str, str] | None:
    """The template's names if it may be a catalog entry; None otherwise."""
    row = await session.scalar(
        select(WorkItemTemplate).where(
            WorkItemTemplate.id == template_id,
            WorkItemTemplate.type == INCIDENT.code,
            WorkItemTemplate.for_requesters.is_(True),
            WorkItemTemplate.disabled_at.is_(None),
            WorkItemTemplate.deleted_at.is_(None),
        )
    )
    if row is None:
        return None
    return dict(row.labels or {}) or {"en": row.code or ""}


def register_record_usage() -> None:
    """Called when the module is imported."""
    register_usage("site", "records", _at_site)
    register_usage("group", "records", _in_group)
    register_usage("department", "records", _in_department)
    register_item_usage(_from_item)
    register_template_check(_entry_template)
