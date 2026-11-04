"""What the AI features may read of an incident, answered by the module that owns it (WP-038).

The ai module never reads work item tables (§6.1). It asks here, through checks registered at
start-up:

- `may_view_incident`: the record page's own check (scope and record rules, D-052), so AI never
  works on a record the person could not open.
- `conversation_for`: the description, replies and notes as that person sees them on the record
  page (staff see private notes; nothing beyond `timeline`), filtered to the sources the tenant's
  admin chose for summaries. The newest entry's ID tells whether a summary is still current.
- `incident_texts`: subject and description, the text possible duplicates compare (embeddings).
"""

import uuid
from collections.abc import Collection, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.ai import ConversationEntry, ConversationText
from app.modules.identity_access import Subject
from app.modules.work_items.domain.conversation import EntryKind, Visibility
from app.modules.work_items.domain.plain import plain_text
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import conversations
from app.modules.work_items.service import work_items as items


async def may_view_incident(session: AsyncSession, subject: Subject, record_id: uuid.UUID) -> bool:
    """Whether the subject may open the incident (the record page's own check)."""
    if not subject.holds(INCIDENT.permission("view")):
        return False
    try:
        await items.visible_record(session, subject, INCIDENT, record_id)
    except NotFound:
        return False
    return True


def _wanted(kind: str, visibility: str, sources: Collection[str]) -> bool:
    if kind == EntryKind.REPLY:
        return "replies" in sources
    if visibility == Visibility.PRIVATE:
        return "private_notes" in sources
    return "public_notes" in sources


async def conversation_for(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID, sources: Collection[str]
) -> ConversationText:
    """The incident's text the subject may see, from `sources` (404 when not visible)."""
    timeline = await conversations.timeline(session, subject, INCIDENT, record_id)
    # Display names only: the e-mail addresses beside them (user_contacts) never reach a prompt.
    names = {key: name for key, (name, _email) in timeline.names.items()}
    entries = tuple(
        ConversationEntry(
            kind=e.kind,
            visibility=e.visibility,
            author=names.get(str(e.created_by), "") if e.created_by else "",
            at=e.created_at,
            text=plain_text(e.body),
        )
        for e in timeline.entries
        if _wanted(e.kind, e.visibility, sources)
    )
    last = timeline.entries[-1].id if timeline.entries else None
    record = timeline.record
    return ConversationText(
        record_id=record.id,
        display_id=record.display_id,
        title=record.subject,
        description=plain_text(record.description) if "description" in sources else "",
        entries=entries,
        last_entry_id=last,
        names=tuple(sorted({n for n in names.values() if n})),
        private_included="private_notes" in sources,
    )


async def incident_texts(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> Mapping[uuid.UUID, Sequence[str]]:
    """Subject and description of live incidents, one piece each (for embeddings)."""
    rows = await session.execute(
        select(WorkItem.id, WorkItem.subject, WorkItem.description).where(
            WorkItem.id.in_(ids),
            WorkItem.type == INCIDENT.code,
            WorkItem.deleted_at.is_(None),
        )
    )
    return {
        record_id: [f"{subject}\n{plain_text(description)}".strip()]
        for record_id, subject, description in rows.all()
    }


async def incident_ids(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    """The newest live incidents' IDs (backfilling the AI index)."""
    rows = await session.scalars(
        select(WorkItem.id)
        .where(WorkItem.type == INCIDENT.code, WorkItem.deleted_at.is_(None))
        .order_by(WorkItem.created_at.desc())
        .limit(limit)
    )
    return list(rows.all())
