"""Copying an owner's files into the actor's drafts (D-121; lane B's conditions on WP-033 s4).

An article's images go into a reply: a file has exactly one link and its bytes are encrypted
with the file's ID in the associated data, so each image becomes a new file, decrypted and
encrypted again under its new ID, linked as the actor's draft. When the reply is saved,
`attach_drafts` moves the copies to it, and from then on they follow the reply's own rule.

Rules (lane B):
1. Only files linked to that exact source owner, and only when the actor may view it; anything
   else is 404, so nobody can copy a file by naming its ID.
2. Only sources that may be opened now. The others are named in `not_copied`, never dropped.
   Clean stays clean (the bytes are checked against the source's sha256 while streaming);
   not-scanned copies start as a new upload would (`initial_state`).
3. The thumbnail is copied too; `metadata_stripped` and `copied_from` are kept.
4. The tenant's limits (batch, file size, blocked extensions), 25 MB per insert, one quota lock.
5. Streamed under the uploads gate; all or nothing: objects already written are removed on any
   failure.
6. Each copy emits `system.file.uploaded`; its stored source is `knowledge`.
7. Drafts never saved are purged after DRAFT_LIFETIME, readable only by their author meanwhile.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.logging import get_logger
from app.shared.events import record_event
from app.shared.files.domain.states import FileState, openable
from app.shared.files.domain.types import extension
from app.shared.files.events import FileUploaded
from app.shared.files.infra import blobs
from app.shared.files.infra.models import FileLink, StoredFile
from app.shared.files.keyring import KeyRing
from app.shared.files.ports import Action, Actor, OwnerType, owner_access
from app.shared.files.service.core import (
    MB,
    FileServices,
    current_data_key,
    data_key,
    lock_usage,
    object_key,
    rules,
    tenant_of,
)
from app.shared.files.service.uploads import _check_quota, _forget, _gate, initial_state
from app.shared.ids import new_id
from app.shared.storage import ObjectStorage

log = get_logger(__name__)

MAX_INSERT_BYTES = 25 * MB  # per insert, whatever the tenant's own limits (lane B)
SOURCE = "knowledge"


class CopyIntegrityError(RuntimeError):
    """The decrypted bytes did not match the source's sha256 (nothing is kept)."""


@dataclass(frozen=True)
class NotCopied:
    """A file that stayed behind, and why: its state, `too_large` or `blocked`."""

    file_id: uuid.UUID
    reason: str


@dataclass(frozen=True)
class Copies:
    """{source file id: copy id}, and the files not copied."""

    copied: dict[uuid.UUID, uuid.UUID]
    not_copied: list[NotCopied]


async def copy_to_drafts(  # noqa: C901, PLR0912, PLR0913, PLR0915 - the rules above, in order
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    *,
    owner_type: OwnerType,
    owner_id: uuid.UUID,
    file_ids: Iterable[uuid.UUID],
) -> Copies:
    """Copy these files of one owner into `actor`'s drafts (see the module docstring)."""
    storage, keyring = services.require_storage()
    wanted = list(dict.fromkeys(file_ids))
    if not wanted:
        return Copies({}, [])
    # 1. The source: viewable by the actor, and each file linked to exactly it.
    await owner_access(owner_type).check(session, actor, owner_type, owner_id, Action.VIEW)
    tenant_rules = await rules(session)
    if len(wanted) > tenant_rules.max_batch:
        raise ValidationFailed(code="too_many_files", params={"max": tenant_rules.max_batch})
    linked = set(
        await session.scalars(
            select(FileLink.file_id).where(
                FileLink.file_id.in_(wanted),
                FileLink.owner_type == owner_type.value,
                FileLink.owner_id == owner_id,
            )
        )
    )
    if linked != set(wanted):
        raise NotFound(code="file_not_found")
    sources = {
        s.id: s for s in await session.scalars(select(StoredFile).where(StoredFile.id.in_(wanted)))
    }
    # 2-4. What may be copied now.
    not_copied: list[NotCopied] = []
    eligible: list[StoredFile] = []
    for file_id in wanted:
        stored = sources.get(file_id)
        state = FileState(stored.state) if stored is not None else FileState.DELETED
        if stored is None or not openable(state, scan_required=services.scan_required):
            not_copied.append(NotCopied(file_id, state.value))
        elif stored.size > tenant_rules.max_file_bytes:
            not_copied.append(NotCopied(file_id, "too_large"))
        elif extension(stored.name) in tenant_rules.blocked:
            not_copied.append(NotCopied(file_id, "blocked"))
        else:
            eligible.append(stored)
    total = sum(s.size + (s.thumb_size or 0) for s in eligible)
    if total > MAX_INSERT_BYTES:
        raise ValidationFailed(code="insert_too_large", params={"limit_mb": MAX_INSERT_BYTES // MB})
    if not eligible:
        return Copies({}, not_copied)
    added = sum(s.size for s in eligible)
    await _check_quota(session, added, lock=True)  # one lock for the whole batch
    tenant = tenant_of(session)
    key_id, key = await current_data_key(session, keyring)
    written: list[str] = []
    copied: dict[uuid.UUID, uuid.UUID] = {}
    made: list[StoredFile] = []
    try:
        async with _gate(services.upload_concurrency):
            for source in eligible:
                stored, keys = await _copy_one(
                    session, services, storage, keyring, source, key_id=key_id, key=key
                )
                written.extend(keys)
                made.append(stored)
                copy_id = stored.id
                copied[source.id] = copy_id
        for stored in made:
            session.add(stored)
        await session.flush()  # the files first: no ORM relationship orders the inserts
        for stored in made:
            session.add(
                FileLink(
                    tenant_id=tenant,
                    file_id=stored.id,
                    owner_type=OwnerType.DRAFT.value,
                    owner_id=actor.user_id,
                    inline=True,
                )
            )
        counter = await lock_usage(session)
        counter.bytes_used += added
        counter.files_count += len(made)
        await session.flush()
        for stored in made:
            await record_event(
                session,
                FileUploaded(
                    file_id=stored.id, owner_type=OwnerType.DRAFT.value, owner_id=actor.user_id
                ),
                aggregate_id=stored.id,
            )
    except BaseException:
        for key_written in written:
            await _forget(services, key_written)
        raise
    log.info("files_copied", count=len(made), not_copied=len(not_copied))
    return Copies(copied, not_copied)


# --- copies onto other records (WP-046a S5c; REQ-INC-033; lane B's conditions) -----------------

RECORD_COPY_SOURCE = "copy"
MAX_COPY_PAIRS = 200  # source files x target records per call (lane B)
MAX_COPY_BYTES = 4 * MAX_INSERT_BYTES  # 100 MB per call (lane B: drop to 50 MB if it is slow)


@dataclass(frozen=True)
class RecordCopies:
    """{target record: {source file id: copy id}}, and the source files not copied."""

    copied: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]]
    not_copied: list[NotCopied]


async def copy_to_records(  # noqa: C901, PLR0912, PLR0913, PLR0915 - lane B's rules, in order
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    *,
    owner_type: OwnerType,
    source_id: uuid.UUID,
    target_ids: Iterable[uuid.UUID],
) -> RecordCopies:
    """Copy one record's own files onto each of `target_ids` (records of the same owner type).

    Lane B's rules:
    1. The actor may view the source and attach to every target, checked before anything is
       read; one target they may not use refuses the whole call (404, nothing copied).
    2. Only files linked to exactly that record: never a reply's or note's (they link to their
       entry), never drafts.
    3. Each copy is a new file under its own ID (`_copy_one`); files that cannot be opened now,
       are too large or blocked are named in `not_copied`.
    4. Limits before any write: the tenant's batch size, at most MAX_COPY_PAIRS files x records
       and MAX_COPY_BYTES per call, and one quota lock for all of it.
    5. Under the uploads gate, all or nothing: every object written is removed on any failure.
    6. Each copy emits `system.file.uploaded`; its stored source is `copy`.
    """
    storage, keyring = services.require_storage()
    targets = list(dict.fromkeys(target_ids))
    if not targets:
        return RecordCopies({}, [])
    access = owner_access(owner_type)
    try:
        await access.check(session, actor, owner_type, source_id, Action.VIEW)
        # Each target's record, for its links (a link to a record names it, as an upload's).
        owners = {
            target: await access.check(session, actor, owner_type, target, Action.ATTACH)
            for target in targets
        }
    except PermissionDenied as error:
        # One record they may not use refuses the whole call, as not found (lane B).
        raise NotFound(code="work_item_not_found") from error
    links = list(
        await session.execute(
            select(FileLink.file_id, FileLink.inline).where(
                FileLink.owner_type == owner_type.value, FileLink.owner_id == source_id
            )
        )
    )
    if not links:
        return RecordCopies({t: {} for t in targets}, [])
    inline = {row.file_id: row.inline for row in links}
    tenant_rules = await rules(session)
    if len(inline) > tenant_rules.max_batch:
        raise ValidationFailed(code="too_many_files", params={"max": tenant_rules.max_batch})
    if len(inline) * len(targets) > MAX_COPY_PAIRS:
        raise ValidationFailed(code="too_many_files", params={"max": MAX_COPY_PAIRS})
    sources = {
        s.id: s
        for s in await session.scalars(select(StoredFile).where(StoredFile.id.in_(list(inline))))
    }
    not_copied: list[NotCopied] = []
    eligible: list[StoredFile] = []
    for file_id in inline:
        stored = sources.get(file_id)
        state = FileState(stored.state) if stored is not None else FileState.DELETED
        if stored is None or not openable(state, scan_required=services.scan_required):
            not_copied.append(NotCopied(file_id, state.value))
        elif stored.size > tenant_rules.max_file_bytes:
            not_copied.append(NotCopied(file_id, "too_large"))
        elif extension(stored.name) in tenant_rules.blocked:
            not_copied.append(NotCopied(file_id, "blocked"))
        else:
            eligible.append(stored)
    total = sum(s.size + (s.thumb_size or 0) for s in eligible) * len(targets)
    if total > MAX_COPY_BYTES:
        raise ValidationFailed(code="insert_too_large", params={"limit_mb": MAX_COPY_BYTES // MB})
    if not eligible:
        return RecordCopies({t: {} for t in targets}, not_copied)
    added = sum(s.size for s in eligible) * len(targets)
    await _check_quota(session, added, lock=True)  # one lock for the whole batch
    tenant = tenant_of(session)
    key_id, key = await current_data_key(session, keyring)
    written: list[str] = []
    copied: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {t: {} for t in targets}
    made: list[tuple[uuid.UUID, StoredFile, bool]] = []
    try:
        async with _gate(services.upload_concurrency):
            for target in targets:
                for source in eligible:
                    stored, keys = await _copy_one(
                        session,
                        services,
                        storage,
                        keyring,
                        source,
                        key_id=key_id,
                        key=key,
                        origin=RECORD_COPY_SOURCE,
                    )
                    written.extend(keys)
                    made.append((target, stored, inline[source.id]))
                    copied[target][source.id] = stored.id
        for _target, stored, _inline in made:
            session.add(stored)
        await session.flush()  # the files first: no ORM relationship orders the inserts
        for target, stored, is_inline in made:
            session.add(
                FileLink(
                    tenant_id=tenant,
                    file_id=stored.id,
                    owner_type=owner_type.value,
                    owner_id=target,
                    record_type=owners[target].record_type,
                    record_id=owners[target].record_id,
                    inline=is_inline,
                )
            )
        counter = await lock_usage(session)
        counter.bytes_used += added
        counter.files_count += len(made)
        await session.flush()
        for target, stored, _inline in made:
            await record_event(
                session,
                FileUploaded(file_id=stored.id, owner_type=owner_type.value, owner_id=target),
                aggregate_id=stored.id,
            )
    except BaseException:
        for key_written in written:
            await _forget(services, key_written)
        raise
    log.info("files_copied_to_records", count=len(made), not_copied=len(not_copied))
    return RecordCopies(copied, not_copied)


async def _copy_one(  # noqa: PLR0913 - the source and where its copy goes, explicit
    session: AsyncSession,
    services: FileServices,
    storage: ObjectStorage,
    keyring: KeyRing,
    source: StoredFile,
    *,
    key_id: uuid.UUID,
    key: bytes,
    origin: str = SOURCE,
) -> tuple[StoredFile, list[str]]:
    """One file copied: decrypted, encrypted again under its new ID, checked, not yet added.

    The bytes are checked against the source's sha256 and size while streaming
    (CopyIntegrityError); the thumbnail comes too; clean stays clean, anything else starts as a
    new upload would. Returns the new row (unsaved) and every object key written, so the caller
    removes them on any failure (lane B's rules, D-121 and REQ-INC-033).
    """
    tenant = tenant_of(session)
    written: list[str] = []
    try:
        source_key = await data_key(session, keyring, source.data_key_id)
        copy_id = new_id()
        target = object_key(tenant, copy_id)
        result = await blobs.write(
            storage,
            target,
            data_key=key,
            data_key_id=key_id,
            file_id=copy_id,
            source=blobs.read(
                storage,
                source.object_key,
                data_key=source_key,
                file_id=source.id,
                size=source.size,
            ),
            limit=source.size,
        )
        written.append(target)
        if result.sha256 != source.sha256 or result.size != source.size:
            raise CopyIntegrityError(str(source.id))  # noqa: TRY301 - cleaned up below
        thumb_key: str | None = None
        thumb_size: int | None = None
        if source.thumb_key is not None and source.thumb_size is not None:
            thumb_key = object_key(tenant, copy_id, thumbnail=True)
            thumb = await blobs.write(
                storage,
                thumb_key,
                data_key=key,
                data_key_id=key_id,
                file_id=copy_id,
                source=blobs.read(
                    storage,
                    source.thumb_key,
                    data_key=source_key,
                    file_id=source.id,
                    size=source.thumb_size,
                ),
                limit=source.thumb_size,
            )
            written.append(thumb_key)
            thumb_size = thumb.size
    except BaseException:
        # Nothing of a failed copy stays: the caller only knows the keys of finished ones.
        for key_written in written:
            await _forget(services, key_written)
        raise
    clean = FileState(source.state) == FileState.CLEAN
    stored = StoredFile(
        id=copy_id,
        tenant_id=tenant,
        name=source.name,
        size=result.size,
        sha256=result.sha256,
        content_type=source.content_type,
        kind=source.kind,
        active_markup=source.active_markup,
        state=(FileState.CLEAN if clean else initial_state(services)).value,
        scan_signature=source.scan_signature if clean else None,
        scanned_at=source.scanned_at if clean else None,
        metadata_stripped=source.metadata_stripped,
        data_key_id=key_id,
        object_key=target,
        stored_size=result.stored_size,
        thumb_key=thumb_key,
        thumb_size=thumb_size,
        source=origin,
        copied_from=source.id,
    )
    return stored, written
