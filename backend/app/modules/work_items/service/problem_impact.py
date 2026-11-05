"""A problem's impact and evidence from the incidents it causes (WP-044b; REQ-PRB-032, -033).

Counted only over the caused incidents the subject may see, so the figures never leak a record
they could not open. `partial` says some caused incidents were left out, so the screen shows
"from the incidents you can see" instead of presenting a smaller number as the whole.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, distinct, func, select
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


def _caused(problem_id: uuid.UUID) -> Select[uuid.UUID]:
    """The incidents the problem causes (live links)."""
    return select(WorkItemLink.source_id).where(
        WorkItemLink.target_id == problem_id,
        WorkItemLink.kind == LinkKind.CAUSED_BY.value,
        WorkItemLink.deleted_at.is_(None),
    )


async def impact(session: AsyncSession, subject: Subject, problem_id: uuid.UUID) -> Impact:
    """The problem's impact (404 when the subject may not see the problem)."""
    await problems.problem_of(session, subject, problem_id)
    caused = _caused(problem_id)
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


# Evidence sources not there yet (REQ-PRB-032): changes and releases on the affected items join
# when those types are registered (WP-045, lane C's releases), other problems on the same items
# with the CMDB (lane B). Named so the panel says what is missing; never faked.
PENDING_SOURCES = ("changes", "releases", "same_items")
EVIDENCE_LIMIT = 200


@dataclass(frozen=True)
class EvidenceIncident:
    """One caused incident on the timeline, by when it was reported."""

    id: uuid.UUID
    display_id: str
    subject: str
    priority: str
    status: str
    status_category: str
    site_id: uuid.UUID | None
    reported_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True)
class Evidence:
    """The evidence panel's timeline (REQ-PRB-032)."""

    incidents: list[EvidenceIncident]
    left_out: bool  # caused incidents the subject may not see, or past the limit
    pending_sources: tuple[str, ...]


async def evidence(session: AsyncSession, subject: Subject, problem_id: uuid.UUID) -> Evidence:
    """The visible caused incidents, oldest report first (404 when the problem is not visible)."""
    await problems.problem_of(session, subject, problem_id)
    caused = _caused(problem_id)
    rows = list(
        await session.scalars(
            items.staff_rows(subject, INCIDENT)
            .where(WorkItem.id.in_(caused))
            .order_by(WorkItem.created_at, WorkItem.id)
            .limit(EVIDENCE_LIMIT + 1)
        )
    )
    total = await session.scalar(
        select(func.count())
        .select_from(WorkItem)
        .where(WorkItem.id.in_(caused), WorkItem.deleted_at.is_(None))
    )
    shown = rows[:EVIDENCE_LIMIT]
    return Evidence(
        incidents=[
            EvidenceIncident(
                id=r.id,
                display_id=r.display_id,
                subject=r.subject,
                priority=r.priority,
                status=r.status,
                status_category=r.status_category,
                site_id=r.site_id,
                reported_at=r.created_at,
                resolved_at=r.resolved_at,
            )
            for r in shown
        ],
        left_out=int(total or 0) > len(shown),
        pending_sources=PENDING_SOURCES,
    )
