"""Field access per role: the rules, the catalogue of rule-able fields, who sees what (ADR-047).

- Rules: one per role, record type and field (read_only, masked or hidden). Viewing needs
  `roles.view`; setting, changing and removing need `roles.manage` too. Adding or changing a rule
  needs the `field_access` feature; viewing and removing never do, and the rules always apply
  (§13): a lapse never shows what a rule hides, and the admin can still take a rule away.
- At most `RULES_PER_TENANT` live rules (a 422 `field_access_limit_reached` past it).
- Every change emits `identity_access.field_access.changed` in the same transaction; the authz
  consumer then makes every compiled subject of the tenant stale, so the person's next request
  has it (§3). The route audits each change with the mode before and after.
- The catalogue: each module registers its record types' rule-able fields (a port), so this
  module never knows another's fields. Core fields (subject, status, ...) are never offered.
- Who sees what: per field, the people in each mode, from the same `effective()` the subject's
  compile uses (§2), so the view and the enforcement never disagree.
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import access_changed
from app.core.errors import (
    Conflict,
    EntitlementRequired,
    FieldError,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.modules.identity_access.domain import field_access as rules
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import FieldAccessChanged
from app.modules.identity_access.infra.models import (
    GroupRole,
    Role,
    RoleFieldAccess,
    User,
    UserRole,
)
from app.modules.identity_access.service.policy import UNMAPPED_DEFAULT
from app.modules.licensing import Feature, has_feature
from app.modules.organization import active_groups, users_in_groups
from app.shared.events import record_event
from app.shared.history import stale_version

VIEW = "roles.view"
MANAGE = "roles.manage"
FEATURE = Feature.FIELD_ACCESS
RECORD_TYPE = "role_field_access"
PEOPLE_SHOWN = 100  # per mode in the effective view; the count is always complete

Action = Literal["created", "updated", "deleted"]


# --- the catalogue port ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleableField:
    """A field an admin may restrict: a built-in (labelled) or a custom field (its own names)."""

    key: str  # "root_cause", "custom.salary_band"
    label_key: str | None = None  # built-ins: the label the UI shows
    labels: dict[str, str] = field(default_factory=dict)  # custom fields: the admin's names
    custom: bool = False
    personal_data: bool = False
    sensitive: bool = False


Provider = Callable[[AsyncSession], Awaitable[Sequence[RuleableField]]]
_CATALOGUES: dict[str, Provider] = {}


def register_field_catalogue(record_type: str, provider: Provider) -> None:
    """A module offers a record type's rule-able fields (at import, like other ports)."""
    _CATALOGUES[record_type] = provider


def record_types() -> list[str]:
    """Every record type with rule-able fields, sorted."""
    return sorted(_CATALOGUES)


async def catalogue(session: AsyncSession, record_type: str) -> list[RuleableField]:
    """The rule-able fields of a record type (422 for a type that has none)."""
    provider = _CATALOGUES.get(record_type)
    if provider is None:
        raise _invalid(name="record_type", code="invalid_choice")
    return sorted(await provider(session), key=lambda f: (f.custom, f.key))


# --- rules ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleChange:
    """One change of a rule, for the audit entry (the mode before and after)."""

    rule: RoleFieldAccess
    action: Action
    old_mode: str | None
    new_mode: str | None


def _require(subject: Subject, *permissions: str) -> None:
    for permission in permissions:
        if not subject.holds(permission):
            raise PermissionDenied(params={"permission": permission, "reason": "no_permission"})


def _invalid(*, name: str, code: str) -> ValidationFailed:
    return ValidationFailed(
        errors=[FieldError(field=f"body.{name}", code=code, message_key=f"errors.field.{code}")]
    )


async def _entitled(subject: Subject) -> None:
    """Adding or changing a rule needs the feature (removing and viewing never do, §13)."""
    if not await has_feature(subject.tenant_id, FEATURE):
        raise EntitlementRequired(params={"feature": FEATURE.value})


async def _role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)))
    if role is None:
        raise NotFound(code="role_not_found", params={"id": str(role_id)})
    return role


async def list_rules(
    session: AsyncSession,
    subject: Subject,
    *,
    role_id: uuid.UUID | None = None,
    record_type: str | None = None,
) -> list[RoleFieldAccess]:
    """The live rules, by role, type and field; narrowed to a role or a type when given."""
    _require(subject, VIEW)
    query = select(RoleFieldAccess).where(RoleFieldAccess.deleted_at.is_(None))
    if role_id is not None:
        query = query.where(RoleFieldAccess.role_id == role_id)
    if record_type is not None:
        query = query.where(RoleFieldAccess.record_type == record_type)
    query = query.order_by(
        RoleFieldAccess.role_id, RoleFieldAccess.record_type, RoleFieldAccess.field
    )
    return list((await session.scalars(query)).all())


async def _announce(session: AsyncSession, row: RoleFieldAccess, mode: str | None) -> None:
    # Compiled subjects go stale right after this commits (this process) and when the event
    # reaches the authz consumer (every other process): the person's next request has it.
    access_changed(session)
    await record_event(
        session,
        FieldAccessChanged(
            role_id=row.role_id,
            record_type=row.record_type,
            field=row.field,
            mode=mode,  # type: ignore[arg-type]  # one of the CHECK's codes, or None when removed
        ),
        aggregate_id=row.role_id,
        aggregate_version=row.version,
    )


async def set_rule(  # noqa: PLR0913 - the rule's four parts and who sets it
    session: AsyncSession,
    subject: Subject,
    *,
    role_id: uuid.UUID,
    record_type: str,
    field_key: str,
    mode: rules.FieldMode,
) -> RuleChange:
    """A new rule (409 `field_access_rule_exists` when the role has one for that field)."""
    _require(subject, VIEW, MANAGE)
    await _entitled(subject)
    if mode not in rules.RULE_MODES:
        raise _invalid(name="mode", code="invalid_choice")
    await _role(session, role_id)
    if field_key not in {f.key for f in await catalogue(session, record_type)}:
        raise _invalid(name="field", code="field_not_ruleable")
    live = await session.scalar(
        select(func.count())
        .select_from(RoleFieldAccess)
        .where(RoleFieldAccess.deleted_at.is_(None))
    )
    if (live or 0) >= rules.RULES_PER_TENANT:
        raise ValidationFailed(
            code="field_access_limit_reached", params={"limit": rules.RULES_PER_TENANT}
        )
    row = RoleFieldAccess(
        tenant_id=subject.tenant_id,
        role_id=role_id,
        record_type=record_type,
        field=field_key,
        mode=mode.value,
        created_by=subject.user_id,
        updated_by=subject.user_id,
    )
    session.add(row)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:  # the partial unique index: one live rule per role and field
        raise Conflict(code="field_access_rule_exists") from exc
    await _announce(session, row, row.mode)
    return RuleChange(row, "created", None, row.mode)


async def _rule(session: AsyncSession, rule_id: uuid.UUID) -> RoleFieldAccess:
    row = await session.scalar(
        select(RoleFieldAccess)
        .where(RoleFieldAccess.id == rule_id, RoleFieldAccess.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="field_access_rule_not_found", params={"id": str(rule_id)})
    return row


async def _fresh(session: AsyncSession, row: RoleFieldAccess, expected_version: int) -> None:
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
    mode: rules.FieldMode,
    expected_version: int,
) -> RuleChange:
    """Another mode for a rule (If-Match); the same mode changes nothing."""
    _require(subject, VIEW, MANAGE)
    await _entitled(subject)
    if mode not in rules.RULE_MODES:
        raise _invalid(name="mode", code="invalid_choice")
    row = await _rule(session, rule_id)
    await _fresh(session, row, expected_version)
    old = row.mode
    if old == mode.value:
        return RuleChange(row, "updated", old, old)
    row.mode = mode.value
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _announce(session, row, row.mode)
    return RuleChange(row, "updated", old, row.mode)


async def remove_rule(
    session: AsyncSession,
    subject: Subject,
    rule_id: uuid.UUID,
    *,
    expected_version: int,
) -> RuleChange:
    """Take a rule away (If-Match): allowed whatever the licence says (§13)."""
    _require(subject, VIEW, MANAGE)
    row = await _rule(session, rule_id)
    await _fresh(session, row, expected_version)
    old = row.mode
    row.deleted_at = datetime.now(UTC)
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _announce(session, row, None)
    return RuleChange(row, "deleted", old, None)


# --- who sees what --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Person:
    """Someone in the effective view."""

    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class Effective:
    """One field: per mode, how many people are in it and the first of them by name."""

    record_type: str
    field: str
    counts: dict[str, int]
    people: dict[str, list[Person]]


async def _role_sets(session: AsyncSession) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Each active person's live roles: their own, their active groups', or the default.

    The same membership the subject's compile uses (PolicyService.compile), in bulk.
    """
    live_roles = select(Role.id).where(Role.deleted_at.is_(None))
    people = (
        await session.execute(
            select(User.id, User.user_type, User.roles_mapped_at).where(
                User.deleted_at.is_(None), User.status == "active"
            )
        )
    ).all()
    sets: dict[uuid.UUID, set[uuid.UUID]] = {p.id: set() for p in people}
    for row in await session.execute(
        select(UserRole.user_id, UserRole.role_id).where(UserRole.role_id.in_(live_roles))
    ):
        if row.user_id in sets:
            sets[row.user_id].add(row.role_id)
    carried = (
        await session.execute(
            select(GroupRole.group_id, GroupRole.role_id).where(GroupRole.role_id.in_(live_roles))
        )
    ).all()
    active = await active_groups(session, frozenset(r.group_id for r in carried))
    for group_id in active:
        members = set((await session.scalars(users_in_groups(frozenset({group_id})))).all())
        for role in (r.role_id for r in carried if r.group_id == group_id):
            for member in members & sets.keys():
                sets[member].add(role)
    defaults: dict[str, uuid.UUID] = dict(
        (
            await session.execute(
                select(Role.key, Role.id).where(
                    Role.key.in_(set(UNMAPPED_DEFAULT.values())), Role.deleted_at.is_(None)
                )
            )
        )
        .tuples()
        .all()
    )
    for person in people:
        if not sets[person.id] and person.roles_mapped_at is None:
            default = UNMAPPED_DEFAULT.get(person.user_type)
            if default is not None and default in defaults:
                sets[person.id].add(defaults[default])
    return sets


def _mode_for(
    roles_held: Iterable[uuid.UUID], by_role: dict[uuid.UUID, str], key: tuple[str, str]
) -> rules.FieldMode:
    held = set(roles_held)
    found = rules.effective(len(held), [(*key, by_role[r]) for r in held if r in by_role])
    return found.get(key, rules.FieldMode.CLEAR)


async def effective_access(
    session: AsyncSession, subject: Subject, *, record_type: str, field_key: str
) -> Effective:
    """Who sees one field how: per mode, the count and the first people by name (§2)."""
    _require(subject, VIEW)
    if field_key not in {f.key for f in await catalogue(session, record_type)}:
        raise _invalid(name="field", code="field_not_ruleable")
    by_role = {
        row.role_id: row.mode
        for row in await session.execute(
            select(RoleFieldAccess.role_id, RoleFieldAccess.mode).where(
                RoleFieldAccess.record_type == record_type,
                RoleFieldAccess.field == field_key,
                RoleFieldAccess.deleted_at.is_(None),
            )
        )
    }
    sets = await _role_sets(session)
    key = (record_type, field_key)
    in_mode: dict[str, list[uuid.UUID]] = {m.value: [] for m in rules.FieldMode}
    for person, held in sets.items():
        in_mode[_mode_for(held, by_role, key).value].append(person)
    shown_ids = {p for ids in in_mode.values() for p in ids}
    names = (
        dict(
            (
                await session.execute(
                    select(User.id, User.display_name).where(User.id.in_(shown_ids))
                )
            ).all()
        )
        if shown_ids
        else {}
    )
    people = {
        mode: sorted((Person(p, names.get(p, "")) for p in ids), key=lambda x: x.name.casefold())[
            :PEOPLE_SHOWN
        ]
        for mode, ids in in_mode.items()
    }
    return Effective(record_type, field_key, {m: len(ids) for m, ids in in_mode.items()}, people)


__all__ = [
    "FEATURE",
    "MANAGE",
    "VIEW",
    "Effective",
    "Person",
    "RuleChange",
    "RuleableField",
    "catalogue",
    "change_rule",
    "effective_access",
    "list_rules",
    "record_types",
    "register_field_catalogue",
    "remove_rule",
    "set_rule",
]
