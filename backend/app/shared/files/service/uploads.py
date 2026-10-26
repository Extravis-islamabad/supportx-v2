"""Uploading a file (REQ-INC-079; ADR-028 item 1).

Order matters, so nothing is stored that should have been refused:

1. the owner: may this person attach here (or is it their own editor draft)?
2. the size the client declared, against the tenant's limit (refused before any byte is read);
3. the storage quota, against the declared size;
4. the first bytes: the real type, against the tenant's blocked list;
5. the stream, encrypted into object storage, cut off at the size limit;
6. one transaction: the quota again with the real size (row-locked), the file, its link, the
   usage and the `system.file.uploaded` event. If that fails, the stored object is removed.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import LimitReached, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.shared.events import record_event
from app.shared.files.domain.states import FileState
from app.shared.files.domain.types import (
    Sniffed,
    blocked_reason,
    extension,
    normalise_name,
    sniff,
)
from app.shared.files.events import FileChanged, FileUploaded
from app.shared.files.infra import blobs
from app.shared.files.infra.models import FileLink, StoredFile
from app.shared.files.ports import Action, Actor, Owner, OwnerType, owner_access, storage_limit
from app.shared.files.service.core import (
    GB,
    MB,
    FileServices,
    Rules,
    current_data_key,
    lock_usage,
    object_key,
    rules,
    tenant_of,
    usage,
)
from app.shared.ids import new_id
from app.shared.storage import StorageUnavailable

log = get_logger(__name__)
# One gate per event loop: how many uploads write to storage at once (upload_concurrency).
_GATES: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def _gate(size: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _GATES.get(loop)
    if gate is None:
        gate = _GATES[loop] = asyncio.Semaphore(size)
    return gate


@dataclass(frozen=True)
class Target:
    """Where the upload goes."""

    owner_type: OwnerType
    owner_id: uuid.UUID
    inline: bool = False


async def resolve_owner(
    session: AsyncSession, actor: Actor, target: Target, action: Action
) -> Owner | None:
    """The owner after the access check; None for the actor's own draft."""
    if target.owner_type == OwnerType.DRAFT:
        if target.owner_id != actor.user_id:
            raise NotFound(code="file_owner_not_found")
        return None
    return await owner_access(target.owner_type).check(
        session, actor, target.owner_type, target.owner_id, action
    )


def _too_large(limit_mb: int, size: int | None) -> ValidationFailed:
    params: dict[str, str | int] = {"limit_mb": limit_mb}
    if size is not None:
        params["size_mb"] = max(1, -(-size // MB))
    return ValidationFailed(code="file_too_large", params=params)


async def _check_quota(session: AsyncSession, adding: int, *, lock: bool) -> None:
    limit = await storage_limit(session)
    if limit is None:
        return
    used = (await lock_usage(session)).bytes_used if lock else (await usage(session))[0]
    if used + adding > limit:
        raise LimitReached(
            code="storage_quota_exceeded",
            params={"used_gb": round(used / GB, 2), "limit_gb": round(limit / GB, 2)},
        )


def initial_state(services: FileServices) -> FileState:
    """Scanning when a scanner exists or scanning is required (files wait); else not scanned."""
    if services.scanner.available or services.scan_required:
        return FileState.SCANNING
    return FileState.NOT_SCANNED


@dataclass(frozen=True)
class Prepared:
    """What the checks decided before any byte is read (no database needed afterwards)."""

    target: Target
    owner: Owner | None
    rules: Rules
    tenant_id: uuid.UUID
    file_id: uuid.UUID
    data_key_id: uuid.UUID
    data_key: bytes = field(repr=False)

    @property
    def object_key(self) -> str:
        """Where the encrypted bytes go."""
        return object_key(self.tenant_id, self.file_id)


@dataclass(frozen=True)
class Staged:
    """The encrypted object written, and what the first bytes said the file is."""

    name: str
    sniffed: Sniffed
    written: blobs.Written


async def prepare(
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    target: Target,
    declared_size: int | None,
) -> Prepared:
    """Owner, size and quota checks, and the data key (steps 1-3; a short transaction)."""
    _, keyring = services.require_storage()
    owner = await resolve_owner(session, actor, target, Action.ATTACH)
    tenant_rules = await rules(session)
    if declared_size is not None and declared_size > tenant_rules.max_file_bytes:
        raise _too_large(tenant_rules.max_file_mb, declared_size)
    await _check_quota(session, declared_size or 0, lock=False)
    key_id, key = await current_data_key(session, keyring)
    return Prepared(target, owner, tenant_rules, tenant_of(session), new_id(), key_id, key)


async def stage(
    services: FileServices, prepared: Prepared, *, name: str, body: AsyncIterator[bytes]
) -> Staged:
    """Real type against the blocked list, then the encrypted stream (steps 4-5; no database).

    Memory stays bounded however many people upload at once: past `upload_concurrency`, uploads
    wait here with their bodies still in the network.
    """
    storage, _ = services.require_storage()
    clean_name = normalise_name(name)
    head, stream = await blobs.read_head(body)
    sniffed = sniff(head)
    reason = blocked_reason(clean_name, sniffed, prepared.rules.blocked)
    if reason is not None:
        raise ValidationFailed(
            code="file_type_blocked",
            params={"reason": reason, "extension": extension(clean_name) or "-"},
        )
    try:
        async with _gate(services.upload_concurrency):
            written = await blobs.write(
                storage,
                prepared.object_key,
                data_key=prepared.data_key,
                data_key_id=prepared.data_key_id,
                file_id=prepared.file_id,
                source=stream,
                limit=prepared.rules.max_file_bytes,
            )
    except blobs.TooLargeError:
        raise _too_large(prepared.rules.max_file_mb, None) from None
    return Staged(clean_name, sniffed, written)


async def finish(
    session: AsyncSession,
    services: FileServices,
    prepared: Prepared,
    staged: Staged,
    source: str = "ui",
) -> tuple[StoredFile, FileLink]:
    """Quota with the real size (row lock), the rows, usage and the event (step 6).

    The caller removes the staged object (`discard`) if this fails or never runs.
    """
    written = staged.written
    await _check_quota(session, written.size, lock=True)
    state = initial_state(services)
    target, owner = prepared.target, prepared.owner
    stored = StoredFile(
        id=prepared.file_id,
        tenant_id=prepared.tenant_id,
        name=staged.name,
        size=written.size,
        sha256=written.sha256,
        content_type=staged.sniffed.content_type,
        kind=staged.sniffed.kind.value,
        active_markup=staged.sniffed.active_markup,
        state=state.value,
        data_key_id=prepared.data_key_id,
        object_key=prepared.object_key,
        stored_size=written.stored_size,
        source=source,
    )
    link = FileLink(
        tenant_id=prepared.tenant_id,
        file_id=prepared.file_id,
        owner_type=target.owner_type.value,
        owner_id=target.owner_id,
        record_type=owner.record_type if owner else None,
        record_id=owner.record_id if owner else None,
        inline=target.inline,
    )
    session.add(stored)
    await session.flush()  # no ORM relationship orders the inserts: the file goes first
    session.add(link)
    counter = await lock_usage(session)
    counter.bytes_used += written.size
    counter.files_count += 1
    await session.flush()
    await record_event(
        session,
        FileUploaded(
            file_id=prepared.file_id,
            owner_type=link.owner_type,
            owner_id=link.owner_id,
            record_type=link.record_type,
            record_id=link.record_id,
        ),
        aggregate_id=prepared.file_id,
    )
    log.info("file_uploaded", file_id=str(prepared.file_id), size=written.size, state=state.value)
    return stored, link


async def discard(services: FileServices, prepared: Prepared) -> None:
    """Remove a staged object whose rows were never written (refused, failed, or a replay)."""
    await _forget(services, prepared.object_key)


async def upload(  # noqa: PLR0913 - the upload's facts, explicit
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    target: Target,
    *,
    name: str,
    declared_size: int | None,
    body: AsyncIterator[bytes],
    source: str = "ui",
) -> tuple[StoredFile, FileLink]:
    """All steps in one session (callers without a long-running client, e.g. email intake).

    The API route instead prepares in a short transaction and streams with no connection held
    (system/api/files.py), so slow uploads never hold database connections.
    """
    prepared = await prepare(session, services, actor, target, declared_size)
    staged = await stage(services, prepared, name=name, body=body)
    try:
        return await finish(session, services, prepared, staged, source)
    except BaseException:
        await discard(services, prepared)
        raise


async def _forget(services: FileServices, key: str) -> None:
    """Remove an object whose row was never committed (best effort, logged)."""
    if services.storage is None:
        return
    try:
        await services.storage.delete(key)
    except StorageUnavailable:
        log.warning("file_orphan_left", object_key=key)


async def attach_drafts(
    session: AsyncSession, actor: Actor, file_ids: list[uuid.UUID], target: Target
) -> list[FileLink]:
    """Move the actor's draft files (pasted into an editor) to the entry or record just saved."""
    owner = await resolve_owner(session, actor, target, Action.ATTACH)
    if owner is None or not file_ids:
        return []
    links = list(
        await session.scalars(
            select(FileLink).where(
                FileLink.file_id.in_(file_ids),
                FileLink.owner_type == OwnerType.DRAFT.value,
                FileLink.owner_id == actor.user_id,
            )
        )
    )
    for link in links:
        link.owner_type, link.owner_id = target.owner_type.value, target.owner_id
        link.record_type, link.record_id = owner.record_type, owner.record_id
        stored = await session.get(StoredFile, link.file_id)
        state = stored.state if stored is not None else FileState.DELETED.value
        await record_event(
            session,
            FileChanged(
                file_id=link.file_id,
                state=state,
                owner_type=link.owner_type,
                owner_id=link.owner_id,
                record_type=link.record_type,
                record_id=link.record_id,
            ),
            aggregate_id=link.file_id,
        )
    return links
