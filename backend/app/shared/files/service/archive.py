"""Several files of one record as one zip (WP-046a S2; REQ-INC-080 AC2; lane B's rules).

Two steps, so a long download never holds a database connection:
1. `plan_archive`, in the request's session. The record must be visible to the reader first
   (else 404, as a missing record). Each picked file is checked again here: the reader may view
   it, it belongs to this record, and it may be downloaded now (clean). The caps hold before any
   byte. Each file's data key is unwrapped here. Files left out are named by ID and a reason only.
2. `stream_archive`, with the plan alone (no session): each file is read through the decrypting
   reader chunk by chunk, with no temp files. If a read or decrypt fails mid-stream, it raises,
   and the response aborts rather than finishing an archive that looks complete. The log names
   the file ID only.
"""

import uuid
import zipfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.core.logging import get_logger
from app.shared.files.domain.archive import MANIFEST, manifest_text, safe_entry_name
from app.shared.files.domain.states import FileState, openable
from app.shared.files.infra import blobs
from app.shared.files.infra.models import FileLink, StoredFile
from app.shared.files.ports import Action, Actor, UnknownOwnerError, record_access
from app.shared.files.service.access import authorize
from app.shared.files.service.core import FileServices, data_key
from app.shared.storage import ObjectStorage

log = get_logger(__name__)

MAX_FILES = 200
MAX_BYTES = 500 * 1024 * 1024
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class ArchiveEntry:
    """One file to put in the zip: its safe name and what the reader needs to stream it."""

    file_id: uuid.UUID
    name: str
    object_key: str
    size: int
    key: bytes  # its data key, unwrapped while the session was open


@dataclass(frozen=True)
class ArchivePlan:
    """What goes in and what was left out (ID and reason only)."""

    entries: list[ArchiveEntry]
    left_out: list[tuple[str, str]]


def _too_many() -> ValidationFailed:
    return ValidationFailed(code="archive_too_many_files", params={"max": MAX_FILES})


async def plan_archive(  # noqa: PLR0913, PLR0917 - the reader, the record, the picked files
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    record_type: str,
    record_id: uuid.UUID,
    file_ids: Sequence[uuid.UUID],
) -> ArchivePlan:
    """Check everything, unwrap the keys, and say what goes in (all DB work happens here)."""
    try:
        source = record_access(record_type)
    except UnknownOwnerError:
        raise NotFound(code="file_owner_not_found") from None
    # The record first (lane B): a hidden record answers as a missing one, with no zip at all.
    await source.visible_owners(session, actor, record_type, record_id)
    wanted = list(dict.fromkeys(file_ids))
    if len(wanted) > MAX_FILES:
        raise _too_many()
    _storage, keyring = services.require_storage()
    links = {
        link.file_id: (stored, link)
        for stored, link in (
            await session.execute(
                select(StoredFile, FileLink)
                .join(FileLink, FileLink.file_id == StoredFile.id)
                .where(
                    StoredFile.id.in_(wanted),
                    FileLink.record_type == record_type,
                    FileLink.record_id == record_id,
                    StoredFile.deleted_at.is_(None),
                )
            )
        ).all()
    }
    included: list[StoredFile] = []
    left_out: list[tuple[str, str]] = []
    for file_id in wanted:
        if file_id not in links:
            left_out.append((str(file_id), "not_found"))  # not this record's, or gone
            continue
        try:
            found = await authorize(session, actor, file_id, Action.VIEW)
        except NotFound:
            left_out.append((str(file_id), "not_found"))
            continue
        stored = found.file
        if not openable(FileState(stored.state), scan_required=services.scan_required):
            left_out.append((str(file_id), f"file_state.{stored.state}"))
            continue
        included.append(stored)
    if sum(s.size for s in included) > MAX_BYTES:
        raise ValidationFailed(code="archive_too_large", params={"max_mb": MAX_BYTES // 2**20})
    taken: set[str] = set()
    entries = [
        ArchiveEntry(
            file_id=s.id,
            name=safe_entry_name(s.name, taken=taken),
            object_key=s.object_key,
            size=s.size,
            key=await data_key(session, keyring, s.data_key_id),
        )
        for s in included
    ]
    return ArchivePlan(entries, left_out)


class _Drain:
    """A write-only buffer zipfile writes into; its bytes are taken as they come."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []
        self._written = 0

    def write(self, data: bytes) -> int:
        self._parts.append(bytes(data))
        self._written += len(data)
        return len(data)

    def tell(self) -> int:
        return self._written

    def flush(self) -> None:
        return None

    def take(self) -> bytes:
        out = b"".join(self._parts)
        self._parts.clear()
        return out


async def stream_archive(
    storage: ObjectStorage, plan: ArchivePlan, manifest_heading: str
) -> AsyncIterator[bytes]:
    """The zip's bytes, file by file; raises if any file fails (never a silent cut)."""
    drain = _Drain()
    with zipfile.ZipFile(drain, mode="w", compression=zipfile.ZIP_STORED) as archive:  # type: ignore[call-overload]  # a write-only stream is all zipfile's writing needs
        stamp = datetime.now(UTC).timetuple()[:6]
        for entry in plan.entries:
            info = zipfile.ZipInfo(entry.name, date_time=stamp)
            info.compress_type = zipfile.ZIP_STORED
            try:
                with archive.open(info, mode="w", force_zip64=entry.size > 2**31) as target:
                    async for piece in blobs.read(
                        storage,
                        entry.object_key,
                        data_key=entry.key,
                        file_id=entry.file_id,
                        size=entry.size,
                    ):
                        target.write(piece)
                        if drain.tell():
                            yield drain.take()
            except Exception:
                # Fail closed (lane B): abort the response, never finish a cut archive.
                log.warning("archive_file_failed", file_id=str(entry.file_id))
                raise
            yield drain.take()
        if plan.left_out:
            archive.writestr(MANIFEST, manifest_text(plan.left_out, manifest_heading))
    yield drain.take()


__all__ = [
    "MAX_BYTES",
    "MAX_FILES",
    "ArchiveEntry",
    "ArchivePlan",
    "plan_archive",
    "stream_archive",
]
