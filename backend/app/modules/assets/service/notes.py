"""Notes on an asset (WP-049b s2; REQ-AST-050, following REQ-INC-062 and 063).

- **Who:** whoever may see the asset reads its notes and adds one (a repair note is not a
  change to the asset). Authors edit and delete their own; others' only with `assets.manage` on
  the asset (403 otherwise, REQ-INC-062 AC2). Notes are staff only: assets have no portal side.
- **Text:** rich text, sanitised on the server (app/shared/richtext.py). Inline images are left
  out: an asset keeps its files as attachments (REQ-INC-079 rules through the files service).
- **History:** each edit keeps the earlier text in the note's own history (record type
  `asset_note`), shown behind its "edited" marker (REQ-INC-062 AC1). A deleted note stays as a
  "note deleted" line with who and when; its text stays in history only. The asset's history
  lists the note as a part added, changed or removed (its ID only).
- **Mentions (REQ-INC-063):** a mentioned person who may see the asset is told (the
  `asset.mentioned` notification); one who may not is not told, and the author hears who (AC2).
  A mention gives no access. Mentions of people who are not users here become plain words.
- Every change writes its event to the outbox in the same transaction; the asset's page shows
  it live (`assets.note.changed` on the asset's channel).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound, PermissionDenied
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.events import AssetNoteChanged, PartAction
from app.modules.assets.infra.models import Asset, AssetNote
from app.modules.assets.service.assets import MANAGE, RECORD_TYPE, VIEW, _refuse, _visible
from app.modules.assets.service.financials import OWN_KIND, PART_KIND
from app.modules.identity_access import Subject, subject_for, user_names
from app.shared.events import record_event
from app.shared.history import Change, HistoryEntry, Source, history_page, record_changes
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id
from app.shared.richtext import (
    is_blank,
    mentioned_user_ids,
    sanitize_html,
    without_images,
    without_mentions,
)

NOTE_RECORD_TYPE = "asset_note"
BODY_MAX = 100_000  # as the migration's check
NOTES_MAX = 500  # per page: the newest; an asset with more shows the newest 500


def _require(subject: Subject, permission: str) -> None:
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission})


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


@dataclass(frozen=True, slots=True)
class SavedNote:
    """A saved note, and the people mentioned who were not told (they cannot see the asset)."""

    note: AssetNote
    not_notified: list[uuid.UUID]


async def _clean_body(session: AsyncSession, raw: str) -> tuple[str, list[uuid.UUID]]:
    """The sanitised text (no images, no mentions of strangers) and the people it mentions."""
    clean = without_images(sanitize_html(raw))
    if is_blank(clean) or not clean.strip():
        _refuse([Problem("body", "required")])
    if len(clean) > BODY_MAX:
        _refuse([Problem("body", "value_too_long", (("max", BODY_MAX),))])
    claimed = mentioned_user_ids(clean)
    known = await user_names(session, claimed)
    clean = without_mentions(clean, [u for u in claimed if u not in known])
    return clean, [uuid.UUID(u) for u in claimed if u in known]


async def _may_see(session: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID) -> bool:
    other = await subject_for(session, _tenant(session), user_id)
    if not other.holds(VIEW):
        return False
    try:
        await _visible(session, other, asset_id)
    except (NotFound, PermissionDenied):
        return False
    return True


async def _split(
    session: AsyncSession, asset_id: uuid.UUID, people: list[uuid.UUID], author: uuid.UUID
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """(told, not told): those who may see the asset, and those who may not (the author: none)."""
    told: list[uuid.UUID] = []
    not_told: list[uuid.UUID] = []
    for person in people:
        if person == author:
            continue
        (told if await _may_see(session, person, asset_id) else not_told).append(person)
    return told, not_told


async def _saved(  # noqa: PLR0913 - one save of a note: who, what, how, whom it tells
    session: AsyncSession,
    asset: Asset,
    note: AssetNote,
    changes: list[Change],
    *,
    action: PartAction,
    source: Source,
    told: list[uuid.UUID],
    reason: str | None = None,
) -> None:
    await session.flush()
    await session.refresh(note)
    await record_changes(
        session,
        record_type=NOTE_RECORD_TYPE,
        record_id=note.id,
        version=note.version,
        kind=OWN_KIND[action],
        changes=changes,
        source=source,
        reason=reason,
    )
    part = str(note.id)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=asset.id,
        version=asset.version,
        kind=PART_KIND[action],
        changes=[Change("note", None if action == "created" else part, part)],
        source=source,
        reason=reason,
    )
    await record_event(
        session,
        AssetNoteChanged(asset_id=asset.id, note_id=note.id, action=action, mentioned=told),
        aggregate_id=note.id,
        aggregate_version=note.version,
    )


async def list_notes(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID
) -> list[AssetNote]:
    """The asset's notes, newest first, deleted ones included (as "note deleted" lines)."""
    _require(subject, VIEW)
    await _visible(session, subject, asset_id)
    return list(
        await session.scalars(
            select(AssetNote)
            .where(AssetNote.asset_id == asset_id)
            .order_by(AssetNote.created_at.desc(), AssetNote.id.desc())
            .limit(NOTES_MAX)
        )
    )


async def add_note(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID, body: str, *, source: Source
) -> SavedNote:
    """A new note on an asset the subject may see; the mentioned people are told."""
    _require(subject, VIEW)
    asset = await _visible(session, subject, asset_id)
    clean, mentioned = await _clean_body(session, body)
    told, not_told = await _split(session, asset.id, mentioned, subject.user_id)
    note = AssetNote(
        id=new_id(),
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        body=clean,
        mentioned_ids=mentioned,
        created_by=subject.user_id,
        updated_by=subject.user_id,
    )
    session.add(note)
    await session.flush()
    await _saved(
        session,
        asset,
        note,
        [Change("body", None, clean)],
        action="created",
        source=source,
        told=told,
    )
    return SavedNote(note, not_told)


def may_change(subject: Subject, note: AssetNote) -> bool:
    """Its author, or a person who may manage assets (checked on the asset as well)."""
    return note.created_by == subject.user_id or subject.holds(MANAGE)


async def _note_to_change(
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    note_id: uuid.UUID,
    expected_version: int,
) -> tuple[Asset, AssetNote]:
    _require(subject, VIEW)
    asset = await _visible(session, subject, asset_id)
    note = await session.scalar(
        select(AssetNote)
        .where(
            AssetNote.id == note_id,
            AssetNote.asset_id == asset.id,
            AssetNote.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if note is None:
        raise NotFound(code="asset_note_not_found")
    if note.created_by != subject.user_id:
        # Someone else's note: only with assets.manage on this asset (REQ-INC-062 AC2).
        _require(subject, MANAGE)
        await _visible(session, subject, asset.id, permission=MANAGE)
    if note.version != expected_version:
        raise await stale_version(
            session, note, expected_version=expected_version, record_type=NOTE_RECORD_TYPE,
            record_id=note.id,
        )  # fmt: skip
    return asset, note


async def edit_note(  # noqa: PLR0913 - the note, its version, the text and the source
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    note_id: uuid.UUID,
    body: str,
    *,
    expected_version: int,
    source: Source,
) -> SavedNote:
    """New text (If-Match); the earlier text stays in the note's history. New mentions told."""
    asset, note = await _note_to_change(session, subject, asset_id, note_id, expected_version)
    clean, mentioned = await _clean_body(session, body)
    if clean == note.body:
        return SavedNote(note, [])
    before = set(note.mentioned_ids)
    told, not_told = await _split(
        session, asset.id, [p for p in mentioned if p not in before], subject.user_id
    )
    changes = [Change("body", note.body, clean)]
    note.body = clean
    note.mentioned_ids = mentioned
    note.edited_at = datetime.now(UTC)
    note.updated_by = subject.user_id
    note.version += 1
    await _saved(session, asset, note, changes, action="updated", source=source, told=told)
    return SavedNote(note, not_told)


async def delete_note(  # noqa: PLR0913 - the note, its version and the source
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    note_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> AssetNote:
    """A "note deleted" line stays with who and when; the text stays in history only."""
    asset, note = await _note_to_change(session, subject, asset_id, note_id, expected_version)
    note.deleted_at = datetime.now(UTC)
    note.deleted_by = subject.user_id
    note.updated_by = subject.user_id
    note.version += 1
    await _saved(
        session,
        asset,
        note,
        [Change("deleted", old=False, new=True)],
        action="deleted",
        source=source,
        told=[],
    )
    return note


async def note_history(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID, note_id: uuid.UUID
) -> list[HistoryEntry]:
    """The note's saves, newest first: each text it had, who wrote it and when."""
    _require(subject, VIEW)
    await _visible(session, subject, asset_id)
    found = await session.scalar(
        select(AssetNote.id).where(AssetNote.id == note_id, AssetNote.asset_id == asset_id)
    )
    if found is None:
        raise NotFound(code="asset_note_not_found")
    entries, _ = await history_page(session, NOTE_RECORD_TYPE, note_id, limit=100)
    return entries


# --- GDPR mentions (ADR-052 S1b) -----------------------------------------------------------------


async def redact_note(
    session: AsyncSession, note_id: uuid.UUID, rewrite: Callable[[str], str], reason: str
) -> bool:
    """A note's text as `rewrite` makes it (a person's erasure redaction; no rights checked here).

    The caller (the erasure's mentions port) is reached only through `people.erase`. The note's
    history names the field only (old and new None: the old text is what is being removed),
    the asset's history lists the note as changed, and the page refreshes live. False when the
    text stays the same or the note is gone.
    """
    note = await session.scalar(select(AssetNote).where(AssetNote.id == note_id).with_for_update())
    if note is None:
        return False
    new_body = rewrite(note.body)
    if new_body == note.body:
        return False
    asset = await session.scalar(select(Asset).where(Asset.id == note.asset_id))
    if asset is None:  # a foreign key keeps the asset; unreachable
        return False
    note.body = new_body[:BODY_MAX]
    note.version += 1
    await _saved(
        session,
        asset,
        note,
        [Change("body", None, None)],
        action="updated",
        source="system",
        told=[],
        reason=reason,
    )
    return True


async def readable_note_body(
    session: AsyncSession, subject: Subject, note_id: uuid.UUID
) -> str | None:
    """A live note's text, when the subject may see its asset (as the notes list)."""
    note = await session.scalar(
        select(AssetNote).where(AssetNote.id == note_id, AssetNote.deleted_at.is_(None))
    )
    if note is None or not subject.holds(VIEW):
        return None
    try:
        await _visible(session, subject, note.asset_id)
    except (NotFound, PermissionDenied):
        return None
    return note.body
