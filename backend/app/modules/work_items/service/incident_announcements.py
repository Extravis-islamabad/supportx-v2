"""Announcing from an incident (WP-046b S4, REQ-INC-129; lane B's and lane C's conditions).

The announcements module makes and ends the announcement with the actor's own rights, scope and
audience rules (its public interface only); this module keeps which announcements were made from
which incident (`work_item_announcements`), and that link grants nobody anything.

- The text is the actor's: the dialog starts from the subject and display ID only (never the
  description, notes, custom fields or requester) and the actor edits it before anything is
  published. Nothing is announced or ended without a person asking.
- Resolving offers to end the linked announcements; nothing ends by itself. A merged or converted
  incident's announcement keeps its own lifecycle.
- The incident's history names the link (`announcements`, the announcement's display ID); the
  audit entry is the announcement's own, plus `incident.announced` with IDs only.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.announcements import (
    Announced,
    announce_for_record,
    announcement_states,
    end_for_record,
)
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import RequestFacts
from app.modules.audit import record as record_audit
from app.modules.identity_access import PolicyService, Subject
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem, WorkItemAnnouncement
from app.modules.work_items.service import work_items as items
from app.shared.history import Change, Source, record_changes

ANNOUNCED = "incident.announced"
FIELD = "announcements"  # how the incident's history names the link


async def _linked_ids(session: AsyncSession, record_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(WorkItemAnnouncement.announcement_id)
        .where(
            WorkItemAnnouncement.work_item_id == record_id,
            WorkItemAnnouncement.deleted_at.is_(None),
        )
        .order_by(WorkItemAnnouncement.created_at, WorkItemAnnouncement.id)
    )
    return list(rows)


async def _history(
    session: AsyncSession, record: WorkItem, display_id: str, source: Source
) -> None:
    """The incident's history names the link, as a part added (no new version of the record)."""
    await record_changes(
        session,
        record_type=items.RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_added",
        changes=[Change(FIELD, None, display_id)],
        source=source,
    )


async def announce(  # noqa: PLR0913 - the incident, the text, its audience and where from
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    values: Mapping[str, Any],
    publish: bool,
    source: Source,
    holders: PolicyService,
    facts: RequestFacts | None = None,
) -> Announced:
    """An announcement from the actor's text, linked to the incident they may edit."""
    record = await items.record_for_action(session, subject, INCIDENT, "edit", record_id)
    made = await announce_for_record(
        session, subject, values=values, publish=publish, source=source, holders=holders
    )
    session.add(
        WorkItemAnnouncement(
            tenant_id=record.tenant_id, work_item_id=record.id, announcement_id=made.id
        )
    )
    await session.flush()
    await _history(session, record, made.display_id, source)
    await record_audit(
        session,
        action_code=ANNOUNCED,
        facts=facts or AUDIT_WORKER,
        object_type=INCIDENT.code.value,
        object_id=str(record.id),
        details={"announcement_id": str(made.id), "published": made.status == "published"},
    )
    return made


async def linked(session: AsyncSession, subject: Subject, record_id: uuid.UUID) -> list[Announced]:
    """The incident's announcements the actor may see (others are left out, never named)."""
    record = await items.visible_record(session, subject, INCIDENT, record_id)
    return await announcement_states(session, subject, await _linked_ids(session, record.id))


async def end(  # noqa: PLR0913 - the incident, the announcement, the reason and where from
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    announcement_id: uuid.UUID,
    *,
    reason: str | None,
    source: Source,
) -> Announced:
    """End one announcement made from this incident (404 for any other; its own rights)."""
    record = await items.visible_record(session, subject, INCIDENT, record_id)
    if announcement_id not in await _linked_ids(session, record.id):
        raise NotFound(code="announcement_not_found")
    # The link stays (the incident still names it); the announcement's own history and audit
    # entry record the end.
    return await end_for_record(session, subject, announcement_id, reason=reason, source=source)
