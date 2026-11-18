"""Type trees of other modules, for custom fields scoped to a type subtree (0175).

The metadata module never reads another module's tables (rule 5e): a module whose records have
a tree of types (the CMDB's CI types, assets' product types) registers a `TypeTree` for its
entity. A field may then be scoped to one type and every type below it; an entity with no tree
refuses a scope (`custom_field_scope_unsupported`). Work items have none: unchanged.
"""

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transaction_memo
from app.modules.metadata.domain.fields import CustomFieldEntity


class TypeTree(Protocol):
    """One module's tree of record types (at most TYPE_TREE_DEPTH levels)."""

    async def lineage(self, session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID] | None:
        """The type itself, then each parent up to the root; None for a type not found."""
        ...

    async def subtree(self, session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID]:
        """The type and every type below it (empty for a type not found)."""
        ...


_TREES: dict[CustomFieldEntity, TypeTree] = {}
_MEMO = "metadata.type_lineage"


def register_type_tree(entity: CustomFieldEntity, tree: TypeTree) -> None:
    """Called once by the owning module at import (the same tree again is fine)."""
    current = _TREES.get(entity)
    if current is not None and current is not tree:
        msg = f"a type tree for {entity.value!r} is registered twice"
        raise ValueError(msg)
    _TREES[entity] = tree


def unregister_type_tree(entity: CustomFieldEntity) -> None:
    """For tests."""
    _TREES.pop(entity, None)


def tree_of(entity: CustomFieldEntity) -> TypeTree | None:
    """The entity's type tree, or None (no scope possible)."""
    return _TREES.get(entity)


async def lineage(
    session: AsyncSession, entity: CustomFieldEntity, type_id: uuid.UUID
) -> list[uuid.UUID] | None:
    """The type's lineage through the entity's tree, read once per transaction.

    None when the entity has no tree or the type is not found.
    """
    tree = _TREES.get(entity)
    if tree is None:
        return None
    memo = transaction_memo(session, _MEMO)
    key = (entity, type_id)
    if memo is not None and key in memo:
        cached: list[uuid.UUID] | None = memo[key]
        return None if cached is None else list(cached)
    found = await tree.lineage(session, type_id)
    if memo is not None:
        memo[key] = found
    return None if found is None else list(found)


def forget(session: AsyncSession, entity: CustomFieldEntity) -> None:
    """Drop this transaction's lineages of the entity's types (a type moved under a new parent)."""
    memo = transaction_memo(session, _MEMO)
    if memo is not None:
        for key in [k for k in memo if k[0] == entity]:
            del memo[key]


__all__ = [
    "TypeTree",
    "forget",
    "lineage",
    "register_type_tree",
    "tree_of",
    "unregister_type_tree",
]
