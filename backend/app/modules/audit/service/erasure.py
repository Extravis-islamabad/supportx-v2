"""Erasure of a person's personal data in the audit log (REQ-AUD-013; ADR-027).

Deletes the person's personal rows (IP addresses, user agents, free-text reasons) through the
migrator-owned `audit_erase_subject()`; the app itself has no DELETE right on the table. Entries
keep the person's ID, which no longer resolves to a name once the people module has anonymised
the user (REQ-ADM-101), so their entries still group together and the chain still verifies:
only salted commitments of the personal data are inside the hashes.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.domain.catalogue import AuditActorType
from app.modules.audit.service.recording import WORKER, record


async def erase_subject(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Remove `user_id`'s personal values from every entry; records the erasure. Returns rows."""
    removed = int(await session.scalar(text("SELECT audit_erase_subject(:s)"), {"s": user_id}) or 0)
    await record(
        session,
        action_code="audit.subject_erased",
        facts=WORKER,
        object_type="user",
        object_id=user_id,
        details={"personal_rows_removed": removed},
        actor=(AuditActorType.SYSTEM, None),
    )
    return removed
