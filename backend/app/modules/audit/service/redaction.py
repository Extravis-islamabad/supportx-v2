"""Signed history redaction (ADR-046 addendum; D-171, ADR-052 S1b; migration 0167).

A redacted passage must not survive in record history. Rows a fingerprinted audit entry commits
to cannot simply be blanked: the verifier would read that as tampering. So before blanking, the
field's digests are kept, exactly as the save's fingerprint commits to them (ADR-046's
`[field, digest(old), digest(new)]`; salted with the entry's data subjects' salts for a personal
field). The verifier then recomputes the fingerprint through them and reports the save as
`redacted_on_request`, never `verified`, and only when the redaction is logged in the chain.

The digests are computed here, in the app, as fingerprints are at save time; salts are read only
through `audit_subject_salts_of`. The migrator-owned `history_redact_signed()` stores them and
blanks the values: the app role cannot write `field_change_redactions` or update record history.
It accepts only the history rows of the redacted mention's own record and field that a
fingerprinted entry commits to (the same binding as `history_redact_field`).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Boolean, Text, Uuid

from app.modules.audit.domain.fingerprint import value_digest
from app.modules.audit.domain.lifecycle import RECORD_TYPES
from app.modules.audit.infra.models import AuditEntry
from app.modules.audit.service.fingerprints import salts_of
from app.shared.history import FieldChange

_REDACT = text(
    "SELECT history_redact_signed(:mention, :rows, :old, :new, :salted) AS result"
).bindparams(
    bindparam("rows", type_=ARRAY(Uuid())),
    bindparam("old", type_=ARRAY(Text())),
    bindparam("new", type_=ARRAY(Text())),
    bindparam("salted", type_=ARRAY(Boolean())),
)


async def _signers(
    session: AsyncSession, record_id: uuid.UUID
) -> dict[uuid.UUID, tuple[str, tuple[uuid.UUID, ...]]]:
    """For each save a fingerprinted entry of the record commits to: (object type, subjects)."""
    rows = await session.execute(
        select(
            AuditEntry.object_type, AuditEntry.fingerprint_saves, AuditEntry.personal_subjects
        ).where(AuditEntry.object_id == str(record_id), AuditEntry.fingerprint_saves.is_not(None))
    )
    found: dict[uuid.UUID, tuple[str, tuple[uuid.UUID, ...]]] = {}
    for object_type, saves, subjects in rows:
        for change_id in saves or ():
            found[change_id] = (str(object_type or ""), tuple(subjects or ()))
    return found


async def _salts(
    session: AsyncSession,
    subjects: Sequence[uuid.UUID],
    cache: dict[tuple[uuid.UUID, ...], list[bytes]],
) -> list[bytes]:
    """The subjects' salts in subject-ID order, as the fingerprint takes them (ADR-046)."""
    ordered = tuple(sorted(set(subjects), key=str))
    if ordered not in cache:
        have = await salts_of(session, ordered)
        # A subject already erased has no salt: their personal half no longer verifies anyway
        # (erased_on_request), so what is kept for it is never compared.
        cache[ordered] = [have[s] for s in ordered if s in have]
    return cache[ordered]


async def redact_signed_history(
    session: AsyncSession,
    mention_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    field: str,
) -> int:
    """Blank the signed history rows of one redacted mention's field, keeping their digests.

    Returns how many rows were blanked. Rows already blank, or not signed, are left (the
    unsigned ones are `history_redact_field`'s). Idempotent: a second call blanks nothing.
    """
    rows = list(
        await session.scalars(
            select(FieldChange).where(
                FieldChange.record_type == record_type,
                FieldChange.record_id == record_id,
                FieldChange.field == field,
            )
        )
    )
    signers = await _signers(session, record_id)
    cache: dict[tuple[uuid.UUID, ...], list[bytes]] = {}
    ids: list[uuid.UUID] = []
    old: list[str] = []
    new: list[str] = []
    salted: list[bool] = []
    for row in rows:
        signer = signers.get(row.change_id)
        if signer is None or (row.old_value is None and row.new_value is None):
            continue
        object_type, subjects = signer
        spec = RECORD_TYPES.get(object_type)
        personal = spec is not None and spec.is_personal(field)
        salts = await _salts(session, subjects, cache) if personal else []
        ids.append(row.id)
        old.append(value_digest(row.old_value, salts))
        new.append(value_digest(row.new_value, salts))
        salted.append(personal)
    if not ids:
        return 0
    result = await session.scalar(
        _REDACT, {"mention": mention_id, "rows": ids, "old": old, "new": new, "salted": salted}
    )
    return int((result or {}).get("blanked", 0))
