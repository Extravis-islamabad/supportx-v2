"""The CI type tree for metadata's type-scoped custom fields (0175 part 2).

A CI custom field may belong to one CI type and every type below it. Metadata never reads the
CMDB's tables (rule 5e): this port answers for the tree, in the session's tenant (RLS). Removed
types are still answered, so a field scoped to one keeps its values readable.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.infra.models import CiType

DEPTH = domain.TYPE_DEPTH_MAX  # the CMDB's own cap, so a lineage is never cut short


class CiTypeTree:
    """The CI type tree: a type's lineage and its subtree."""

    async def lineage(self, session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID] | None:
        """The type, then each parent up to the root; None for a type not found."""
        found: list[uuid.UUID] = []
        current: uuid.UUID | None = type_id
        while current is not None and len(found) < DEPTH:
            row = (
                await session.execute(
                    select(CiType.id, CiType.parent_id).where(CiType.id == current)
                )
            ).one_or_none()
            if row is None:
                return found or None  # a broken link ends the lineage
            found.append(row.id)
            current = row.parent_id
        return found

    async def subtree(self, session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID]:
        """The type and every type below it (breadth first, at most DEPTH levels)."""
        known = await session.scalar(select(CiType.id).where(CiType.id == type_id))
        if known is None:
            return []
        found = [type_id]
        level = [type_id]
        for _ in range(DEPTH):
            level = list(
                await session.scalars(
                    select(CiType.id).where(CiType.parent_id.in_(level), CiType.id.not_in(found))
                )
            )
            if not level:
                break
            found += level
        return found


TREE = CiTypeTree()


def register() -> None:
    """The CMDB's import registers the tree (idempotent)."""
    metadata.register_type_tree(metadata.CustomFieldEntity.CI, TREE)
