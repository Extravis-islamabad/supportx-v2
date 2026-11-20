"""Fine-grained access to assets and CIs: the criteria port, the rules, enforcement (ADR-053).

- **The criteria port.** cmdb and assets register their criteria (`register_access_criteria`):
  which criteria a rule may name (type with its subtree, site, groups, a criticality ceiling),
  and how one rule's criteria compile into SQL on their own table. This module never knows
  their columns.
- **Enforcement** is inside `scope_filter` (service/policy.py): a resource type that declares
  `narrowed_as` gets the person's rules ANDed onto its scope predicate, so every list, search,
  picker, lookup, export, report source, realtime check and mention passage that already uses
  the scope filter is narrowed too, and a record outside the set is out of scope (404).
- **Rules.** Viewing needs `roles.view`; adding, changing and removing need `roles.manage` too.
  Adding or changing needs the `fine_grained_access` feature (Enterprise, D-172); viewing and
  removing never do, and existing rules always apply: a lapse never shows what a rule hides.
  At most `RULES_PER_TENANT` live rules. Each change emits `identity_access.resource_access.
  changed` in the same transaction (the authz consumer then makes compiled subjects stale).
- **The effective view** for a person is that person's compiled subject: the same compile.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import access_changed
from app.core.errors import (
    EntitlementRequired,
    FieldError,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.modules.identity_access.domain import resource_access as rules
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import ResourceAccessChanged
from app.modules.identity_access.infra.models import Role, RoleResourceAccess
from app.modules.licensing import Feature, has_feature
from app.shared.events import record_event
from app.shared.history import stale_version

VIEW = "roles.view"
MANAGE = "roles.manage"
FEATURE = Feature.FINE_GRAINED_ACCESS
RECORD_TYPE = "role_resource_access"

Action = Literal["created", "updated", "deleted"]
CriterionKind = Literal["ids", "ceiling"]


# --- the criteria port ----------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessCriteria:
    """What a resource's rules may name, and how one rule compiles to SQL (the owning module).

    `fields`: criterion -> kind (`ids`: a list of IDs; `ceiling`: one code of `ceilings[name]`,
    lowest first). `compile` turns one rule's criteria into a predicate on the module's table;
    every criterion named must hold (AND within a rule).
    """

    fields: Mapping[str, CriterionKind]
    compile: Callable[[rules.Criteria], ColumnElement[bool]]
    ceilings: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


_CRITERIA: dict[str, AccessCriteria] = {}


def register_access_criteria(resource: str, criteria: AccessCriteria) -> None:
    """A module offers a resource's criteria (at import, like other ports)."""
    _CRITERIA[rules.Resource(resource).value] = criteria


def criteria_of(resource: str) -> AccessCriteria | None:
    """The registered criteria of a resource (None until its module registers)."""
    return _CRITERIA.get(resource)


def rules_predicate(resource: str, found: tuple[rules.Criteria, ...]) -> ColumnElement[bool]:
    """One role's rules for a resource as SQL: any rule lets a record through (a union).

    Fails closed: a resource whose module hasn't registered its criteria shows nothing.
    """
    registered = _CRITERIA.get(resource)
    if registered is None or not found:
        return false()
    return or_(*(registered.compile(c) for c in found))


# --- compile --------------------------------------------------------------------------------------


async def resource_access_of(
    session: AsyncSession, role_grants: Mapping[uuid.UUID, rules.RoleGrants]
) -> rules.Compiled:
    """The per-role reach of someone holding exactly these roles (with their own grants).

    Applied whatever the licence says, so a lapse never shows what a rule hides (ADR-053 §5).
    """
    if not role_grants:
        return rules.EMPTY
    rows = await session.execute(
        select(
            RoleResourceAccess.role_id, RoleResourceAccess.resource, RoleResourceAccess.criteria
        ).where(
            RoleResourceAccess.role_id.in_(list(role_grants)),
            RoleResourceAccess.deleted_at.is_(None),
        )
    )
    return rules.compile_access(
        role_grants, [(r.role_id, r.resource, dict(r.criteria)) for r in rows]
    )


# --- rules ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleChange:
    """One change of a rule, for the audit entry (its criteria before and after)."""

    rule: RoleResourceAccess
    action: Action
    old_criteria: dict[str, Any] | None
    new_criteria: dict[str, Any] | None


def _require(subject: Subject, *permissions: str) -> None:
    for permission in permissions:
        if not subject.holds(permission):
            raise PermissionDenied(params={"permission": permission, "reason": "no_permission"})


def _invalid(*, name: str, code: str) -> ValidationFailed:
    return ValidationFailed(
        errors=[FieldError(field=f"body.{name}", code=code, message_key=f"errors.field.{code}")]
    )


async def _entitled(subject: Subject) -> None:
    """Adding or changing a rule needs the feature (removing and viewing never do, §5)."""
    if not await has_feature(subject.tenant_id, FEATURE):
        raise EntitlementRequired(params={"feature": FEATURE.value})


async def _role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)))
    if role is None:
        raise NotFound(code="role_not_found", params={"id": str(role_id)})
    return role


def _clean(resource: str, criteria: Mapping[str, Any]) -> dict[str, Any]:
    """The criteria checked against the resource's registered ones (422 otherwise)."""
    try:
        kind = rules.Resource(resource)
    except ValueError:
        raise _invalid(name="resource", code="invalid_choice") from None
    registered = _CRITERIA.get(kind.value)
    if registered is None:
        raise _invalid(name="resource", code="invalid_choice")
    problems = rules.criteria_problems(criteria, registered.fields)
    for name, values in registered.ceilings.items():
        if name in criteria and criteria[name] not in values:
            problems.append(f"criterion_invalid:{name}")
    if problems:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field=f"body.criteria.{p.split(':', 1)[1]}" if ":" in p else "body.criteria",
                    code=p.split(":", 1)[0],
                    message_key=f"errors.field.{p.split(':', 1)[0]}",
                )
                for p in problems
            ]
        )
    return {k: [str(v) for v in value] if isinstance(value, list) else value
            for k, value in criteria.items()}  # fmt: skip


async def list_rules(
    session: AsyncSession,
    subject: Subject,
    *,
    role_id: uuid.UUID | None = None,
    resource: str | None = None,
) -> list[RoleResourceAccess]:
    """The live rules, by role and resource; narrowed to a role or a resource when given."""
    _require(subject, VIEW)
    query = select(RoleResourceAccess).where(RoleResourceAccess.deleted_at.is_(None))
    if role_id is not None:
        query = query.where(RoleResourceAccess.role_id == role_id)
    if resource is not None:
        query = query.where(RoleResourceAccess.resource == resource)
    query = query.order_by(
        RoleResourceAccess.role_id, RoleResourceAccess.resource, RoleResourceAccess.created_at
    )
    return list((await session.scalars(query)).all())


async def _announce(session: AsyncSession, row: RoleResourceAccess, *, removed: bool) -> None:
    # Compiled subjects go stale right after this commits (this process) and when the event
    # reaches the authz consumer (every other process): the person's next request has it.
    access_changed(session)
    await record_event(
        session,
        ResourceAccessChanged(
            role_id=row.role_id,
            rule_id=row.id,
            resource=row.resource,  # type: ignore[arg-type]  # one of the CHECK's codes
            removed=removed,
        ),
        aggregate_id=row.role_id,
        aggregate_version=row.version,
    )


async def add_rule(
    session: AsyncSession,
    subject: Subject,
    *,
    role_id: uuid.UUID,
    resource: str,
    criteria: Mapping[str, Any],
) -> RuleChange:
    """A new rule for a role (needs the feature; at most `RULES_PER_TENANT`)."""
    _require(subject, VIEW, MANAGE)
    await _entitled(subject)
    await _role(session, role_id)
    cleaned = _clean(resource, criteria)
    live = await session.scalar(
        select(func.count())
        .select_from(RoleResourceAccess)
        .where(RoleResourceAccess.deleted_at.is_(None))
    )
    if (live or 0) >= rules.RULES_PER_TENANT:
        raise ValidationFailed(
            code="resource_access_limit_reached", params={"limit": rules.RULES_PER_TENANT}
        )
    row = RoleResourceAccess(
        tenant_id=subject.tenant_id,
        role_id=role_id,
        resource=resource,
        criteria=cleaned,
        created_by=subject.user_id,
        updated_by=subject.user_id,
    )
    session.add(row)
    await session.flush()
    await _announce(session, row, removed=False)
    return RuleChange(row, "created", None, cleaned)


async def _rule(session: AsyncSession, rule_id: uuid.UUID) -> RoleResourceAccess:
    row = await session.scalar(
        select(RoleResourceAccess)
        .where(RoleResourceAccess.id == rule_id, RoleResourceAccess.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="resource_access_rule_not_found", params={"id": str(rule_id)})
    return row


async def _fresh(session: AsyncSession, row: RoleResourceAccess, expected_version: int) -> None:
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip


async def change_rule(
    session: AsyncSession,
    subject: Subject,
    rule_id: uuid.UUID,
    *,
    criteria: Mapping[str, Any],
    expected_version: int,
) -> RuleChange:
    """Other criteria for a rule (If-Match; needs the feature). The same criteria change nothing."""
    _require(subject, VIEW, MANAGE)
    await _entitled(subject)
    row = await _rule(session, rule_id)
    await _fresh(session, row, expected_version)
    cleaned = _clean(row.resource, criteria)
    old = dict(row.criteria)
    if old == cleaned:
        return RuleChange(row, "updated", old, old)
    row.criteria = cleaned
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _announce(session, row, removed=False)
    return RuleChange(row, "updated", old, cleaned)


async def remove_rule(
    session: AsyncSession, subject: Subject, rule_id: uuid.UUID, *, expected_version: int
) -> RuleChange:
    """Take a rule away (If-Match): allowed whatever the licence says (ADR-053 §5)."""
    _require(subject, VIEW, MANAGE)
    row = await _rule(session, rule_id)
    await _fresh(session, row, expected_version)
    old = dict(row.criteria)
    row.deleted_at = datetime.now(UTC)
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _announce(session, row, removed=True)
    return RuleChange(row, "deleted", old, None)


# --- the effective view ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Narrowed:
    """One resource for one person: each of their roles that sees it, by its rules."""

    rules: list[rules.Criteria]  # every narrowed role's rules, criteria only
    whole_scope_roles: int  # roles that see it with no rule: their own scope applies in full


@dataclass(frozen=True)
class Effective:
    """How one person sees assets and CIs: per resource, narrowed or not, and by which rules."""

    user_id: uuid.UUID
    tenant_admin: bool
    narrowed: dict[str, Narrowed]


def effective_of(target: Subject) -> Effective:
    """The person's narrowing, straight from their compiled subject (the same compile)."""
    return Effective(
        user_id=target.user_id,
        tenant_admin=target.is_tenant_admin,
        narrowed={
            resource: Narrowed(
                rules=[c for reach in reaches if reach.rules is not None for c in reach.rules],
                whole_scope_roles=sum(1 for reach in reaches if reach.rules is None),
            )
            for resource, reaches in target.resource_access.items()
        },
    )


__all__ = [
    "FEATURE",
    "MANAGE",
    "VIEW",
    "AccessCriteria",
    "Effective",
    "Narrowed",
    "RuleChange",
    "add_rule",
    "change_rule",
    "criteria_of",
    "effective_of",
    "list_rules",
    "register_access_criteria",
    "remove_rule",
    "resource_access_of",
    "rules_predicate",
]
