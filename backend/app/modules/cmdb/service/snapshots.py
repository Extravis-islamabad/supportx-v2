"""A CI's saved versions (REQ-CMDB-024; S1's write side, S2's relationships).

Every save of a CI appends a snapshot to `cmdb_ci_versions` (the app may only add): its fields
and, since S2 (0180), its live relationships as `relationships`, a sorted list of
`{relationship_id, type_id, direction, ci_id}` read from this CI's side. A version is then whole
on its own: "as of" and compare read snapshots only, never timestamps of the relationship rows
(their `created_at` is the app clock, a snapshot's `saved_at` the transaction's). Snapshots
saved before 0180 have no `relationships`: there were none then.

Every writer of a version (CI saves, relationship changes, erasure moves and redactions) calls
`save_version`, so no version is ever missing its relationships.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.domain.relationships import RelationshipDirection
from app.modules.cmdb.infra.models import Ci, CiVersion, Relationship
from app.shared.ids import new_id

LINKS = "relationships"


async def links_of(session: AsyncSession, ci_id: uuid.UUID) -> list[dict[str, str]]:
    """The CI's live relationships from its own side, in a stable order."""
    rows = await session.execute(
        select(
            Relationship.id, Relationship.type_id, Relationship.from_ci_id, Relationship.to_ci_id
        )
        .where(
            Relationship.deleted_at.is_(None),
            or_(Relationship.from_ci_id == ci_id, Relationship.to_ci_id == ci_id),
        )
        .order_by(Relationship.id)
    )
    links = [
        {
            "relationship_id": str(rid),
            "type_id": str(type_id),
            "direction": (
                RelationshipDirection.FORWARD if src == ci_id else RelationshipDirection.INVERSE
            ).value,
            "ci_id": str(dst if src == ci_id else src),
        }
        for rid, type_id, src, dst in rows
    ]
    return sorted(links, key=lambda link: (link["type_id"], link["direction"], link["ci_id"]))


async def save_version(
    session: AsyncSession, record: Ci, fields: Mapping[str, Any], saved_by: uuid.UUID | None
) -> None:
    """Append the CI as it is now: `fields` (cis.snapshot) and its live relationships."""
    await session.execute(
        insert(CiVersion).values(
            tenant_id=record.tenant_id,
            id=new_id(),
            ci_id=record.id,
            version=record.version,
            snapshot={**fields, LINKS: await links_of(session, record.id)},
            saved_by=saved_by,
        )
    )
