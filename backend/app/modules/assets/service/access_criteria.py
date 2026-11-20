"""Which assets a fine-grained access rule may narrow to (ADR-053; identity_access's port).

A rule names any of: product types (each with its whole subtree), sites and managing groups.
Every criterion a rule names must hold. The subtree is one SQL predicate: the type IDs under
the named ones (a recursive query on the small type table), then the indexed match on assets.
"""

import itertools
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement, and_, literal, select

from app.modules.assets.infra.models import Asset, AssetProductType
from app.modules.identity_access import AccessCriteria, register_access_criteria

# Each subtree query gets its own CTE name: two rules (two roles) in one statement must not
# share one (lane B, S3a).
_CTE_SEQ = itertools.count()

RESOURCE = "asset"

FIELDS: Mapping[str, Any] = {
    "product_type_ids": "ids",
    "site_ids": "ids",
    "managed_by_group_ids": "ids",
}


def _ids(values: Sequence[str]) -> list[uuid.UUID]:
    return [uuid.UUID(str(v)) for v in values]


def subtree(type_ids: Sequence[uuid.UUID]) -> Any:  # noqa: ANN401 - a SQLAlchemy select of IDs
    """The named product types and every type under them (RLS keeps it to the tenant)."""
    roots = (
        select(AssetProductType.id)
        .where(AssetProductType.id.in_(list(type_ids)))
        .cte(f"ra_asset_roots_{next(_CTE_SEQ)}", recursive=True)
    )
    below = select(AssetProductType.id).join(roots, AssetProductType.parent_id == roots.c.id)
    tree = roots.union_all(below)
    return select(tree.c.id)


def compile_rule(criteria: Mapping[str, Any]) -> ColumnElement[bool]:
    """One rule's criteria on `assets` (every criterion named must hold)."""
    parts: list[ColumnElement[bool]] = []
    if criteria.get("product_type_ids"):
        parts.append(Asset.product_type_id.in_(subtree(_ids(criteria["product_type_ids"]))))
    if criteria.get("site_ids"):
        parts.append(Asset.site_id.in_(_ids(criteria["site_ids"])))
    if criteria.get("managed_by_group_ids"):
        parts.append(Asset.managed_by_group_id.in_(_ids(criteria["managed_by_group_ids"])))
    # A rule naming nothing is refused when saved; never let one through by accident.
    return and_(*parts) if parts else literal(False)  # noqa: FBT003 - SQL FALSE


def register() -> None:
    """The asset's criteria, at import (like the other ports)."""
    register_access_criteria(RESOURCE, AccessCriteria(fields=FIELDS, compile=compile_rule))


__all__ = ["FIELDS", "RESOURCE", "compile_rule", "register", "subtree"]
