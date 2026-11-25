"""The CMDB's side of a monitoring topology import (WP-053 S6; REQ-CMDB-031, REQ-INT-041).

`monitoring_integrations` maps MonetX devices and links into CIs and relationships only through
these functions (rule e: it never reads the CMDB's tables). Every write is the **sync identity**'s
(no person's scope; ADR-047 §8), with the ordinary checks, history, version and event, and its
attributes stamped `monetx` so the tenant's precedence applies (S4): a value a stronger source set
(a person's edit, by default) is kept, never overwritten.

- A device's CI is made by `monitored_ci_create` and kept current by `monitored_ci_update`.
- `monitored_link` / `monitored_unlink` make and remove relationships the import owns. The caller
  keeps which ones it made, so a hand-made relationship is never removed.
- `monitored_retire` moves a CI that monitoring no longer reports to an end-of-life state. Nothing
  is ever hard-deleted.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.domain import field_access as field_rules
from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain import sources as source_rules
from app.modules.cmdb.domain import sync as sync_rules
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.domain.sources import AttributeSource
from app.modules.cmdb.events import RelationshipsChanged
from app.modules.cmdb.infra.models import Ci, CiState, CiType, Relationship, RelationshipType
from app.modules.cmdb.service import cis, relationships
from app.modules.cmdb.service.catalogue import ensure_defaults, get_settings
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.history import Source

STAMP = AttributeSource.MONETX
# The attributes a monitoring import may set on a CI (never owner, impact, custom fields).
SETTABLE = frozenset({"name", "site_id", "description"})


@dataclass(frozen=True)
class MonitoredUpdate:
    """What an update changed, and what a stronger source kept (never overwritten)."""

    changed: tuple[str, ...]
    kept: tuple[str, ...]


async def _type_id(session: AsyncSession, api_name: str) -> uuid.UUID:
    await ensure_defaults(session)
    found = await session.scalar(
        select(CiType.id).where(CiType.api_name == api_name, CiType.deleted_at.is_(None))
    )
    if found is None:
        found = await session.scalar(
            select(CiType.id).where(CiType.api_name == "hardware", CiType.deleted_at.is_(None))
        )
    if found is None:
        raise ValueError(api_name)
    return found


async def monitored_ci_create(
    session: AsyncSession,
    *,
    type_api_name: str,
    values: Mapping[str, Any],
    source: Source,
) -> uuid.UUID:
    """A new CI for a monitored device, by the sync identity, stamped `monetx`."""
    sent = {k: v for k, v in values.items() if k in SETTABLE and v is not None}
    record = await cis._add(  # noqa: SLF001 - the CMDB's own write path, for its sync identity
        session,
        None,
        {**sent, "type_id": await _type_id(session, type_api_name)},
        source,
        origin=domain.CiSource.MONETX,
        stamp_as=STAMP,
    )
    return record.id


async def monitored_ci_update(
    session: AsyncSession, ci_id: uuid.UUID, values: Mapping[str, Any], *, source: Source
) -> MonitoredUpdate | None:
    """Bring a monitored device's CI up to date where `monetx` wins (None: the CI is gone)."""
    record = await session.scalar(
        select(Ci).where(Ci.id == ci_id, Ci.deleted_at.is_(None)).with_for_update()
    )
    if record is None:
        return None
    precedence = source_rules.precedence_of((await get_settings(session)).source_precedence)
    incoming = {
        k: str(v) if isinstance(v, uuid.UUID) else v for k, v in values.items() if k in SETTABLE
    }
    current = field_rules.flat(cis.snapshot(record))
    plan = sync_rules.plan(precedence, current, cis.effective_stamps(record), incoming, STAMP)
    if plan.changes:
        typed = {
            k: uuid.UUID(v) if k == "site_id" and isinstance(v, str) else v
            for k, v in plan.changes.items()
        }
        await cis.sync_update(session, record, typed, source=source, stamp_as=STAMP)
    return MonitoredUpdate(tuple(sorted(plan.changes)), tuple(plan.kept))


async def monitored_link(
    session: AsyncSession,
    from_ci_id: uuid.UUID,
    to_ci_id: uuid.UUID,
    *,
    type_code: str,
    source: Source,
) -> uuid.UUID | None:
    """A relationship the import owns, if both CIs are live and it doesn't exist (else None)."""
    if from_ci_id == to_ci_id:
        return None
    await relationships.ensure_types(session)
    kind = await session.scalar(
        select(RelationshipType).where(
            RelationshipType.code == type_code, RelationshipType.deleted_at.is_(None)
        )
    )
    if kind is None:
        return None
    rows = await relationships._locked(session, [from_ci_id, to_ci_id])  # noqa: SLF001 - own module
    if len(rows) < 2:  # noqa: PLR2004 - both ends
        return None
    there = await session.scalar(
        select(Relationship.id).where(
            Relationship.type_id == kind.id,
            Relationship.from_ci_id == from_ci_id,
            Relationship.to_ci_id == to_ci_id,
            Relationship.deleted_at.is_(None),
        )
    )
    if there is not None:
        return None
    made = await relationships.RelationshipRepository(session).add(
        Relationship(type_id=kind.id, from_ci_id=from_ci_id, to_ci_id=to_ci_id)
    )
    forward = rel.RelationshipDirection.FORWARD
    await relationships._touch(  # noqa: SLF001 - own module
        session, None, rows[from_ci_id], "child_added",
        [relationships._link(kind.id, forward, to_ci_id)], source,  # noqa: SLF001
    )  # fmt: skip
    await relationships._touch(  # noqa: SLF001 - own module
        session, None, rows[to_ci_id], "child_added",
        [relationships._link(kind.id, rel.RelationshipDirection.INVERSE, from_ci_id)],  # noqa: SLF001
        source,
    )  # fmt: skip
    await record_event(
        session,
        RelationshipsChanged(
            ci_id=from_ci_id,
            action="added",
            type_id=kind.id,
            relationship_ids=[made.id],
            other_ci_ids=[to_ci_id],
        ),
        aggregate_id=from_ci_id,
        aggregate_version=rows[from_ci_id].version,
    )
    return made.id


async def monitored_unlink(
    session: AsyncSession, relationship_id: uuid.UUID, *, source: Source
) -> bool:
    """Remove a relationship the import made (soft delete; both ends get a version)."""
    row = await session.scalar(
        select(Relationship).where(
            Relationship.id == relationship_id, Relationship.deleted_at.is_(None)
        )
    )
    if row is None:
        return False
    rows = await relationships._locked(session, [row.from_ci_id, row.to_ci_id])  # noqa: SLF001
    row.deleted_at = system_clock.now()
    await session.flush()
    for ci_id, other, direction in (
        (row.from_ci_id, row.to_ci_id, rel.RelationshipDirection.FORWARD),
        (row.to_ci_id, row.from_ci_id, rel.RelationshipDirection.INVERSE),
    ):
        if ci_id in rows:
            await relationships._touch(  # noqa: SLF001 - own module
                session, None, rows[ci_id], "child_removed",
                [relationships._link(row.type_id, direction, other)], source,  # noqa: SLF001
            )  # fmt: skip
    await record_event(
        session,
        RelationshipsChanged(
            ci_id=row.from_ci_id,
            action="removed",
            type_id=row.type_id,
            relationship_ids=[row.id],
            other_ci_ids=[row.to_ci_id],
        ),
        aggregate_id=row.from_ci_id,
        aggregate_version=rows[row.from_ci_id].version if row.from_ci_id in rows else None,
    )
    return True


async def monitored_retire(session: AsyncSession, ci_id: uuid.UUID, *, source: Source) -> bool:
    """Move a CI monitoring no longer reports to the first end-of-life state (never deleted)."""
    record = await session.scalar(
        select(Ci).where(Ci.id == ci_id, Ci.deleted_at.is_(None)).with_for_update()
    )
    if record is None:
        return False
    current = await session.get(CiState, record.state_id)
    if current is not None and current.category == domain.CiStateCategory.END_OF_LIFE.value:
        return False
    ended = await session.scalar(
        select(CiState.id)
        .where(
            CiState.category == domain.CiStateCategory.END_OF_LIFE.value,
            CiState.deleted_at.is_(None),
        )
        .order_by(CiState.position, CiState.id)
        .limit(1)
    )
    if ended is None:
        return False
    await cis.sync_update(session, record, {"state_id": ended}, source=source, stamp_as=STAMP)
    return True
