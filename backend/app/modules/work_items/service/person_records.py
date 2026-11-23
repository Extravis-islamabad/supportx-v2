"""The records a person requested, for other modules' erasure ports (ADR-052; lane C's ai port).

IDs only, never their content: the records where the person is the requester or the one a
request was raised for (`on_behalf_of`), deleted ones included (their summaries and
embeddings go too). Not the records they only created for someone else. In the caller's tenant
session (RLS), keyset-paged by ID so a batched erasure resumes where it stopped.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.infra.models import WorkItem

PAGE_MAX = 500


async def records_requested_by(
    session: AsyncSession,
    person_id: uuid.UUID,
    *,
    cursor: str | None = None,
    limit: int = PAGE_MAX,
) -> tuple[list[tuple[str, uuid.UUID]], str | None]:
    """(record type, record ID) pairs, oldest ID first, and the cursor for the next page.

    `cursor` is the previous page's answer (an ID; None to start); None back means the end.
    """
    size = max(1, min(limit, PAGE_MAX))
    query = (
        select(WorkItem.type, WorkItem.id)
        .where(or_(WorkItem.requester_id == person_id, WorkItem.on_behalf_of_id == person_id))
        .order_by(WorkItem.id)
        .limit(size + 1)
    )
    if cursor is not None:
        query = query.where(WorkItem.id > uuid.UUID(cursor))
    rows = (await session.execute(query)).all()
    found = [(str(row.type), row.id) for row in rows[:size]]
    following = str(found[-1][1]) if len(rows) > size and found else None
    return found, following


__all__ = ["PAGE_MAX", "records_requested_by"]
