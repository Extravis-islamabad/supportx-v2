"""Change-set fingerprints of lifecycle entries: salts, building at save time, verifying (ADR-046).

* `for_saves`: at save time, the fingerprint of one record's saves in a request, from the values
  exactly as `field_changes` stores them (JSON), with the data subjects' salts for personal
  fields (domain/lifecycle.py names them per record type).
* `statuses`: the verifier. For each fingerprinted entry it reads the saves back from
  `field_changes` and recomputes both halves: `verified`, `mismatch` (always when the ordinary
  half differs), or `erased_on_request` (the ordinary half matches, and a subject's salt is
  gone with their erasure logged after the entry).

Salts never leave the database except into this process's memory for hashing: the app role
cannot read `audit_subject_salts`; the migrator-owned definer functions get or create them
(`audit_subject_salts_ensure`) and read them (`audit_subject_salts_of`). No API, viewer or
export returns one.
"""

import json
import os
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Uuid

from app.modules.audit.domain.fingerprint import (
    FieldValues,
    FingerprintStatus,
    SaveValues,
    fingerprint,
    has_personal,
    personal_fingerprint,
    status_of,
)
from app.modules.audit.domain.integrity import SALT_SIZE
from app.modules.audit.domain.lifecycle import RECORD_TYPES, RecordAudit
from app.modules.audit.infra.models import AuditEntry
from app.shared.history import Change, FieldChange, SavedRecord, record_subjects

ERASED_ACTION = "audit.subject_erased"
CHUNK = 500  # entries per verification query

_ENSURE = text(
    "SELECT subject_ref, salt_bytes FROM audit_subject_salts_ensure(:subjects, :salts)"
).bindparams(bindparam("subjects", type_=ARRAY(Uuid())), bindparam("salts", type_=ARRAY(BYTEA())))
_SALTS_OF = text(
    "SELECT subject_ref, salt_bytes FROM audit_subject_salts_of(:subjects)"
).bindparams(bindparam("subjects", type_=ARRAY(Uuid())))


@dataclass(frozen=True)
class EntryFingerprint:
    """What a lifecycle entry stores of its change set (inside the entry hash).

    `value` commits to the ordinary fields (no salt: it always recomputes, even after an
    erasure); `personal` to the personal fields, salted, and is None without any.
    """

    value: str
    personal: str | None
    saves: tuple[uuid.UUID, ...]
    subjects: tuple[uuid.UUID, ...]


# --- salts --------------------------------------------------------------------------------------


async def ensure_salts(
    session: AsyncSession, subjects: Iterable[uuid.UUID]
) -> dict[uuid.UUID, bytes]:
    """Each subject's salt, created when missing; erased subjects are left out (no new salt)."""
    wanted = sorted(set(subjects), key=str)
    if not wanted:
        return {}
    fresh = [os.urandom(SALT_SIZE) for _ in wanted]
    rows = await session.execute(_ENSURE, {"subjects": wanted, "salts": fresh})
    return {row.subject_ref: bytes(row.salt_bytes) for row in rows}


async def salts_of(session: AsyncSession, subjects: Iterable[uuid.UUID]) -> dict[uuid.UUID, bytes]:
    """The salts that still exist for these subjects (never creates one)."""
    wanted = sorted(set(subjects), key=str)
    if not wanted:
        return {}
    rows = await session.execute(_SALTS_OF, {"subjects": wanted})
    return {row.subject_ref: bytes(row.salt_bytes) for row in rows}


# --- at save time -------------------------------------------------------------------------------


def as_stored(value: object) -> Any:  # noqa: ANN401 - a JSON value
    """The value as it reads back from JSONB (field_changes is written with json.dumps)."""
    return json.loads(json.dumps(value))


def _save_values(spec: RecordAudit, saved: SavedRecord) -> SaveValues:
    rows: Sequence[Change] = saved.recorded or (Change("", None, None),)
    return SaveValues(
        saved.change_id,
        saved.version,
        saved.kind,
        tuple(
            FieldValues(
                c.field,
                as_stored(c.old),
                as_stored(c.new),
                spec.is_personal(c.field),
                saved.reason,  # record_changes writes the save's reason on every row
            )
            for c in rows
        ),
    )


def _previous_people(spec: RecordAudit, saves: Sequence[SavedRecord]) -> set[uuid.UUID]:
    """The people a save moved the record away from (an old requester, lane A's review).

    The save's old free text may be theirs, so they are its data subjects too.
    """
    found: set[uuid.UUID] = set()
    for saved in saves:
        for change in saved.recorded:
            if change.field in spec.data_subjects and change.old is not None:
                person = _uuid(change.old)
                if person is not None:
                    found.add(person)
    return found


async def for_saves(
    session: AsyncSession, spec: RecordAudit, saves: Sequence[SavedRecord]
) -> EntryFingerprint:
    """The fingerprint of one record's saves (in order) for its entry."""
    last = saves[-1]
    values = [_save_values(spec, s) for s in saves]
    salts: dict[uuid.UUID, bytes] = {}
    reasons = spec.reasons_personal
    if has_personal(values, reasons_personal=reasons) and spec.data_subjects:
        people = await record_subjects(session, spec.history_record_type, last.record_id)
        found = {p for name in spec.data_subjects if (p := people.get(name)) is not None}
        salts = await ensure_salts(session, found | _previous_people(spec, saves))
    subjects = tuple(sorted(salts, key=str))
    record_type, record_id = spec.history_record_type, last.record_id
    return EntryFingerprint(
        fingerprint(record_type, record_id, values, reasons_personal=reasons),
        personal_fingerprint(
            record_type, record_id, values, subjects, salts, reasons_personal=reasons
        ),
        tuple(s.change_id for s in saves),
        subjects,
    )


# --- verification -------------------------------------------------------------------------------


@dataclass
class FingerprintTally:
    """Verdicts of a verification run (first mismatch by chain position)."""

    verified: int = 0
    erased: int = 0
    mismatches: int = 0
    first_mismatch: tuple[int, uuid.UUID] | None = None

    def add(self, seq: int, entry_id: uuid.UUID, status: FingerprintStatus) -> None:
        """Count one entry's verdict."""
        if status is FingerprintStatus.VERIFIED:
            self.verified += 1
        elif status is FingerprintStatus.ERASED_ON_REQUEST:
            self.erased += 1
        else:
            self.mismatches += 1
            if self.first_mismatch is None or seq < self.first_mismatch[0]:
                self.first_mismatch = (seq, entry_id)


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def _history(
    session: AsyncSession, entries: Sequence[Mapping[str, Any]]
) -> dict[uuid.UUID, list[FieldChange]]:
    """The field_changes rows of the entries' saves, by change ID (read by record, then save)."""
    by_type: dict[str, set[uuid.UUID]] = {}
    changes: set[uuid.UUID] = set()
    for entry in entries:
        spec = RECORD_TYPES.get(entry["object_type"] or "")
        record_id = _uuid(entry["object_id"])
        if spec is None or record_id is None:
            continue
        by_type.setdefault(spec.history_record_type, set()).add(record_id)
        changes.update(entry["fingerprint_saves"] or ())
    found: dict[uuid.UUID, list[FieldChange]] = {}
    for record_type, ids in by_type.items():
        rows = await session.scalars(
            select(FieldChange).where(
                FieldChange.record_type == record_type,
                FieldChange.record_id.in_(sorted(ids, key=str)),
                FieldChange.change_id.in_(sorted(changes, key=str)),
            )
        )
        for row in rows:
            found.setdefault(row.change_id, []).append(row)
    return found


async def _erasures(session: AsyncSession, subjects: Iterable[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """The newest logged erasure of each subject (an `audit.subject_erased` entry)."""
    ids = sorted({str(s) for s in subjects})
    if not ids:
        return {}
    rows = await session.execute(
        select(AuditEntry.object_id, func.max(AuditEntry.occurred_at))
        .where(
            AuditEntry.action == ERASED_ACTION,
            AuditEntry.object_type == "user",
            AuditEntry.object_id.in_(ids),
        )
        .group_by(AuditEntry.object_id)
    )
    return {uuid.UUID(object_id): at for object_id, at in rows}


def _saves_of(
    entry: Mapping[str, Any], history: Mapping[uuid.UUID, list[FieldChange]]
) -> tuple[RecordAudit, uuid.UUID, list[SaveValues]] | None:
    """The entry's saves read back from history, or None when they cannot belong to it."""
    spec = RECORD_TYPES.get(entry["object_type"] or "")
    record_id = _uuid(entry["object_id"])
    if spec is None or record_id is None:
        return None
    saves = []
    for change_id in entry["fingerprint_saves"] or ():
        rows = history.get(change_id, [])
        if any(r.record_id != record_id or r.record_type != spec.history_record_type for r in rows):
            return None
        first = rows[0] if rows else None
        saves.append(
            SaveValues(
                change_id,
                first.record_version if first else -1,
                first.kind if first else "",
                tuple(
                    FieldValues(
                        r.field, r.old_value, r.new_value, spec.is_personal(r.field), r.reason
                    )
                    for r in rows
                ),
            )
        )
    return spec, record_id, saves


def _verdict(
    entry: Mapping[str, Any],
    history: Mapping[uuid.UUID, list[FieldChange]],
    salts: Mapping[uuid.UUID, bytes],
    erased: Mapping[uuid.UUID, datetime],
) -> FingerprintStatus:
    found = _saves_of(entry, history)
    if found is None:
        return FingerprintStatus.MISMATCH
    spec, record_id, saves = found
    record_type = spec.history_record_type
    needed: list[uuid.UUID] = list(entry["personal_subjects"] or ())
    have = [s for s in needed if s in salts]
    # The ordinary half has no salt: it is checked whatever happened to the subjects, so an
    # erasure can never hide a change to an ordinary value (ADR-046).
    reasons = spec.reasons_personal
    ordinary = (
        fingerprint(record_type, record_id, saves, reasons_personal=reasons) == entry["fingerprint"]
    )
    personal = (
        personal_fingerprint(record_type, record_id, saves, needed, salts, reasons_personal=reasons)
        if len(have) == len(needed)
        else None
    )
    return status_of(
        ordinary_matches=ordinary,
        personal_stored=entry.get("personal_fingerprint"),
        personal_recomputed=personal,
        subjects=needed,
        salted=have,
        erased_after=erased,
        occurred_at=entry["occurred_at"],
    )


async def statuses(
    session: AsyncSession, entries: Sequence[Mapping[str, Any]]
) -> dict[uuid.UUID, FingerprintStatus]:
    """The verdict on each fingerprinted entry (entry rows as mappings; others are skipped)."""
    out: dict[uuid.UUID, FingerprintStatus] = {}
    marked = [e for e in entries if e.get("fingerprint") is not None]
    for start in range(0, len(marked), CHUNK):
        chunk = marked[start : start + CHUNK]
        history = await _history(session, chunk)
        subjects = {s for e in chunk for s in e["personal_subjects"] or ()}
        salts = await salts_of(session, subjects)
        erased = await _erasures(session, subjects - salts.keys())
        for entry in chunk:
            out[entry["id"]] = _verdict(entry, history, salts, erased)
    return out


async def status_of_entry(session: AsyncSession, entry: AuditEntry) -> FingerprintStatus | None:
    """One entry's verdict for the entry view; None when it has no fingerprint."""
    if entry.fingerprint is None:
        return None
    row = {column.name: getattr(entry, column.name) for column in AuditEntry.__table__.columns}
    return (await statuses(session, [row]))[entry.id]
