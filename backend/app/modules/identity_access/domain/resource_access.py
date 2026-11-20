"""Fine-grained access to assets and configuration items, narrow-only (ADR-053; D-172). Pure.

A rule is (role, resource, criteria). The resource is `asset` or `ci`; the criteria are a few
fields the owning module registers (type with its subtree, site, groups, a criticality ceiling),
each a list of values. A record matches a rule when it matches every criterion the rule names.

Semantics (ADR-053 §2, D-172), per role and then across roles:
- Each role that holds a permission of the resource's module shows **its own scope for that
  permission, narrowed by its own rules** (a union of them), or its whole scope when it has no
  rule for the resource.
- The person sees the **union of those per-role sets**. A rule never widens a role's own scope,
  and one role's scope is never combined with another role's rules, so nothing is ever granted.
- A person none of whose roles has a rule for the resource is not narrowed at all (the plain
  merged scope applies). Tenant admins are never narrowed (the caller skips them).

The same `compile_access` builds the person's subject and the effective-access view.
"""

import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from app.core.authorization import Scope

RULES_PER_TENANT = 500  # ADR-053 §1: past it a 422 `resource_access_limit_reached`
VALUES_PER_CRITERION = 200
CRITERIA_MAX_BYTES = 16 * 1024


class Resource(StrEnum):
    """What a rule narrows."""

    ASSET = "asset"
    CI = "ci"


# The permission module whose roles count for each resource.
MODULE_OF: Mapping[Resource, str] = MappingProxyType(
    {Resource.ASSET: "assets", Resource.CI: "cmdb"}
)

# One rule's criteria: {criterion: [values]} (a ceiling criterion holds one value).
Criteria = Mapping[str, Any]
# One role's grants of the module's permissions: {permission: ((scope, condition), ...)}.
RoleGrants = Mapping[str, tuple[tuple[Scope, Mapping[str, Any] | None], ...]]


@dataclass(frozen=True)
class RoleReach:
    """What one role shows of a resource: its own grants, narrowed by its own rules (or not)."""

    grants: RoleGrants
    rules: tuple[Criteria, ...] | None  # None: the role has no rule, its scope is whole


# {resource: (one RoleReach per role that sees it, ...)}; a resource missing from the mapping
# is not narrowed for the person (no role of theirs has a rule for it).
Compiled = Mapping[str, tuple[RoleReach, ...]]
EMPTY: Compiled = MappingProxyType({})


def _module_grants(grants: RoleGrants, resource: Resource) -> RoleGrants:
    prefix = MODULE_OF[resource] + "."
    return MappingProxyType(
        {p: tuple(g) for p, g in sorted(grants.items()) if p.startswith(prefix) and g}
    )


def compile_access(
    role_grants: Mapping[uuid.UUID, RoleGrants],
    rules: Iterable[tuple[uuid.UUID, str, Criteria]],
) -> Compiled:
    """The subject's form, from each role's (entitled) grants and the roles' rules.

    `rules` are (role, resource, criteria) of the person's roles. A resource appears only when
    some role that sees it has a rule; then every role that sees it is listed with its own
    grants and its own rules (None when it has none).
    """
    by_role: dict[tuple[uuid.UUID, str], list[Criteria]] = {}
    for role, resource, criteria in rules:
        by_role.setdefault((role, resource), []).append(criteria)
    result: dict[str, tuple[RoleReach, ...]] = {}
    for resource in Resource:
        seeing = {
            role: own
            for role in sorted(role_grants)
            if (own := _module_grants(role_grants[role], resource))
        }
        if not any((role, resource.value) in by_role for role in seeing):
            continue  # no role of the person's narrows it: the plain scope applies
        result[resource.value] = tuple(
            RoleReach(
                grants=own,
                rules=(
                    tuple(_frozen(c) for c in _unique(by_role[(role, resource.value)]))
                    if (role, resource.value) in by_role
                    else None
                ),
            )
            for role, own in seeing.items()
        )
    return MappingProxyType(result)


def narrowing(access: Compiled, resource: Resource | str) -> tuple[RoleReach, ...] | None:
    """The person's per-role reach for a resource, or None when not narrowed."""
    return access.get(str(resource))


def _canonical(criteria: Criteria) -> str:
    return json.dumps(criteria, sort_keys=True, default=str)


def _unique(found: list[Criteria]) -> list[Criteria]:
    seen: dict[str, Criteria] = {}
    for criteria in found:
        seen.setdefault(_canonical(criteria), criteria)
    return [seen[k] for k in sorted(seen)]


def _frozen(criteria: Criteria) -> Criteria:
    return MappingProxyType(
        {k: tuple(v) if isinstance(v, list | tuple) else v for k, v in criteria.items()}
    )


def _plain(criteria: Criteria) -> dict[str, Any]:
    return {k: list(v) if isinstance(v, tuple) else v for k, v in criteria.items()}


def to_json(access: Compiled) -> dict[str, list[dict[str, Any]]]:
    """The cache form."""
    return {
        resource: [
            {
                "grants": {p: [[s, c] for s, c in g] for p, g in reach.grants.items()},
                "rules": None if reach.rules is None else [_plain(c) for c in reach.rules],
            }
            for reach in reaches
        ]
        for resource, reaches in access.items()
    }


def from_json(data: Mapping[str, Any] | None) -> Compiled:
    """Inverse of to_json; a subject cached before this existed has none (not narrowed)."""
    if not data:
        return EMPTY
    result: dict[str, tuple[RoleReach, ...]] = {}
    for resource, reaches in data.items():
        if not all(isinstance(r, Mapping) and "grants" in r for r in reaches):
            # An unknown form never reads as "not narrowed" (that would show too much): the
            # cache treats it as a miss and the subject is compiled again.
            msg = "unknown resource access cache form"
            raise ValueError(msg)
        result[resource] = tuple(
            RoleReach(
                grants=MappingProxyType(
                    {p: tuple((cast("Scope", s), c) for s, c in g) for p, g in r["grants"].items()}
                ),
                rules=None if r["rules"] is None else tuple(_frozen(c) for c in r["rules"]),
            )
            for r in reaches
        )
    return MappingProxyType(result)


def criteria_problems(criteria: Mapping[str, Any], allowed: Mapping[str, str]) -> list[str]:
    """Problems of a rule's criteria against the criteria a resource offers.

    `allowed` maps each criterion to its kind: `ids` (a list of IDs) or `ceiling` (one code from
    the resource's own ordered list, checked by the module). Empty criteria never pass: a rule
    that names nothing would let everything through, which is no rule at all.
    """
    problems: list[str] = []
    if not criteria:
        return ["criteria_required"]
    if len(json.dumps(criteria, default=str)) > CRITERIA_MAX_BYTES:
        return ["criteria_too_large"]
    for name, value in criteria.items():
        kind = allowed.get(name)
        if kind is None:
            problems.append(f"criterion_unknown:{name}")
        elif kind == "ids":
            if not isinstance(value, list) or not value or len(value) > VALUES_PER_CRITERION:
                problems.append(f"criterion_invalid:{name}")
                continue
            try:
                for item in value:
                    uuid.UUID(str(item))
            except ValueError:
                problems.append(f"criterion_invalid:{name}")
        elif not isinstance(value, str) or not value:
            problems.append(f"criterion_invalid:{name}")
    return problems
