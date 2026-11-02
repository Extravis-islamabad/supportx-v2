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

from app.core.errors import NotFound, ValidationFailed
from app.core.logging import get_logger
from app.shared.events import record_event
from app.shared.files.domain.states import FileState, openable
from app.shared.files.domain.types import extension
from app.shared.files.events import FileUploaded
from app.shared.files.infra import blobs
from app.shared.files.infra.models import FileLink, StoredFile
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
                clean = FileState(source.state) == FileState.CLEAN
                made.append(
                    StoredFile(
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
                        source=SOURCE,
                        copied_from=source.id,
                    )
                )
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
