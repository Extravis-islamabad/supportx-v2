"""Erasure of a person's personal data in the audit log and record history (REQ-AUD-013).

ADR-027 and ADR-046.

Through the migrator-owned `audit_erase_subject()` (the app itself has no DELETE right on
`audit_personal`, no UPDATE on `field_changes` and no right at all on `audit_subject_salts`):

1. the person's personal rows (IP addresses, user agents, free-text reasons) are deleted;
2. the personal values in record history of the saves whose fingerprints use the person's salt
   are blanked (the free text of tickets they raised or that were raised for them), and so is
   every free-text reason of those saves (the function does that itself). They are
   found through the entries' subject lists, and the function blanks only rows of those saves;
   which fields are personal comes from the lifecycle table (domain/lifecycle.py);
3. the person's salt is destroyed (crypto-shredding), so the salted digests in the chain can
   never be matched to a guess again.

Entries keep the person's ID, which no longer resolves to a name once the people module has
anonymised the user (REQ-ADM-101), so their entries still group together. The chain still
verifies: personal data is inside the hashes only as salted commitments and digests. The
verifier then reports the person's saves as "erased on request", accepted only because this
erasure is itself logged (`audit.subject_erased`); everyone else's saves still verify.
"""

import uuid
from typing import Any

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Uuid

from app.modules.audit.domain.catalogue import AuditActorType
from app.modules.audit.domain.lifecycle import RECORD_TYPES
from app.modules.audit.infra.models import AuditEntry
from app.modules.audit.service.recording import WORKER, record
from app.shared.history import FieldChange

_ERASE = (
    text("SELECT audit_erase_subject(:subject, :rows) AS result")
    .bindparams(bindparam("subject", type_=Uuid()), bindparam("rows", type_=ARRAY(Uuid())))
    .columns(result=JSONB)
)


async def personal_history(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """The field_changes rows holding `user_id`'s personal values, found through the entries."""
    entries = await session.execute(
        select(AuditEntry.object_type, AuditEntry.object_id, AuditEntry.fingerprint_saves).where(
            AuditEntry.personal_subjects.contains([user_id])
        )
    )
    rows: set[uuid.UUID] = set()
    for object_type, object_id, saves in entries:
        spec = RECORD_TYPES.get(object_type or "")
        if spec is None or not saves or object_id is None:
            continue
        found = await session.execute(
            select(FieldChange.id, FieldChange.field).where(
                FieldChange.record_type == spec.history_record_type,
                FieldChange.record_id == uuid.UUID(object_id),
                FieldChange.change_id.in_(saves),
            )
        )
        rows.update(row_id for row_id, name in found if spec.is_personal(name))
    return sorted(rows, key=str)


async def erase_subject(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Remove `user_id`'s personal values; records the erasure. Returns personal rows removed."""
    rows = await personal_history(session, user_id)
    result: dict[str, Any] = await session.scalar(_ERASE, {"subject": user_id, "rows": rows}) or {}
    removed = int(result.get("personal_rows", 0))
    await record(
        session,
        action_code="audit.subject_erased",
        facts=WORKER,
        object_type="user",
        object_id=user_id,
        details={
            "personal_rows_removed": removed,
            "history_values_erased": int(result.get("history_values", 0)),
            "history_reasons_erased": int(result.get("history_reasons", 0)),
            "salt_erased": int(result.get("salts", 0)),
        },
        actor=(AuditActorType.SYSTEM, None),
    )
    return removed
