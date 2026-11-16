"""What other modules may know of CIs (WP-053 S1; the CMDB's public interface).

- `can_see(session, subject, ci_id)`: before a person links a CI to a record;
- `ci_refs(session, subject, ids)`: names for a record's linked CIs in one call. A removed CI, or
  one the person may not see, comes back marked (`gone` / `hidden`), never silently missing and
  never named;
- the picker (`GET /cmdb/cis/picker`, `cis.picker`) to choose one.
`cmdb.ci.updated` (with `changed_fields`) is the hint that a name or state changed.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.infra.models import Ci
from app.modules.cmdb.service.cis import visible_rows
from app.modules.identity_access import Subject

REFS_MAX = 500


@dataclass(frozen=True, slots=True)
class CiRef:
    """A CI as another module shows it: never more than this."""

    id: uuid.UUID
    display_id: str | None
    name: str | None  # None when gone or hidden
    type_id: uuid.UUID | None
    state_id: uuid.UUID | None
    gone: bool = False
    hidden: bool = False


async def can_see(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> bool:
    """Whether the person may see (and so link) this CI."""
    return await session.scalar(visible_rows(subject).where(Ci.id == ci_id)) is not None


async def ci_refs(session: AsyncSession, subject: Subject, ids: Sequence[uuid.UUID]) -> list[CiRef]:
    """One ref per ID, in the order asked (at most REFS_MAX)."""
    unique = list(dict.fromkeys(ids))[:REFS_MAX]
    if not unique:
        return []
    rows = await session.scalars(visible_rows(subject).where(Ci.id.in_(unique)))
    visible = {r.id: r for r in rows}
    live = set(
        await session.scalars(select(Ci.id).where(Ci.id.in_(unique), Ci.deleted_at.is_(None)))
    )
    out: list[CiRef] = []
    for ci_id in unique:
        row = visible.get(ci_id)
        if row is not None:
            out.append(CiRef(row.id, row.display_id, row.name, row.type_id, row.state_id))
        elif ci_id in live:
            out.append(CiRef(ci_id, None, None, None, None, hidden=True))
        else:
            out.append(CiRef(ci_id, None, None, None, None, gone=True))
    return out
