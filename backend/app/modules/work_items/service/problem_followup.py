"""Follow-up on a problem's linked incidents (WP-044b s5; REQ-PRB-055, D-140 Q1).

When a problem is resolved or closed, the technician sees its open linked incidents (the ones
they may see), unticks any, and chooses what to copy: the resolution, the workaround or both.
The chosen incidents then go through the incidents' own bulk resolve job:
- each one through its own transition and closure rules;
- the result per incident and progress are shown live;
- each history names the problem.

They land in resolved, so each requester confirms or rejects the fix (REQ-INC-096). Nothing
is closed silently (Q1).
"""

import uuid
from collections.abc import Sequence
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDenied
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.lists import BulkAction
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import INCIDENT, PROBLEM
from app.modules.work_items.infra.models import WorkItem, WorkItemBulkJob, WorkItemLink
from app.modules.work_items.service import bulk, problems
from app.modules.work_items.service import work_items as items
from app.shared.history import Source
from app.shared.richtext import is_blank

_DONE = frozenset({StatusCategory.RESOLVED, *FINAL_CATEGORIES})


class CopyPart(StrEnum):
    """What each incident gets as its resolution."""

    RESOLUTION = "resolution"
    WORKAROUND = "workaround"
    BOTH = "both"


async def open_incidents(
    session: AsyncSession, subject: Subject, problem_id: uuid.UUID
) -> tuple[WorkItem, list[WorkItem]]:
    """The problem, and its linked incidents still open that the subject may see."""
    problem = await problems.problem_of(session, subject, problem_id)
    caused = select(WorkItemLink.source_id).where(
        WorkItemLink.target_id == problem.id,
        WorkItemLink.kind == LinkKind.CAUSED_BY.value,
        WorkItemLink.deleted_at.is_(None),
    )
    rows = await session.scalars(
        items.staff_rows(subject, INCIDENT)
        .where(WorkItem.id.in_(caused))
        .order_by(WorkItem.created_at, WorkItem.id)
    )
    return problem, [r for r in rows if StatusCategory(r.status_category) not in _DONE]


def _text(problem: WorkItem, part: CopyPart) -> str:
    parts = {
        CopyPart.RESOLUTION: [problem.resolution],
        CopyPart.WORKAROUND: [problem.workaround],
        CopyPart.BOTH: [problem.resolution, problem.workaround],
    }[part]
    return "".join(p for p in parts if p and not is_blank(p))


async def start(  # noqa: PLR0913 - the problem, the choice and the source
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    incident_ids: Sequence[uuid.UUID],
    *,
    copy: CopyPart,
    source: Source,
) -> WorkItemBulkJob:
    """Resolve the chosen open incidents with the problem's text (each through its own rules)."""
    problem, offered = await open_incidents(session, subject, problem_id)
    if not await items.may(session, subject, PROBLEM, "edit", problem.id):
        raise PermissionDenied(params={"permission": PROBLEM.permission("edit")})
    allowed = {i.id for i in offered}
    chosen = [i for i in dict.fromkeys(incident_ids) if i in allowed]
    if not chosen:
        raise items.field_errors([("incident_ids", "required")])
    text = _text(problem, copy)
    if is_blank(text):
        raise items.field_errors([("copy", "required")])
    return await bulk.start(
        session,
        subject,
        INCIDENT,
        action=BulkAction.RESOLVE,
        changes={"resolution": text, "follow_up_of": problem.display_id},
        record_ids=chosen,
        source=source,
    )
