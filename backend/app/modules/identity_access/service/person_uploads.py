"""A person's own uploads, listed for an erasure's "files to keep" (D-171, ADR-052).

The request names the files kept (each with a reason); everything else the person uploaded is
deleted. The person asking needs to see what there is to choose from:

- metadata only (name, size, type, date, and what the file is attached to by type), never the
  content and never a download link (the coordinator, 2026-11-17);
- the same files `_keep_problems` accepts: live, uploaded by the person;
- through the shared files tables (`app.shared.files`), never another module's tables.

The route asks for `people.erase` and audits each page listed.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.service.people import get_person
from app.shared.db.repository import decode_cursor, encode_cursor
from app.shared.files.infra.models import FileLink, StoredFile

LIST_LIMIT = 100


@dataclass(frozen=True)
class Upload:
    """One file the person uploaded: what it is, never what is in it."""

    id: uuid.UUID
    name: str
    size: int
    content_type: str
    created_at: datetime
    # What it is attached to, by type (`file_owner_type.*`); None: not attached (yet).
    attached_to: str | None


@dataclass(frozen=True)
class UploadPage:
    """One page, oldest first by ID, and the cursor of the next (None: the last page)."""

    items: list[Upload]
    next_cursor: str | None


async def person_uploads(
    session: AsyncSession, person_id: uuid.UUID, *, cursor: str | None, limit: int = LIST_LIMIT
) -> UploadPage:
    """The person's live uploads, a page at a time (404 for a person not found)."""
    await get_person(session, person_id)
    query = select(StoredFile).where(
        StoredFile.created_by == person_id, StoredFile.deleted_at.is_(None)
    )
    if cursor:
        query = query.where(StoredFile.id > decode_cursor(cursor))
    found = list(await session.scalars(query.order_by(StoredFile.id).limit(limit + 1)))
    more = len(found) > limit
    rows = found[:limit]
    owners: dict[uuid.UUID, str] = {}
    if rows:  # a file has exactly one link (app/shared/files)
        links = await session.execute(
            select(FileLink.file_id, FileLink.owner_type).where(
                FileLink.file_id.in_([r.id for r in rows])
            )
        )
        owners = {file_id: owner_type for file_id, owner_type in links.all()}  # noqa: C416 - Row pairs, typed
    items = [
        Upload(
            id=r.id,
            name=r.name,
            size=r.size,
            content_type=r.content_type,
            created_at=r.created_at,
            attached_to=owners.get(r.id),
        )
        for r in rows
    ]
    return UploadPage(items, encode_cursor(rows[-1].id) if more and rows else None)


__all__ = ["LIST_LIMIT", "Upload", "UploadPage", "person_uploads"]
