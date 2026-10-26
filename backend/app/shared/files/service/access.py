"""Seeing, opening and removing files (REQ-INC-079 AC3, AC4; ADR-028).

Every way in asks the owner module first (`FileOwnerAccess`): a file is visible exactly when its
owner is, and a private note's files only to the people who may see private notes. Opening also
needs a usable scan state. Downloads and previews go through a short-lived link bound to the user;
the content route checks the link and then the user's access again.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.shared.events import record_event
from app.shared.files.domain import tokens
from app.shared.files.domain.states import FileState, openable
from app.shared.files.domain.types import Kind, Sniffed, inline_allowed
from app.shared.files.events import FileChanged
from app.shared.files.infra import blobs
from app.shared.files.infra.models import FileLink, StoredFile
from app.shared.files.ports import Action, Actor, OwnerType, owner_access, record_access
from app.shared.files.service.core import FileServices, data_key, now


class LinkExpiredError(AppError):
    """The download link is past its lifetime: open the file again for a new one."""

    status: ClassVar[HTTPStatus] = HTTPStatus.GONE
    code: ClassVar[str] = "file_link_expired"


@dataclass(frozen=True)
class Attachment:
    """A file and where it is attached."""

    file: StoredFile
    link: FileLink
    private: bool = False


def _not_found() -> NotFound:
    return NotFound(code="file_not_found")


async def _attachment(session: AsyncSession, file_id: uuid.UUID) -> Attachment:
    row = (
        await session.execute(
            select(StoredFile, FileLink)
            .join(FileLink, FileLink.file_id == StoredFile.id)
            .where(StoredFile.id == file_id, StoredFile.deleted_at.is_(None))
        )
    ).one_or_none()
    if row is None:
        raise _not_found()
    return Attachment(row[0], row[1])


async def authorize(
    session: AsyncSession, actor: Actor, file_id: uuid.UUID, action: Action
) -> Attachment:
    """The file if `actor` may do `action` with it (NotFound when they may not see it)."""
    found = await _attachment(session, file_id)
    owner_type = OwnerType(found.link.owner_type)
    if owner_type == OwnerType.DRAFT:
        if found.link.owner_id != actor.user_id:
            raise _not_found()
        return found
    try:
        owner = await owner_access(owner_type).check(
            session, actor, owner_type, found.link.owner_id, action
        )
    except NotFound:
        raise _not_found() from None
    return Attachment(found.file, found.link, private=owner.private)


async def for_record(
    session: AsyncSession, actor: Actor, record_type: str, record_id: uuid.UUID
) -> list[Attachment]:
    """Every file on a record (the record itself, its replies and notes) the actor may see."""
    visible = await record_access(record_type).visible_owners(
        session, actor, record_type, record_id
    )
    rows = await session.execute(
        select(StoredFile, FileLink)
        .join(FileLink, FileLink.file_id == StoredFile.id)
        .where(
            FileLink.record_type == record_type,
            FileLink.record_id == record_id,
            StoredFile.deleted_at.is_(None),
        )
        .order_by(StoredFile.created_at, StoredFile.id)
    )
    return [
        Attachment(stored, link)
        for stored, link in rows.tuples()
        if (OwnerType(link.owner_type), link.owner_id) in visible
    ]


def _sniffed(stored: StoredFile) -> Sniffed:
    return Sniffed(stored.content_type, Kind(stored.kind), active_markup=stored.active_markup)


def _require_openable(services: FileServices, stored: StoredFile) -> None:
    if not openable(FileState(stored.state), scan_required=services.scan_required):
        raise Conflict(code="file_not_ready", params={"state": stored.state})


async def issue_link(
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    file_id: uuid.UUID,
    disposition: tokens.Disposition,
) -> tuple[str, datetime]:
    """A short-lived link for one file (preview falls back to download for unsafe types)."""
    _, keyring = services.require_storage()
    found = await authorize(session, actor, file_id, Action.VIEW)
    _require_openable(services, found.file)
    if disposition == tokens.Disposition.INLINE and not inline_allowed(_sniffed(found.file)):
        disposition = tokens.Disposition.ATTACHMENT
    expires_at = now() + services.link_ttl
    grant = tokens.LinkGrant(found.file.id, actor.user_id, actor.tenant_id, disposition, expires_at)
    return tokens.sign(grant, keyring.link_key()), expires_at


@dataclass(frozen=True)
class Content:
    """What the content route streams, and how."""

    name: str
    content_type: str
    size: int
    start: int
    end: int
    disposition: tokens.Disposition
    body: AsyncIterator[bytes]
    partial: bool
    file_id: uuid.UUID | None = None
    private: bool = False


def parse_range(header: str | None, size: int) -> tuple[int, int, bool]:
    """(start, end, partial) for a `Range: bytes=a-b` header (one range; others: whole file)."""
    whole = (0, max(size - 1, 0), False)
    if not header or not header.startswith("bytes=") or "," in header or size == 0:
        return whole
    first, _, last = header[6:].partition("-")
    try:
        if first == "":
            length = int(last)
            start, end = max(size - length, 0), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
    except ValueError:
        return whole
    if start > end or start >= size:
        raise ValidationFailed(code="range_not_satisfiable", params={"size": size})
    return start, end, True


async def open_by_link(  # noqa: PLR0913 - the link, the reader and the request's range
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    token: str,
    *,
    range_header: str | None,
    when: datetime | None = None,
) -> Content:
    """Check a link and the user's access, then stream the file (or the requested range)."""
    storage, keyring = services.require_storage()
    try:
        grant = tokens.verify(token, keyring.link_key(), when or now())
    except tokens.TokenError as error:
        if error.expired:
            raise LinkExpiredError from None
        raise _not_found() from None
    if grant.user_id != actor.user_id or grant.tenant_id != actor.tenant_id:
        raise _not_found()
    found = await authorize(session, actor, grant.file_id, Action.VIEW)
    _require_openable(services, found.file)
    stored = found.file
    start, end, partial = parse_range(range_header, stored.size)
    key = await data_key(session, keyring, stored.data_key_id)
    body = blobs.read(
        storage,
        stored.object_key,
        data_key=key,
        file_id=stored.id,
        size=stored.size,
        start=start,
        end=end,
    )
    content_type = (
        stored.content_type
        if grant.disposition == tokens.Disposition.INLINE
        else "application/octet-stream"
    )
    return Content(
        stored.name,
        content_type,
        stored.size,
        start,
        end,
        grant.disposition,
        body,
        partial=partial,
        file_id=stored.id,
        private=found.private,
    )


async def open_image(
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    file_id: uuid.UUID,
    *,
    thumbnail: bool,
) -> Content:
    """An image (inline in the editor) or its thumbnail, for a signed-in user who may see it."""
    storage, keyring = services.require_storage()
    found = await authorize(session, actor, file_id, Action.VIEW)
    stored = found.file
    _require_openable(services, stored)
    if stored.kind != Kind.IMAGE.value or stored.active_markup:
        raise _not_found()
    key_name, size = stored.object_key, stored.size
    content_type = stored.content_type
    if thumbnail:
        if stored.thumb_key is None or stored.thumb_size is None:
            raise NotFound(code="file_thumbnail_not_found")
        key_name, size, content_type = stored.thumb_key, stored.thumb_size, "image/webp"
    key = await data_key(session, keyring, stored.data_key_id)
    body = blobs.read(storage, key_name, data_key=key, file_id=stored.id, size=size)
    return Content(
        stored.name,
        content_type,
        size,
        0,
        size - 1,
        tokens.Disposition.INLINE,
        body,
        partial=False,
    )


DELETE_GRACE = timedelta(hours=24)


async def remove(session: AsyncSession, actor: Actor, file_id: uuid.UUID) -> Attachment:
    """Delete an attachment (soft; its object goes after the grace period)."""
    found = await authorize(session, actor, file_id, Action.REMOVE)
    stored = found.file
    stored.state = FileState.DELETED.value
    stored.deleted_at = now()
    stored.purge_after = now() + DELETE_GRACE
    stored.version += 1
    await record_event(
        session,
        FileChanged(
            file_id=stored.id,
            state=stored.state,
            owner_type=found.link.owner_type,
            owner_id=found.link.owner_id,
            record_type=found.link.record_type,
            record_id=found.link.record_id,
        ),
        aggregate_id=stored.id,
    )
    return found
