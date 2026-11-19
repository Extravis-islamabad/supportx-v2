"""Assets' product type tree for metadata's type-scoped custom fields (0175).

An asset custom field may belong to one product type and every type below it. Metadata never
reads assets' tables (rule 5e): this port answers for the tree, in the session's tenant (RLS).
Removed types are still answered: a field scoped to one keeps its values readable.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.assets.infra.models import AssetProductType

DEPTH = 8  # metadata's TYPE_TREE_DEPTH: deeper than any tree the product types allow


class ProductTypeTree:
    """The product type tree: a type's lineage and its subtree."""

    async def lineage(self, session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID] | None:
        """The type, then each parent up to the root; None for a type not found."""
        found: list[uuid.UUID] = []
        current: uuid.UUID | None = type_id
        while current is not None and len(found) < DEPTH:
            row = (
                await session.execute(
                    select(AssetProductType.id, AssetProductType.parent_id).where(
                        AssetProductType.id == current
                    )
                )
            ).one_or_none()
            if row is None:
                return found or None  # a broken link ends the lineage
            found.append(row.id)
            current = row.parent_id
        return found

    async def subtree(self, session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID]:
        """The type and every type below it (breadth first, at most DEPTH levels)."""
        known = await session.scalar(
            select(AssetProductType.id).where(AssetProductType.id == type_id)
        )
        if known is None:
            return []
        found = [type_id]
        level = [type_id]
        for _ in range(DEPTH):
            level = list(
                await session.scalars(
                    select(AssetProductType.id).where(AssetProductType.parent_id.in_(level))
                )
            )
            if not level:
                break
            found += level
        return found


TREE = ProductTypeTree()


def register() -> None:
    """Assets' import registers the tree (idempotent)."""
    metadata.register_type_tree(metadata.CustomFieldEntity.ASSET, TREE)
