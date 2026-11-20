"""Which CIs a fine-grained access rule may narrow to (ADR-053; identity_access's port).

A rule names any of: CI types (each with its whole subtree), sites, owner groups, managed-by
groups, and a criticality ceiling (`low` .. `critical`: a CI passes when its criticality is at
or below it; a CI with none passes). Every criterion a rule names must hold. The subtree is one
SQL predicate: the type IDs under the named ones (a recursive query on the small type table),
then the indexed `type_id` match on the CIs.
"""

import itertools
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement, and_, literal, or_, select

from app.modules.cmdb.domain.types import CiImpact
from app.modules.cmdb.infra.models import Ci, CiType
from app.modules.identity_access import AccessCriteria, register_access_criteria

# Each subtree query gets its own CTE name: two rules (two roles) in one statement must not
# share one (lane B, S3a).
_CTE_SEQ = itertools.count()

RESOURCE = "ci"
CEILING = tuple(i.value for i in CiImpact)  # lowest first

FIELDS: Mapping[str, Any] = {
    "type_ids": "ids",
    "site_ids": "ids",
    "owner_group_ids": "ids",
    "managed_by_group_ids": "ids",
    "criticality_max": "ceiling",
}


def _ids(values: Sequence[str]) -> list[uuid.UUID]:
    return [uuid.UUID(str(v)) for v in values]


def subtree(type_ids: Sequence[uuid.UUID]) -> Any:  # noqa: ANN401 - a SQLAlchemy select of IDs
    """The named CI types and every type under them (RLS keeps it to the tenant)."""
    roots = (
        select(CiType.id)
        .where(CiType.id.in_(list(type_ids)))
        .cte(f"ra_roots_{next(_CTE_SEQ)}", recursive=True)
    )
    below = select(CiType.id).join(roots, CiType.parent_id == roots.c.id)
    tree = roots.union_all(below)
    return select(tree.c.id)


def _at_or_below(ceiling: str) -> ColumnElement[bool]:
    allowed = CEILING[: CEILING.index(ceiling) + 1]
    return or_(Ci.criticality.is_(None), Ci.criticality.in_(allowed))


def compile_rule(criteria: Mapping[str, Any]) -> ColumnElement[bool]:
    """One rule's criteria on `cmdb_cis` (every criterion named must hold)."""
    parts: list[ColumnElement[bool]] = []
    if criteria.get("type_ids"):
        parts.append(Ci.type_id.in_(subtree(_ids(criteria["type_ids"]))))
    if criteria.get("site_ids"):
        parts.append(Ci.site_id.in_(_ids(criteria["site_ids"])))
    if criteria.get("owner_group_ids"):
        parts.append(Ci.owner_group_id.in_(_ids(criteria["owner_group_ids"])))
    if criteria.get("managed_by_group_ids"):
        parts.append(Ci.managed_by_group_id.in_(_ids(criteria["managed_by_group_ids"])))
    ceiling = criteria.get("criticality_max")
    if isinstance(ceiling, str) and ceiling in CEILING:
        parts.append(_at_or_below(ceiling))
    # A rule naming nothing is refused when saved; never let one through by accident.
    return and_(*parts) if parts else literal(False)  # noqa: FBT003 - SQL FALSE


def register() -> None:
    """The CI's criteria, at import (like the other ports)."""
    register_access_criteria(
        RESOURCE,
        AccessCriteria(fields=FIELDS, compile=compile_rule, ceilings={"criticality_max": CEILING}),
    )


__all__ = ["CEILING", "FIELDS", "RESOURCE", "compile_rule", "register", "subtree"]
