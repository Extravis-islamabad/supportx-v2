"""The portal home's summary of the person's own work (WP-032 D1; REQ-PRT-002).

Their own open requests (incidents and service requests they raised or that are for them) by
the status they are told, the approvals waiting for them, and their open tasks. Counts only:
the lists stay on their own pages. The home refetches it on the person's channels, so it moves
within a second of a technician's change (AC1).
"""

import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.parts import TaskStatus
from app.modules.work_items.domain.portal import PortalStatus, portal_status
from app.modules.work_items.domain.types import INCIDENT, SERVICE_REQUEST
from app.modules.work_items.infra.models import WorkItem, WorkItemTask
from app.modules.work_items.service import approvals
from app.modules.work_items.service.portal import OPEN_CATEGORIES


@dataclass(frozen=True)
class PortalSummary:
    """Counts for the home page."""

    open_by_status: dict[PortalStatus, int]
    approvals: int
    tasks: int


def _mine(user_id: uuid.UUID) -> ColumnElement[bool]:
    return or_(WorkItem.requester_id == user_id, WorkItem.on_behalf_of_id == user_id)


async def summary(session: AsyncSession, subject: Subject) -> PortalSummary:
    """The signed-in person's own open requests, pending approvals and open tasks."""
    rows = await session.execute(
        select(WorkItem.status, WorkItem.status_category, func.count())
        .where(
            _mine(subject.user_id),
            WorkItem.type.in_([INCIDENT.code.value, SERVICE_REQUEST.code.value]),
            WorkItem.status_category.in_([c.value for c in OPEN_CATEGORIES]),
            WorkItem.deleted_at.is_(None),
        )
        .group_by(WorkItem.status, WorkItem.status_category)
    )
    by: Counter[PortalStatus] = Counter()
    for code, category, n in rows.all():
        by[portal_status(code, StatusCategory(category))] += n
    waiting = await approvals.mine(session, subject, SERVICE_REQUEST)
    tasks = await session.scalar(
        select(func.count())
        .select_from(WorkItemTask)
        .join(WorkItem, WorkItem.id == WorkItemTask.work_item_id)
        .where(
            WorkItemTask.owner_id == subject.user_id,
            WorkItemTask.status.in_([TaskStatus.OPEN.value, TaskStatus.IN_PROGRESS.value]),
            WorkItemTask.deleted_at.is_(None),
            WorkItem.deleted_at.is_(None),
        )
    )
    return PortalSummary(dict(by), len(waiting), int(tasks or 0))


__all__ = ["PortalSummary", "summary"]
