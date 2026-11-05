"""A problem's impact from the incidents it causes (WP-044b; REQ-PRB-031).

Counted only over the caused incidents the subject may see, so the figures never leak a record
they could not open. `partial` says some caused incidents were left out, so the screen shows
"from the incidents you can see" instead of presenting a smaller number as the whole.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem, WorkItemLink, WorkItemWorklog
from app.modules.work_items.service import problems
from app.modules.work_items.service import work_items as items

_DONE = (StatusCategory.RESOLVED.value, *(c.value for c in FINAL_CATEGORIES))


@dataclass(frozen=True)
class Impact:
    """Counts over the visible caused incidents."""

    incidents: int
    open_incidents: int
    by_priority: dict[str, int]
    by_site: dict[uuid.UUID | None, int]
    people: int  # distinct requesters (and those they raised it for)
    minutes: int  # time logged on those incidents
    partial: bool


async def impact(session: AsyncSession, subject: Subject, problem_id: uuid.UUID) -> Impact:
    """The problem's impact (404 when the subject may not see the problem)."""
    await problems.problem_of(session, subject, problem_id)
    caused = select(WorkItemLink.source_id).where(
        WorkItemLink.target_id == problem_id,
        WorkItemLink.kind == LinkKind.CAUSED_BY.value,
        WorkItemLink.deleted_at.is_(None),
    )
    visible = items.staff_rows(subject, INCIDENT).where(WorkItem.id.in_(caused)).subquery("visible")
    all_caused = await session.scalar(
        select(func.count())
        .select_from(WorkItem)
        .where(WorkItem.id.in_(caused), WorkItem.deleted_at.is_(None))
    )
    priorities: dict[str, int] = {}
    for priority, count in await session.execute(
        select(visible.c.priority, func.count()).group_by(visible.c.priority)
    ):
        priorities[str(priority)] = int(count)
    sites: dict[uuid.UUID | None, int] = {}
    for site_id, count in await session.execute(
        select(visible.c.site_id, func.count()).group_by(visible.c.site_id)
    ):
        sites[site_id] = int(count)
    open_count = await session.scalar(
        select(func.count()).select_from(visible).where(visible.c.status_category.not_in(_DONE))
    )
    requesters = select(visible.c.requester_id.label("person")).union(
        select(visible.c.on_behalf_of_id).where(visible.c.on_behalf_of_id.is_not(None))
    )
    people = await session.scalar(select(func.count(distinct(requesters.subquery().c.person))))
    minutes = await session.scalar(
        select(func.coalesce(func.sum(WorkItemWorklog.minutes), 0)).where(
            WorkItemWorklog.work_item_id.in_(select(visible.c.id)),
            WorkItemWorklog.deleted_at.is_(None),
        )
    )
    total = sum(priorities.values())
    return Impact(
        incidents=total,
        open_incidents=int(open_count or 0),
        by_priority=priorities,
        by_site=sites,
        people=int(people or 0),
        minutes=int(minutes or 0),
        partial=int(all_caused or 0) > total,
    )
