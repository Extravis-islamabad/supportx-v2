"""What other modules may ask about incidents (D-121; written by lane C, reviewed by lane A).

Every answer uses the read rule of `GET /incidents/{id}`: the subject's view scope
(`staff_rows`, the same `scope_filter` the list and `_may` apply, requesters included: their own
incidents and those on behalf of them), live records only (trash never). Nothing about a record
the subject could not open is ever returned, not even that it exists.
"""

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import INCIDENT, WorkItemType
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service.work_items import staff_rows
from app.shared.records.ports import (
    BATCH_MAX,
    Actor,
    RecordPeople,
    RecordResolution,
    RecordSummary,
    register_record_facts,
)

_ARABIC = re.compile("[؀-ۿݐ-ݿࢠ-ࣿ]")


class WorkItemFacts:
    """The port for one work-item type."""

    def __init__(self, wtype: WorkItemType) -> None:
        self.wtype = wtype
        self.record_type = wtype.code.value

    async def visible(
        self, session: AsyncSession, subject: Actor, ids: Iterable[uuid.UUID]
    ) -> set[uuid.UUID]:
        """The ids `subject` may open."""
        wanted = list(dict.fromkeys(ids))
        if len(wanted) > BATCH_MAX:
            msg = f"at most {BATCH_MAX} ids per call, got {len(wanted)}"
            raise ValueError(msg)
        if not wanted or not isinstance(subject, Subject):
            return set()
        if not subject.holds(self.wtype.permission("view")):
            return set()
        rows = await session.scalars(
            staff_rows(subject, self.wtype)
            .where(WorkItem.id.in_(wanted))
            .with_only_columns(WorkItem.id)
        )
        return set(rows)

    async def summaries(
        self, session: AsyncSession, subject: Actor, ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, RecordSummary]:
        """List lines of the records `subject` may open, by the same rule as `visible`."""
        shown = await self.visible(session, subject, ids)
        if not shown:
            return {}
        rows = await session.scalars(select(WorkItem).where(WorkItem.id.in_(shown)))
        return {r.id: RecordSummary(r.id, r.display_id, r.subject, r.status_category) for r in rows}

    async def _one(
        self, session: AsyncSession, subject: Actor, record_id: uuid.UUID
    ) -> WorkItem | None:
        if not await self.visible(session, subject, [record_id]):
            return None
        found: WorkItem | None = await session.scalar(
            select(WorkItem).where(WorkItem.id == record_id, WorkItem.deleted_at.is_(None))
        )
        return found

    async def requester_of(
        self, session: AsyncSession, subject: Actor, record_id: uuid.UUID
    ) -> RecordPeople | None:
        """Requester and on-behalf-of, when `subject` may open the record."""
        record = await self._one(session, subject, record_id)
        if record is None:
            return None
        return RecordPeople(record.requester_id, record.on_behalf_of_id)

    async def resolution_of(
        self, session: AsyncSession, subject: Actor, record_id: uuid.UUID
    ) -> RecordResolution | None:
        """Subject, resolution (sanitised when saved) and its language; None without one."""
        record = await self._one(session, subject, record_id)
        if record is None or not (record.resolution or "").strip():
            return None
        text = record.resolution or ""
        # The record keeps no language; the resolution's letters say which it is written in.
        language = "ar" if _ARABIC.search(text) else "en"
        return RecordResolution(subject=record.subject, resolution_html=text, language=language)


def register() -> None:
    """Called when the module is imported (the consumers worker too)."""
    register_record_facts(WorkItemFacts(INCIDENT))
