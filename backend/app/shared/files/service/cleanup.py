"""Removing files for good (D-077 rule applied to files; plan section 7).

- A deleted attachment's object goes after its grace period (24 h, undo window), then its rows.
- Editor drafts nobody saved (24 h old) are removed.
- A purged record takes its files along (`purge_record`; called by the record purge, WI-020 AC3).
- Objects that could not be deleted earlier (storage down) are tried again.

Every removal lowers the tenant's usage in the same transaction. The audit entry of a purge is
written by the caller (shared code cannot reach the audit module); `Purged` says what went.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.shared.events import record_event
from app.shared.files.domain.states import FileState
from app.shared.files.events import FileChanged
from app.shared.files.infra.models import FileLink, StoredFile
from app.shared.files.ports import OwnerType
from app.shared.files.service.core import FileServices, lock_usage, now
from app.shared.storage import StorageUnavailable

log = get_logger(__name__)
DRAFT_LIFETIME = timedelta(hours=24)
BATCH = 500


@dataclass
class Purged:
    """What a purge removed (counts only: names are personal data and stay out of logs)."""

    files: int = 0
    bytes: int = 0
    left: int = 0  # objects storage refused to delete this time (tried again later)
    file_ids: list[uuid.UUID] = field(default_factory=list)


async def _purge(session: AsyncSession, services: FileServices, rows: list[StoredFile]) -> Purged:
    result = Purged()
    if not rows:
        return result
    counter = await lock_usage(session)
    for stored in rows:
        keys = [k for k in (stored.object_key, stored.thumb_key) if k is not None]
        if stored.state == FileState.INFECTED.value and stored.purge_after is None:
            keys = []  # objects already removed when it was blocked; usage already lowered
        try:
            for key in keys:
                if services.storage is not None:
                    await services.storage.delete(key)
        except StorageUnavailable:
            result.left += 1
            continue
        if keys and stored.state != FileState.INFECTED.value:
            counter.bytes_used = max(0, counter.bytes_used - stored.size)
            counter.files_count = max(0, counter.files_count - 1)
            result.bytes += stored.size
        await session.execute(delete(StoredFile).where(StoredFile.id == stored.id))
        result.files += 1
        result.file_ids.append(stored.id)
    return result


async def purge_due(session: AsyncSession, services: FileServices) -> Purged:
    """Deleted files past their grace period, and editor drafts nobody saved."""
    moment = now()
    due = list(
        await session.scalars(
            select(StoredFile)
            .where(StoredFile.purge_after.is_not(None), StoredFile.purge_after <= moment)
            .limit(BATCH)
        )
    )
    drafts = list(
        await session.scalars(
            select(StoredFile)
            .join(FileLink, FileLink.file_id == StoredFile.id)
            .where(
                FileLink.owner_type == OwnerType.DRAFT.value,
                StoredFile.created_at <= moment - DRAFT_LIFETIME,
            )
            .limit(BATCH)
        )
    )
    seen = {row.id for row in due}
    result = await _purge(session, services, due + [d for d in drafts if d.id not in seen])
    if result.files or result.left:
        log.info("files_purged", files=result.files, bytes=result.bytes, left=result.left)
    return result


async def purge_record(
    session: AsyncSession, services: FileServices, record_type: str, record_id: uuid.UUID
) -> Purged:
    """Every file of a record, now (the record itself is being purged)."""
    rows = list(
        await session.scalars(
            select(StoredFile)
            .join(FileLink, FileLink.file_id == StoredFile.id)
            .where(FileLink.record_type == record_type, FileLink.record_id == record_id)
        )
    )
    return await _purge(session, services, rows)


@dataclass(frozen=True)
class Forgotten:
    """What `forget_uploader` did: files deleted, and whether the batch was full (call again)."""

    deleted: int
    full: bool


async def forget_uploader(
    session: AsyncSession,
    uploader_id: uuid.UUID,
    *,
    keep: Collection[uuid.UUID] = (),
    limit: int = BATCH,
) -> "Forgotten":
    """A person's GDPR erasure (D-171 b, ADR-052 §4): the files they uploaded go.

    Every live file they uploaded (`created_by`), except those in `keep` (the admin kept them,
    each with a reason the erasure job audits), is deleted now and purged at the next purge
    run: no undo window, the person asked for it to go. Each deleted file's screens refresh
    (`system.file.changed`). Files already deleted wait no longer either. Idempotent: a second
    call deletes nothing and returns 0. At most `limit` files per call (the erasure job calls
    again while `full`, a call that used its whole limit). Returns how many it deleted.
    """
    moment = now()
    query = (
        select(StoredFile)
        .where(StoredFile.created_by == uploader_id)
        .where((StoredFile.deleted_at.is_(None)) | (StoredFile.purge_after > moment))
        .order_by(StoredFile.id)
        .limit(limit)
        .with_for_update()
    )
    if keep:
        query = query.where(StoredFile.id.not_in(list(keep)))
    rows = list(await session.scalars(query))
    deleted = 0
    for stored in rows:
        live = stored.deleted_at is None
        if live:
            stored.state = FileState.DELETED.value
            stored.deleted_at = moment
            stored.version += 1
            deleted += 1
        stored.purge_after = moment
        if not live:
            continue
        link = await session.scalar(
            select(FileLink)
            .where(FileLink.file_id == stored.id)
            .order_by(FileLink.created_at)
            .limit(1)
        )
        if link is not None:
            await record_event(
                session,
                FileChanged(
                    file_id=stored.id,
                    state=stored.state,
                    owner_type=link.owner_type,
                    owner_id=link.owner_id,
                    record_type=link.record_type,
                    record_id=link.record_id,
                ),
                aggregate_id=stored.id,
            )
    await session.flush()
    return Forgotten(deleted=deleted, full=len(rows) >= limit)
