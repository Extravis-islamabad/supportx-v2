"""Work items as the CMDB's linked-records port (WP-053 S5c; REQ-CMDB-019, D-158).

Registered from this module's __init__ into the CMDB's public `register_ci_linked_records` (lane
B's #635, rule 8). A CI's Associations tab lists the work items linked to it:

- **Visible only, on every call** (D-158, the coordinator's S5c condition): each page goes through
  the type's own staff view (`staff_rows`), the same filter the counts port uses, so the tab's list
  and its "open of total" agree and an unseen record is never listed, counted or hinted at.
- **"Open" as the counts port says it:** open or paused (`ci_links._OPEN`), so a row's `open` and
  the counter mean one thing.
- **Unknown kinds answer an empty page**, never an error naming the types (lane A's #635 note).
- **The cursor is opaque:** the last row's ID (UUIDv7, so creation order), as the asset panel's.
  Not `updated_at`, which moves while someone pages (rows would repeat or be skipped). A forged
  cursor only narrows the page: visibility is applied again on every call.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest
from app.modules import cmdb
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemCi
from app.modules.work_items.service import ci_links
from app.modules.work_items.service import work_items as items

PAGE_MAX = 100  # the CMDB clamps to its own PAGE_MAX too; this guards a direct call


def _record(row: WorkItem) -> cmdb.CiLinkedRecord:
    return cmdb.CiLinkedRecord(
        id=row.id,
        kind=str(row.type),
        display_id=row.display_id,
        subject=row.subject,
        status=row.status,
        open=row.status_category in ci_links.OPEN_CATEGORIES,
        updated_at=row.updated_at,
    )


def _after(cursor: str | None) -> uuid.UUID | None:
    if cursor is None:
        return None
    try:
        return uuid.UUID(cursor)
    except ValueError:
        raise BadRequest(code="invalid_cursor") from None


class WorkItemCiLinkedRecords:
    """The port, as the CMDB's `CiLinkedRecords` Protocol defines it."""

    async def linked_page(  # noqa: PLR0913 - the port's agreed signature
        self,
        session: AsyncSession,
        subject: Subject,
        ci_id: uuid.UUID,
        kind: str,
        *,
        cursor: str | None = None,
        limit: int = 25,
    ) -> tuple[Sequence[cmdb.CiLinkedRecord], str | None]:
        """One page of `kind`'s records linked to the CI that the reader may see, newest first."""
        after = _after(cursor)
        if kind not in cmdb.LINKED_TYPES:
            return [], None
        wtype = TYPES[WorkItemTypeCode(kind)]
        size = max(1, min(limit, PAGE_MAX))
        linked = select(WorkItemCi.work_item_id).where(
            WorkItemCi.ci_id == ci_id, WorkItemCi.deleted_at.is_(None)
        )
        query = items.staff_rows(subject, wtype).where(WorkItem.id.in_(linked))
        if after is not None:
            query = query.where(WorkItem.id < after)
        rows = list(await session.scalars(query.order_by(WorkItem.id.desc()).limit(size + 1)))
        page = rows[:size]
        following = str(page[-1].id) if len(rows) > size and page else None
        return [_record(r) for r in page], following

    async def ci_ids_of(self, session: AsyncSession, work_item_id: uuid.UUID) -> list[uuid.UUID]:
        """The CIs the record links now (its live links), for the tab's live updates."""
        return await ci_links.ci_ids_of(session, work_item_id)


PORT = WorkItemCiLinkedRecords()

__all__ = ["PORT", "WorkItemCiLinkedRecords"]
