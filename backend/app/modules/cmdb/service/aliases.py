"""A merged CI's ID finds its survivor, for a reader who may see it (WP-053 S4b; REQ-CMDB-017 AC2).

Never through a reader's blind spot (the coordinator's (3), lane C (8)): a merged CI whose
survivor the reader may not see answers exactly as a CI that exists nowhere (404
`cmdb_ci_not_found`, a "gone" ref, a missing impact input), so an alias never confirms that an
unseen CI exists. The same rule for the record, the picker, the impact inputs and `ci_refs`.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.infra.models import Ci, CiAlias
from app.modules.cmdb.service.cis import visible_rows
from app.modules.identity_access import Subject

CHAIN_MAX = 20  # a chain of merges (A into B, B into C) is followed this far at most


def _live() -> Any:  # noqa: ANN401 - a SQLAlchemy condition
    return (CiAlias.restored_at.is_(None)) & (CiAlias.deleted_at.is_(None))


async def survivor_of(session: AsyncSession, merged_id: uuid.UUID) -> uuid.UUID | None:
    """The live CI a merged CI went into (following a chain of merges), or None. Unscoped."""
    current: uuid.UUID | None = None
    wanted = merged_id
    seen: set[uuid.UUID] = set()
    while wanted not in seen and len(seen) < CHAIN_MAX:
        seen.add(wanted)
        found = await session.scalar(
            select(CiAlias.ci_id).where(CiAlias.alias_id == wanted, _live())
        )
        if found is None:
            break
        current = wanted = found
    return current


async def visible_survivor(
    session: AsyncSession, subject: Subject, merged_id: uuid.UUID
) -> Ci | None:
    """The survivor of a merged CI when the reader may see it; None otherwise (never a hint)."""
    survivor = await survivor_of(session, merged_id)
    if survivor is None:
        return None
    found: Ci | None = await session.scalar(visible_rows(subject).where(Ci.id == survivor))
    return found


async def resolve_visible(
    session: AsyncSession, subject: Subject, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """For each asked ID that is a merged CI with a survivor the reader sees: that survivor."""
    if not ids:
        return {}
    merged = set(
        await session.scalars(
            select(CiAlias.alias_id).where(CiAlias.alias_id.in_(list(ids)), _live())
        )
    )
    found: dict[uuid.UUID, uuid.UUID] = {}
    for ci_id in ids:
        if ci_id in merged and (row := await visible_survivor(session, subject, ci_id)):
            found[ci_id] = row.id
    return found


def alias_survivors(text: str) -> Select[Any]:
    """The survivors whose merged CI's display ID is `text` (any case): for search and pickers.

    The caller adds the reader's scope (`visible_rows`), so an unseen survivor is never found.
    """
    return select(CiAlias.ci_id).where(
        _live(), func.lower(CiAlias.alias_display_id) == text.strip().lower()
    )
