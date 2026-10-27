"""People administration (WP-021; REQ-ADM-002..005, REQ-ADM-035; D-092).

An admin adds people before they ever sign in (their first sign-in links them by email, see
users.py), edits the person record, makes someone a technician (takes a licence seat), allows or
stops sign-in, and deactivates or reactivates. Nothing is ever deleted: a deactivated person keeps
their records, roles and groups; reactivation shows what they had and keeps only what the admin
confirms.

Every write: one transaction with its event (CLAUDE.md rule b), If-Match on changes (rule g), the
field history (§7.4), and the route audits it. Ending someone's sessions happens after commit.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import after_commit
from app.core.errors import Conflict, FieldError, PermissionDenied, ValidationFailed
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.people import (
    PERSON_FIELDS,
    TEXT_FIELDS,
    UUID_FIELDS,
    Problem,
    clean_text,
    full_name,
    person_problems,
)
from app.modules.identity_access.events import UserCreated, UserStatusChanged, UserUpdated
from app.modules.identity_access.infra.models import Role, User, UserRole
from app.modules.identity_access.service.directory import (
    USER_RECORD_TYPE,
    UserRepository,
    explain_user_conflict,
)
from app.modules.identity_access.service.roles import (
    grant_system_role,
    guard_last_admin,
    holds_tenant_admin,
    revoke_roles,
)
from app.modules.licensing import LimitKey, hold_limit, reserve_capacity
from app.modules.organization import (
    active_unit_ids,
    department_site,
    leave_groups,
    memberships,
    register_usage,
)
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

EndSessions = Callable[[uuid.UUID], Awaitable[None]]

# Every field problem code this module returns (errors.field.<code> labels, checked in CI by
# tests/test_error_labels.py, which reads FIELD_PROBLEMS sets).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "value_too_long",
        "email_not_valid",
        "phone_not_valid",
        "invalid_choice",
        "unknown_time_zone",
        "email_taken",
        "employee_id_taken",
        "email_required_for_sign_in",
        "site_not_found",
        "department_not_found",
        "user_not_found",
        "manager_loop",
    }
)


@dataclass(frozen=True)
class Placement:
    """Where a person sits: records they request default to it (REQ-ADM-002)."""

    site_id: uuid.UUID | None
    department_id: uuid.UUID | None


@dataclass(frozen=True)
class Reactivation:
    """What a deactivated person still holds, for the admin to confirm before reactivating."""

    role_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]


def _invalid(
    problems: Sequence[Problem],
) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(
                field=f"body.{name}",
                code=code,
                message_key=f"errors.field.{code}",
                params=dict(params),
            )
            for name, code, params in problems
        ]
    )


def _clean(values: Mapping[str, Any]) -> dict[str, Any]:
    """Only person fields; text trimmed (empty → None)."""
    unknown = sorted(set(values) - PERSON_FIELDS)
    if unknown:
        raise _invalid([(name, "read_only", {}) for name in unknown])
    cleaned: dict[str, Any] = {}
    for name, value in values.items():
        if name in TEXT_FIELDS or name == "time_zone":
            cleaned[name] = clean_text(value)
        else:
            cleaned[name] = value
    return cleaned


async def _reference_problems(
    session: AsyncSession, user_id: uuid.UUID | None, values: Mapping[str, Any]
) -> list[Problem]:
    """Unknown or inactive site / department, unknown manager, a manager loop, taken values."""
    problems: list[Problem] = []
    site_id = values.get("site_id")
    if site_id is not None and not await active_unit_ids(session, "site", [site_id]):
        problems.append(("site_id", "site_not_found", {}))
    department_id = values.get("department_id")
    if department_id is not None and not await active_unit_ids(
        session, "department", [department_id]
    ):
        problems.append(("department_id", "department_not_found", {}))
    manager_id = values.get("manager_id")
    if manager_id is not None:
        if not await _live(session, manager_id):
            problems.append(("manager_id", "user_not_found", {}))
        elif user_id is not None and await _manages(session, user_id, manager_id):
            problems.append(("manager_id", "manager_loop", {}))
    email = values.get("email")
    if email and await _taken(session, func.lower(User.email) == email.lower(), user_id):
        problems.append(("email", "email_taken", {}))
    employee_id = values.get("employee_id")
    if employee_id and await _taken(session, User.employee_id == employee_id, user_id):
        problems.append(("employee_id", "employee_id_taken", {}))
    return problems


async def _live(session: AsyncSession, user_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(User.id).where(User.id == user_id, User.deleted_at.is_(None))
    )
    return found is not None


async def _taken(session: AsyncSession, condition: Any, user_id: uuid.UUID | None) -> bool:  # noqa: ANN401 - a SQL condition
    query = select(User.id).where(condition, User.deleted_at.is_(None))
    if user_id is not None:
        query = query.where(User.id != user_id)
    return await session.scalar(query.limit(1)) is not None


async def _manages(session: AsyncSession, user_id: uuid.UUID, manager_id: uuid.UUID) -> bool:
    """Whether `user_id` is `manager_id` or above them in the chain (REQ-ADM-035 AC1)."""
    chain = (
        select(User.id, User.manager_id).where(User.id == manager_id).cte("chain", recursive=True)
    )
    chain = chain.union(select(User.id, User.manager_id).join(chain, User.id == chain.c.manager_id))
    found = await session.scalar(select(chain.c.id).where(chain.c.id == user_id).limit(1))
    return found is not None


def _with_name(current: User | None, values: dict[str, Any]) -> dict[str, Any]:
    """Keep display_name in step with first/last name unless the admin set their own."""
    if "display_name" in values:
        custom = values["display_name"]
        values["name_custom"] = custom is not None
        if custom is not None:
            return values
    first = values.get("first_name", current.first_name if current else None)
    last = values.get("last_name", current.last_name if current else None)
    custom_now = current is not None and current.name_custom and "display_name" not in values
    if first and not custom_now:
        values["display_name"] = full_name(first, last)
    return values


async def create_person(  # noqa: PLR0913 - keyword-only person settings
    session: AsyncSession,
    values: Mapping[str, Any],
    *,
    user_type: UserType = UserType.REQUESTER,
    can_sign_in: bool = True,
    source: Literal["admin", "import"] = "admin",
    now: datetime | None = None,
) -> User:
    """Add a person (REQ-ADM-002). Technicians take a seat; sign-in needs an email address."""
    now = now or datetime.now(UTC)
    clean = _clean(values)
    clean.setdefault("first_name", None)
    problems: list[Problem] = list(person_problems(clean))
    if can_sign_in and not clean.get("email"):
        problems.append(("email", "email_required_for_sign_in", {}))
    problems += await _reference_problems(session, None, clean)
    if problems:
        raise _invalid(problems)
    if user_type is UserType.TECHNICIAN:
        await hold_limit(session, LimitKey.TECHNICIANS)
        await reserve_capacity(session, LimitKey.TECHNICIANS, code="technician_limit_reached")
    clean = _with_name(None, clean)
    person = User(
        **clean,
        user_type=user_type.value,
        can_sign_in=can_sign_in,
        invited_at=now if can_sign_in else None,
        roles_mapped_at=now,  # SupportX owns this person's roles; Keycloak's are not mapped
    )
    try:
        person = await UserRepository(session).add(person)
    except IntegrityError as exc:  # a parallel add took the email or employee ID
        raise Conflict(code="user_email_conflict") from exc
    await grant_system_role(session, person.id, user_type.value)
    await record_changes(
        session,
        record_type=USER_RECORD_TYPE,
        record_id=person.id,
        version=person.version,
        kind="created",
        changes=[],
        source="import" if source == "import" else "ui",
    )
    await record_event(
        session,
        UserCreated(user_id=person.id, user_type=user_type.value, source=source),
        aggregate_id=person.id,
        aggregate_version=person.version,
    )
    return person


async def update_person(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    expected_version: int,
    changes: Mapping[str, Any],
    source: Source = "api",
) -> User:
    """Change the person record (REQ-ADM-002). A stale version gets an explained 409."""
    clean = _clean(changes)
    current = await UserRepository(session).get(user_id)
    clean = _with_name(current, clean)
    problems: list[Problem] = list(person_problems(clean))
    if "email" in clean and clean["email"] is None and current.can_sign_in:
        problems.append(("email", "email_required_for_sign_in", {}))
    # Only references that change are checked: an inactive site stays on the people it had.
    moved = {
        name: value
        for name, value in clean.items()
        if (name in UUID_FIELDS or name in {"email", "employee_id"})
        and getattr(current, name) != value
    }
    problems += await _reference_problems(session, user_id, moved)
    if problems:
        raise _invalid(problems)
    return await _save(session, current, expected_version, clean, source)


async def _save(
    session: AsyncSession,
    current: User,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> User:
    changed = sorted(name for name, value in values.items() if getattr(current, name) != value)
    if not changed:
        if current.version != expected_version:
            raise await explain_user_conflict(
                session,
                Conflict(
                    code="version_conflict",
                    params={
                        "expected_version": expected_version,
                        "current_version": current.version,
                    },
                ),
                current.id,
            )
        return current
    before = {name: getattr(current, name) for name in changed}
    try:
        updated = await UserRepository(session).update(
            current.id, expected_version=expected_version, changes={n: values[n] for n in changed}
        )
    except Conflict as error:
        raise await explain_user_conflict(session, error, current.id) from error
    except IntegrityError as exc:
        raise Conflict(code="user_email_conflict") from exc
    await record_changes(
        session,
        record_type=USER_RECORD_TYPE,
        record_id=current.id,
        version=updated.version,
        kind="updated",
        changes=[Change(name, before[name], values[name]) for name in changed],
        source=source,
    )
    await record_event(
        session,
        UserUpdated(user_id=current.id, changed_fields=changed),
        aggregate_id=current.id,
        aggregate_version=updated.version,
    )
    return updated


async def set_user_type(
    session: AsyncSession, user_id: uuid.UUID, user_type: UserType, *, expected_version: int
) -> User:
    """Make a person a technician (takes a seat, gets the technician role) or a requester.

    A requester never holds the technician role. A tenant admin stays a technician: the admin
    role is removed first (so the tenant never loses its last admin this way).
    """
    current = await UserRepository(session).get(user_id)
    if current.user_type == user_type.value:
        return await _save(session, current, expected_version, {}, "ui")
    if user_type is UserType.TECHNICIAN:
        if current.status == "active":
            await hold_limit(session, LimitKey.TECHNICIANS)
            await reserve_capacity(session, LimitKey.TECHNICIANS, code="technician_limit_reached")
        await grant_system_role(session, user_id, UserType.TECHNICIAN.value)
    else:
        if await holds_tenant_admin(session, user_id):
            raise Conflict(code="tenant_admin_is_technician")
        held = await _held(session, user_id)
        technician_roles = [role_id for key, role_id in held if key == "technician"]
        await revoke_roles(session, user_id, technician_roles)
        await grant_system_role(session, user_id, UserType.REQUESTER.value)
    return await _save(session, current, expected_version, {"user_type": user_type.value}, "ui")


async def set_sign_in(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    actor_id: uuid.UUID | None,
    user_id: uuid.UUID,
    allowed: bool,  # noqa: FBT001 - the one setting this changes
    *,
    expected_version: int,
    end_sessions: EndSessions | None = None,
) -> User:
    """Allow sign-in (needs an email address; marks the invitation) or stop it (ends sessions)."""
    current = await UserRepository(session).get(user_id)
    if allowed == current.can_sign_in:
        return await _save(session, current, expected_version, {}, "ui")
    if allowed and not current.email:
        raise _invalid([("email", "email_required_for_sign_in", {})])
    if not allowed and user_id == actor_id:
        raise PermissionDenied(code="cannot_stop_own_sign_in")
    values: dict[str, Any] = {"can_sign_in": allowed}
    if allowed:
        values["invited_at"] = datetime.now(UTC)
    updated = await _save(session, current, expected_version, values, "ui")
    if not allowed:
        _end_after_commit(session, user_id, end_sessions)
    return updated


async def deactivate(
    session: AsyncSession,
    actor_id: uuid.UUID | None,
    user_id: uuid.UUID,
    *,
    expected_version: int,
    end_sessions: EndSessions | None = None,
) -> User:
    """Deactivate (REQ-ADM-005): cannot sign in, frees the seat, keeps every record and role."""
    current = await UserRepository(session).get(user_id)
    if current.status == "disabled":
        return await _save(session, current, expected_version, {}, "ui")
    if user_id == actor_id:
        raise PermissionDenied(code="cannot_deactivate_self")
    if await holds_tenant_admin(session, user_id):
        await guard_last_admin(session, user_id)  # the last active admin is never deactivated
    updated = await _save(session, current, expected_version, {"status": "disabled"}, "ui")
    await record_event(
        session,
        UserStatusChanged(user_id=user_id, status="disabled"),
        aggregate_id=user_id,
        aggregate_version=updated.version,
    )
    _end_after_commit(session, user_id, end_sessions)
    return updated


async def reactivation(session: AsyncSession, user_id: uuid.UUID) -> Reactivation:
    """The roles and groups a person still holds, offered for confirmation on reactivation."""
    await UserRepository(session).get(user_id)
    held = await _held(session, user_id)
    groups = await memberships(session, user_id)
    return Reactivation(
        role_ids=[role_id for _key, role_id in held], group_ids=sorted(groups.group_ids)
    )


async def reactivate(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    expected_version: int,
    keep_role_ids: Sequence[uuid.UUID],
    keep_group_ids: Sequence[uuid.UUID],
) -> User:
    """Reactivate, keeping only the confirmed roles and groups (REQ-ADM-005 AC3)."""
    current = await UserRepository(session).get(user_id)
    if current.status == "active":
        return await _save(session, current, expected_version, {}, "ui")
    if current.user_type == UserType.TECHNICIAN.value:
        await hold_limit(session, LimitKey.TECHNICIANS)
        await reserve_capacity(session, LimitKey.TECHNICIANS, code="technician_limit_reached")
    held = await _held(session, user_id)
    keep_roles = set(keep_role_ids)
    await revoke_roles(
        session, user_id, [role_id for _key, role_id in held if role_id not in keep_roles]
    )
    groups = await memberships(session, user_id)
    await leave_groups(session, user_id, sorted(groups.group_ids - set(keep_group_ids)))
    # A person always keeps the system role of their type.
    await grant_system_role(session, user_id, current.user_type)
    updated = await _save(session, current, expected_version, {"status": "active"}, "ui")
    await record_event(
        session,
        UserStatusChanged(user_id=user_id, status="active"),
        aggregate_id=user_id,
        aggregate_version=updated.version,
    )
    return updated


async def _held(session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str | None, uuid.UUID]]:
    rows = await session.execute(
        select(Role.key, UserRole.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
    )
    return [(row.key, row.role_id) for row in rows]


def _end_after_commit(
    session: AsyncSession, user_id: uuid.UUID, end_sessions: EndSessions | None
) -> None:
    """Sessions end once the change is committed. Backstop: sign-in refuses the person."""
    if end_sessions is None:
        return

    async def end() -> None:
        await end_sessions(user_id)

    after_commit(session, end)


async def person_placement(session: AsyncSession, user_id: uuid.UUID | None) -> Placement:
    """The person's site and department (a record they request takes them as defaults).

    The department's site is used when the person has a department but no site of their own.
    """
    if user_id is None:
        return Placement(None, None)
    row = (
        await session.execute(select(User.site_id, User.department_id).where(User.id == user_id))
    ).one_or_none()
    if row is None:
        return Placement(None, None)
    site_id = row.site_id
    if site_id is None and row.department_id is not None:
        site_id = await department_site(session, row.department_id)
    return Placement(site_id, row.department_id)


async def _people_using(column: Any, session: AsyncSession, unit_id: uuid.UUID) -> int:  # noqa: ANN401 - a User column
    count = await session.scalar(
        select(func.count()).select_from(User).where(column == unit_id, User.deleted_at.is_(None))
    )
    return int(count or 0)


async def _people_at_site(session: AsyncSession, unit_id: uuid.UUID) -> int:
    return await _people_using(User.site_id, session, unit_id)


async def _people_in_department(session: AsyncSession, unit_id: uuid.UUID) -> int:
    return await _people_using(User.department_id, session, unit_id)


def register_people_usage() -> None:
    """A site or department people sit at cannot be removed (organization asks here)."""
    register_usage("site", "people", _people_at_site)
    register_usage("department", "people", _people_in_department)
