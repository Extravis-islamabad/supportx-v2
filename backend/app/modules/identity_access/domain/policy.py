"""The compiled subject and the decision rules: pure Python (architecture.md §11.2; WP-016).

A *subject* is everything needed to decide for one user in one tenant, compiled once from their
role assignments, memberships and the tenant's licence, then cached:

    grants        permission -> one or more (scope, condition) grants
    site_ids      sites the user belongs to          (for `site` scope)
    group_ids     support groups the user belongs to  (for `group` scope)
    not_entitled  permissions the roles grant but the licence does not include

A decision is allowed if ANY grant of the permission matches the record: its scope reaches the
record and its attribute condition (filter DSL, optional) holds for it.
"""

import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType
from typing import Any

from app.core.authorization import Scope
from app.modules.identity_access.domain.permissions import Catalogue, broadest, covers

# JSON filter DSL tree (shared/api/filters.py), as stored in role_permissions.condition.
Condition = Mapping[str, Any]


@dataclass(frozen=True)
class Grant:
    """Permission held at a scope, optionally only for records matching `condition`."""

    scope: Scope
    condition: Condition | None = None


@dataclass(frozen=True)
class Decision:
    """The outcome of a check, with a machine reason (logged and returned as a problem param)."""

    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        """Truthy when allowed, so `if decision:` reads naturally."""
        return self.allowed


ALLOW = Decision(allowed=True, reason="allowed")


@dataclass(frozen=True)
class Subject:
    """One user's effective permissions in one tenant."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role_keys: frozenset[str]
    is_tenant_admin: bool
    grants: Mapping[str, tuple[Grant, ...]]
    site_ids: frozenset[uuid.UUID] = frozenset()
    group_ids: frozenset[uuid.UUID] = frozenset()
    not_entitled: frozenset[str] = frozenset()
    extra: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def holds(self, permission: str) -> bool:
        """Whether the permission is held at any scope (route-level check)."""
        return permission in self.grants

    def check(self, permission: str) -> Decision:
        """Route-level decision with its reason."""
        if self.holds(permission):
            return ALLOW
        if permission in self.not_entitled:
            return Decision(allowed=False, reason="not_entitled")
        return Decision(allowed=False, reason="no_permission")

    def broadest_scope(self, permission: str) -> Scope | None:
        """The widest scope held for `permission` (None if not held)."""
        grants = self.grants.get(permission, ())
        return broadest(g.scope for g in grants) if grants else None

    # --- cache form ------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form for the Valkey cache."""
        return {
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id),
            "role_keys": sorted(self.role_keys),
            "is_tenant_admin": self.is_tenant_admin,
            "grants": {
                key: [{"scope": g.scope, "condition": g.condition} for g in grants]
                for key, grants in self.grants.items()
            },
            "site_ids": sorted(str(i) for i in self.site_ids),
            "group_ids": sorted(str(i) for i in self.group_ids),
            "not_entitled": sorted(self.not_entitled),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Subject":
        """Inverse of to_dict."""
        return cls(
            tenant_id=uuid.UUID(data["tenant_id"]),
            user_id=uuid.UUID(data["user_id"]),
            role_keys=frozenset(data["role_keys"]),
            is_tenant_admin=bool(data["is_tenant_admin"]),
            grants=MappingProxyType(
                {
                    key: tuple(Grant(g["scope"], g["condition"]) for g in grants)
                    for key, grants in data["grants"].items()
                }
            ),
            site_ids=frozenset(uuid.UUID(i) for i in data["site_ids"]),
            group_ids=frozenset(uuid.UUID(i) for i in data["group_ids"]),
            not_entitled=frozenset(data["not_entitled"]),
        )


def compile_subject(  # noqa: PLR0913 - keyword-only inputs of the compilation
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_keys: Iterable[str],
    grants: Iterable[tuple[str, Grant]],
    catalogue: Catalogue,
    entitled_features: frozenset[str],
    site_ids: frozenset[uuid.UUID] = frozenset(),
    group_ids: frozenset[uuid.UUID] = frozenset(),
    is_tenant_admin: bool = False,
) -> Subject:
    """Merge the grants of all roles into one subject.

    Unknown permissions (a module removed) and scopes the permission does not allow are dropped;
    permissions whose licence feature is missing go to `not_entitled`. An unconditioned grant at
    a scope makes narrower or conditioned grants of the same permission redundant.
    """
    merged: dict[str, dict[tuple[str, str], Grant]] = {}
    not_entitled: set[str] = set()
    for key, grant in grants:
        spec = catalogue.get(key)
        if spec is None or grant.scope not in spec.scopes:
            continue
        if spec.feature is not None and spec.feature not in entitled_features:
            not_entitled.add(key)
            continue
        merged.setdefault(key, {})[(grant.scope, _canonical(grant.condition))] = grant
    simplified = {key: _simplify(list(grants_of.values())) for key, grants_of in merged.items()}
    return Subject(
        tenant_id=tenant_id,
        user_id=user_id,
        role_keys=frozenset(role_keys),
        is_tenant_admin=is_tenant_admin,
        grants=MappingProxyType(dict(sorted(simplified.items()))),
        site_ids=site_ids,
        group_ids=group_ids,
        not_entitled=frozenset(not_entitled - set(simplified)),
    )


def _canonical(condition: Condition | None) -> str:
    return json.dumps(condition, sort_keys=True)


def _simplify(grants: list[Grant]) -> tuple[Grant, ...]:
    """Drop grants another unconditioned grant of the same permission already covers."""
    unconditional = [g for g in grants if g.condition is None]
    kept = [
        g for g in grants if not any(u is not g and covers(u.scope, g.scope) for u in unconditional)
    ]
    return tuple(sorted(kept, key=lambda g: (g.scope, _canonical(g.condition))))


# --- in-memory evaluation of a single record (same semantics as the SQL compiler) ---------------


@dataclass(frozen=True)
class RecordFacts:
    """What a check needs to know about one record."""

    owner_ids: frozenset[uuid.UUID] = frozenset()
    site_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    attributes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


def in_scope(subject: Subject, scope: Scope, record: RecordFacts) -> bool:
    """Whether `scope` (held by `subject`) reaches `record`."""
    if scope == "all":
        return True
    if scope == "site":
        return record.site_id is not None and record.site_id in subject.site_ids
    if scope == "group":
        return record.group_id is not None and record.group_id in subject.group_ids
    return subject.user_id in record.owner_ids


def decide(subject: Subject, permission: str, record: RecordFacts) -> Decision:
    """Allowed if any grant's scope reaches the record and its condition holds."""
    route_level = subject.check(permission)
    if not route_level:
        return route_level
    grants = subject.grants[permission]
    reached = [g for g in grants if in_scope(subject, g.scope, record)]
    if not reached:
        return Decision(allowed=False, reason="out_of_scope")
    if any(g.condition is None or matches(g.condition, record.attributes) for g in reached):
        return ALLOW
    return Decision(allowed=False, reason="condition_not_met")


def matches(condition: Condition, attributes: Mapping[str, Any]) -> bool:
    """Evaluate a filter DSL tree against a record's attributes.

    Mirrors app/shared/api/filters.py: `contains`/`starts_with` are case-insensitive, `ne` and
    `not_in` also match NULL. Relative-date operators need the database: a condition using them
    never matches in memory (deny), so check such records with the SQL scope filter instead.
    """
    if "and" in condition:
        return all(matches(node, attributes) for node in condition["and"])
    if "or" in condition:
        return any(matches(node, attributes) for node in condition["or"])
    return _matches_condition(
        str(condition.get("op")),
        attributes.get(str(condition.get("field"))),
        condition.get("value"),
    )


def _matches_condition(op: str, value: Any, target: Any) -> bool:  # noqa: ANN401, PLR0911 - JSON values; one branch per operator
    if op == "is_null":
        return value is None
    if op == "is_not_null":
        return value is not None
    if op == "ne":
        return value is None or _norm(value) != _norm(target)
    if op == "not_in":
        return value is None or _norm(value) not in {_norm(t) for t in target or ()}
    if value is None:
        return False
    if op in {"eq", "in"}:
        wanted = [target] if op == "eq" else list(target or ())
        return _norm(value) in {_norm(t) for t in wanted}
    if op in {"contains", "starts_with"}:
        text, needle = str(value).casefold(), str(target).casefold()
        return needle in text if op == "contains" else text.startswith(needle)
    if op in {"gt", "gte", "lt", "lte", "between"}:
        return _compare(op, _norm(value), target)
    return False


def _norm(value: Any) -> Any:  # noqa: ANN401 - JSON scalar or record attribute
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _compare(op: str, value: Any, target: Any) -> bool:  # noqa: ANN401 - comparable scalars
    try:
        if op == "between":
            low, high = (_norm(t) for t in target)
            return bool(low <= value <= high)
        target = _norm(target)
        return bool(
            {
                "gt": value > target,
                "gte": value >= target,
                "lt": value < target,
                "lte": value <= target,
            }[op]
        )
    except (TypeError, ValueError):
        return False


def can_delegate(
    subject: Subject, permission: str, scope: Scope, condition: Condition | None
) -> bool:
    """Whether `subject` may hand out `permission` at `scope` (with `condition`) to anyone.

    No privilege escalation (WP-016): a user can only grant what they hold themselves, at the
    same or a narrower scope; a conditioned grant can be passed on only with the same condition.
    Tenant admins may grant anything in the catalogue.
    """
    if subject.is_tenant_admin:
        return True
    for held in subject.grants.get(permission, ()):
        if not covers(held.scope, scope):
            continue
        if held.condition is None or _canonical(held.condition) == _canonical(condition):
            return True
    return False
