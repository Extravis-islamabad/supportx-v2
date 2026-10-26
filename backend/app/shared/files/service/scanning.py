"""The scan worker's job for one file (D-081 D3, D4; ADR-028 items 3 and 4).

1. Decrypt the file and stream it to the scanner.
2. Infected: block it for good, delete its object at once, keep the row (name, hash, signature)
   for the audit trail.
3. Clean image: strip its metadata losslessly (re-encrypting the cleaned bytes), then make a
   thumbnail under strict limits.
4. Scanner down: the attempt is counted and the file keeps waiting; the scan sweep tries again
   later. After the last attempt the file shows "could not be checked" and stays closed while
   scanning is required.
5. No scanner installed: the file waits (scanning required) or shows "not scanned".

Returns what happened, so the caller can write the audit entry (shared code cannot reach the
audit module).
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.shared.events import record_event
from app.shared.files.domain import metadata
from app.shared.files.domain.states import SCAN_ATTEMPTS_MAX, FileState, may_become
from app.shared.files.events import FileChanged
from app.shared.files.infra import blobs, thumbnails
from app.shared.files.infra.models import FileLink, StoredFile
from app.shared.files.infra.scanner import ScannerUnavailableError
from app.shared.files.service.core import (
    FileServices,
    current_data_key,
    data_key,
    lock_usage,
    now,
    object_key,
    tenant_of,
)
from app.shared.storage import StorageUnavailable

log = get_logger(__name__)


@dataclass(frozen=True)
class ScanOutcome:
    """The file's state after the scan, and the signature when it was blocked."""

    file_id: uuid.UUID
    state: FileState
    signature: str | None = None


async def _single(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def _announce(session: AsyncSession, stored: StoredFile) -> None:
    link = await session.scalar(select(FileLink).where(FileLink.file_id == stored.id))
    if link is None:
        return
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


async def _set(session: AsyncSession, stored: StoredFile, state: FileState) -> None:
    if not may_become(FileState(stored.state), state):
        return
    stored.state = state.value
    stored.scanned_at = now()
    stored.version += 1
    await _announce(session, stored)


async def _unavailable(
    session: AsyncSession, services: FileServices, stored: StoredFile
) -> ScanOutcome:
    """No scanner installed, or it did not answer: wait, retry later, or give up visibly."""
    if not services.scanner.available:
        if services.scan_required:
            return ScanOutcome(stored.id, FileState.SCANNING)  # waits; admins are told why
        await _set(session, stored, FileState.NOT_SCANNED)
        return ScanOutcome(stored.id, FileState.NOT_SCANNED)
    stored.scan_attempts += 1
    if stored.scan_attempts < SCAN_ATTEMPTS_MAX:
        log.warning("file_scan_retry", file_id=str(stored.id), attempt=stored.scan_attempts)
        return ScanOutcome(stored.id, FileState.SCANNING)  # the sweep tries again
    log.error("file_scan_failed", file_id=str(stored.id))
    await _set(session, stored, FileState.SCAN_FAILED)
    return ScanOutcome(stored.id, FileState.SCAN_FAILED)


async def scan(session: AsyncSession, services: FileServices, file_id: uuid.UUID) -> ScanOutcome:
    """Scan one file (idempotent: a file no longer waiting is left alone)."""
    stored = await session.get(StoredFile, file_id, with_for_update=True)
    if stored is None or stored.state != FileState.SCANNING.value:
        state = FileState(stored.state) if stored is not None else FileState.DELETED
        return ScanOutcome(file_id, state)
    if not services.scanner.available:
        return await _unavailable(session, services, stored)
    storage, keyring = services.require_storage()
    key = await data_key(session, keyring, stored.data_key_id)
    data = await blobs.read_all(
        storage, stored.object_key, data_key=key, file_id=stored.id, size=stored.size
    )
    try:
        verdict = await services.scanner.scan(data)
    except ScannerUnavailableError:
        return await _unavailable(session, services, stored)
    if verdict.infected:
        stored.scan_signature = verdict.signature
        await _set(session, stored, FileState.INFECTED)
        await _drop_objects(session, services, stored)
        log.warning("file_blocked", file_id=str(file_id), signature=verdict.signature)
        return ScanOutcome(file_id, FileState.INFECTED, verdict.signature)
    if stored.kind == "image":
        await _clean_image(session, services, stored, data)
    await _set(session, stored, FileState.CLEAN)
    return ScanOutcome(file_id, FileState.CLEAN)


async def _clean_image(
    session: AsyncSession, services: FileServices, stored: StoredFile, data: bytes
) -> None:
    """Strip metadata (re-encrypting the result) and store a thumbnail."""
    storage, keyring = services.require_storage()
    tenant = tenant_of(session)
    cleaned = metadata.strip(stored.content_type, data)
    if cleaned.stripped:
        key_id, key = await current_data_key(session, keyring)
        written = await blobs.write(
            storage,
            stored.object_key,
            data_key=key,
            data_key_id=key_id,
            file_id=stored.id,
            source=_single(cleaned.data),
            limit=len(cleaned.data),
        )
        counter = await lock_usage(session)
        counter.bytes_used += written.size - stored.size
        stored.size, stored.stored_size = written.size, written.stored_size
        stored.sha256 = hashlib.sha256(cleaned.data).digest()
        stored.data_key_id = key_id
        stored.metadata_stripped = True
        data = cleaned.data
    thumb = await thumbnails.thumbnail(data)
    if thumb is None:
        return
    key_id, key = await current_data_key(session, keyring)
    if key_id != stored.data_key_id:  # thumbnails use the file's own key
        key = await data_key(session, keyring, stored.data_key_id)
    thumb_key = object_key(tenant, stored.id, thumbnail=True)
    written = await blobs.write(
        storage,
        thumb_key,
        data_key=key,
        data_key_id=stored.data_key_id,
        file_id=stored.id,
        source=_single(thumb),
        limit=len(thumb),
    )
    stored.thumb_key, stored.thumb_size = thumb_key, written.size


async def _drop_objects(session: AsyncSession, services: FileServices, stored: StoredFile) -> None:
    """Delete a file's objects now and stop counting them (the row stays)."""
    if services.storage is None:
        return
    for key in (stored.object_key, stored.thumb_key):
        if key is None:
            continue
        try:
            await services.storage.delete(key)
        except StorageUnavailable:
            log.warning("file_object_left", file_id=str(stored.id))
            stored.purge_after = now()  # the cleanup job tries again
    counter = await lock_usage(session)
    counter.bytes_used = max(0, counter.bytes_used - stored.size)
    counter.files_count = max(0, counter.files_count - 1)
    stored.thumb_key = None


async def rescan(session: AsyncSession, file_id: uuid.UUID) -> bool:
    """Admin action: try again a file that could not be checked (or was not scanned)."""
    stored = await session.get(StoredFile, file_id, with_for_update=True)
    if stored is None or not may_become(FileState(stored.state), FileState.SCANNING):
        return False
    stored.state = FileState.SCANNING.value
    stored.scan_attempts = 0
    stored.version += 1
    await _announce(session, stored)
    return True


async def waiting(session: AsyncSession) -> list[uuid.UUID]:
    """Files of the tenant still waiting for a scan (the sweep re-queues them)."""
    return list(
        await session.scalars(
            select(StoredFile.id).where(StoredFile.state == FileState.SCANNING.value).limit(500)
        )
    )
