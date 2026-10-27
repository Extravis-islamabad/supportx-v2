"""Records that use a site, group or department (WP-021): such a unit cannot be removed.

Registered with the organization module's usage registry, which cannot read this module's tables
(CLAUDE.md rule e). Every live record counts, closed ones too: removing the unit would leave
them pointing at nothing.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization import register_usage
from app.modules.work_items.infra.models import WorkItem


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


def register_record_usage() -> None:
    """Called when the module is imported."""
    register_usage("site", "records", _at_site)
    register_usage("group", "records", _in_group)
    register_usage("department", "records", _in_department)
