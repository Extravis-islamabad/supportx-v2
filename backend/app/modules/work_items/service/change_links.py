"""A change made from another record (WP-045a D6; REQ-CHG-002).

From an incident, a service request, a problem or a release the person may see: the form is
pre-filled from it (`prefill`, every value still editable, AC3), and the new change is linked
to it as `change_for` (the change -> its source), recorded on both records (AC1). CIs and
assets come with the CMDB (lane B's WP-049/050).
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.identity_access import Subject
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemLink
from app.modules.work_items.service import parts
from app.modules.work_items.service import work_items as items
from app.shared.history import Source

SOURCES = frozenset(
    {
        WorkItemTypeCode.INCIDENT,
        WorkItemTypeCode.SERVICE_REQUEST,
        WorkItemTypeCode.PROBLEM,
        WorkItemTypeCode.RELEASE,
    }
)


async def _source(session: AsyncSession, subject: Subject, record_id: uuid.UUID) -> WorkItem:
    """A record a change may be made from, which the subject may see (else 404, never why)."""
    found = await session.get(WorkItem, record_id)
    code = WorkItemTypeCode(found.type) if found is not None else None
    if found is None or code not in SOURCES:
        raise NotFound(code="change_source_not_found")
    return await items.visible_record(session, subject, TYPES[code], record_id)


async def prefill(session: AsyncSession, subject: Subject, record_id: uuid.UUID) -> dict[str, Any]:
    """A new change's starting values from the record (REQ-CHG-002); the form may edit each."""
    source = await _source(session, subject, record_id)
    return {
        "subject": source.subject,
        "description": source.description,
        "requester_id": source.requester_id,
        "impact": source.impact,
        "urgency": source.urgency,
        "site_id": source.site_id,
        "from_record_id": source.id,
    }


async def link_new(
    session: AsyncSession,
    subject: Subject,
    change: WorkItem,
    record_id: uuid.UUID,
    *,
    source: Source,
) -> WorkItemLink:
    """Link a just-made change to the record it was made from, with history on both (AC1)."""
    origin = await _source(session, subject, record_id)
    link = await parts.LinkRepository(session).add(
        WorkItemLink(source_id=change.id, target_id=origin.id, kind=LinkKind.CHANGE_FOR.value)
    )
    await parts.link_recorded(session, change, origin, link, "child_added", source)
    return link
