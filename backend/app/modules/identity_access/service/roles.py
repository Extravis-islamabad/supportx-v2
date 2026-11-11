"""Roles, role permissions and role assignments (architecture.md §11.2; WP-016; D-029).

Rules enforced here (the routes only check the coarse permission):
- system roles (tenant_admin, technician, requester) can be neither edited nor deleted;
- nobody can grant a permission or scope they do not hold themselves (tenant admins excepted),
  neither by building a role nor by assigning one; only tenant admins assign or remove the
  tenant admin role;
- the last active tenant admin can never lose the role (serialised by an advisory lock);
- deleting a role in use needs a replacement role: access is moved, never silently dropped.
Every change writes its event in the same transaction and refreshes compiled permissions.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Scope, access_changed
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import (
    AppError,
    Conflict,
    FieldError,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.modules.identity_access.domain.permissions import SYSTEM_ROLES, TENANT_ADMIN, Catalogue
from app.modules.identity_access.domain.policy import Subject, can_delegate
from app.modules.identity_access.events import GroupRoleChanged, RoleChanged, UserRoleChanged
from app.modules.identity_access.infra.models import (
    GroupRole,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.modules.identity_access.service.access_settings import tenant_technician_scope
from app.modules.identity_access.service.policy import PolicyService, ResourceType
from app.modules.organization import active_groups, users_in_groups
from app.shared.api.filters import compile_filter
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.ids import new_id

if TYPE_CHECKING:
    from app.core.tenancy import TenantContext

MAX_PERMISSIONS = 300


class RoleRepository(Repository[Role]):
    """Roles of the session's tenant."""

    model = Role


@dataclass(frozen=True)
class PermissionGrant:
    """One row of a role's permission matrix."""

    permission: str
    scope: Scope
    condition: dict[str, Any] | None = None


@dataclass(frozen=True)
class RoleDetail:
    """A role with its permissions (system roles: from the catalogue) and assignee count."""

    role: Role
    grants: list[PermissionGrant]
    user_count: int
    # Support groups carrying the role (WP-042): their members hold it too.
    group_ids: list[uuid.UUID] = field(default_factory=list)


def _tenant(session: AsyncSession) -> uuid.UUID:
    context: TenantContext = session.info[SESSION_TENANT_KEY]
    return context.tenant_id


def _refresh(session: AsyncSession, policy: PolicyService) -> None:
    """Compiled permissions of the tenant go stale once this transaction commits."""
    del policy  # registered as the process's access invalidator at startup
    access_changed(session)


async def ensure_system_roles(session: AsyncSession) -> dict[str, uuid.UUID]:
    """Create the tenant's system roles if missing; returns key → role ID."""
    tenant_id = _tenant(session)
    for key in SYSTEM_ROLES:
        await session.execute(
            insert(Role)
            .values(id=new_id(), tenant_id=tenant_id, key=key, name=key, is_system=True, version=1)
            .on_conflict_do_nothing(
                index_elements=[Role.tenant_id, Role.key], index_where=Role.deleted_at.is_(None)
            )
        )
    rows = await session.execute(
        select(Role.key, Role.id).where(Role.is_system, Role.deleted_at.is_(None))
    )
    return {row.key: row.id for row in rows}


async def list_roles(session: AsyncSession) -> list[tuple[Role, int]]:
    """Every role of the tenant with how many users hold it (system roles first)."""
    await ensure_system_roles(session)
    counts = (
        select(UserRole.role_id, func.count().label("users")).group_by(UserRole.role_id).subquery()
    )
    rows = await session.execute(
        select(Role, func.coalesce(counts.c.users, 0))
        .outerjoin(counts, counts.c.role_id == Role.id)
        .where(Role.deleted_at.is_(None))
        .order_by(Role.is_system.desc(), Role.name)
    )
    return [(row[0], int(row[1])) for row in rows]


@dataclass(frozen=True)
class RoleName:
    """A role as other modules name it: system roles by their key (labelled), others by name."""

    key: str
    name: str
    system: bool


async def role_names(session: AsyncSession, keys: Sequence[str]) -> list[RoleName]:
    """Roles of the tenant with these keys, in the given order (unknown keys left out)."""
    if not keys:
        return []
    rows = await session.scalars(
        select(Role).where(Role.key.in_(list(keys)), Role.deleted_at.is_(None))
    )
    found = {row.key: RoleName(row.key, row.name, row.is_system) for row in rows}
    return [found[key] for key in keys if key in found]


async def get_role(session: AsyncSession, catalogue: Catalogue, role_id: uuid.UUID) -> RoleDetail:
    """One role with its permission matrix."""
    role = await RoleRepository(session).get(role_id)
    return await _detail(session, catalogue, role)


async def _detail(session: AsyncSession, catalogue: Catalogue, role: Role) -> RoleDetail:
    if role.is_system:
        scope = await tenant_technician_scope(session)  # the role editor shows what applies
        grants = [
            PermissionGrant(p, s)
            for p, s in catalogue.system_grants(role.key, technician_scope=scope)
        ]
    else:
        rows = await session.scalars(
            select(RolePermission)
            .where(RolePermission.role_id == role.id)
            .order_by(RolePermission.permission)
        )
        grants = [PermissionGrant(r.permission, r.scope, r.condition) for r in rows]  # type: ignore[arg-type]  # CHECK constraint: a valid scope code
    count = await session.scalar(
        select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
    )
    return RoleDetail(role, grants, int(count or 0), await groups_of_role(session, role.id))


def _validate_grants(
    grants: Sequence[PermissionGrant],
    *,
    subject: Subject,
    policy: PolicyService,
    resources: dict[str, ResourceType],
) -> list[PermissionGrant]:
    """Known permissions, allowed scopes, compilable conditions, no escalation, no duplicates."""
    errors: list[FieldError] = []
    seen: set[str] = set()
    if len(grants) > MAX_PERMISSIONS:
        raise ValidationFailed(params={"max": MAX_PERMISSIONS})
    for index, grant in enumerate(grants):
        path = f"body.permissions.{index}"
        spec = policy.catalogue.get(grant.permission)
        if spec is None:
            errors.append(
                FieldError(
                    field=f"{path}.permission",
                    code="unknown_permission",
                    message_key="errors.field.unknown_permission",
                )
            )
            continue
        if grant.permission in seen:
            errors.append(
                FieldError(
                    field=f"{path}.permission",
                    code="duplicate_permission",
                    message_key="errors.field.duplicate_permission",
                )
            )
            continue
        seen.add(grant.permission)
        if grant.scope not in spec.scopes:
            errors.append(
                FieldError(
                    field=f"{path}.scope",
                    code="scope_not_allowed",
                    message_key="errors.field.scope_not_allowed",
                )
            )
            continue
        problems = _condition_problems(grant, spec.module, resources, path)
        if problems:
            errors.extend(problems)
            continue
        if not can_delegate(subject, grant.permission, grant.scope, grant.condition):
            raise PermissionDenied(
                code="privilege_escalation",
                params={"permission": grant.permission, "scope": grant.scope},
            )
    if errors:
        raise ValidationFailed(errors=errors)
    return list(grants)


def _condition_problems(
    grant: PermissionGrant, module: str, resources: dict[str, ResourceType], path: str
) -> list[FieldError]:
    """Field errors of an attribute condition (none if it has none or it compiles)."""
    if grant.condition is None:
        return []
    resource = resources.get(module)
    if resource is None:
        return [
            FieldError(
                field=f"{path}.condition",
                code="condition_not_supported",
                message_key="errors.field.condition_not_supported",
            )
        ]
    try:
        compile_filter(
            grant.condition, resource.fields, now=datetime.now(UTC), path=f"{path}.condition"
        )
    except AppError as exc:
        return list(exc.errors) or [
            FieldError(
                field=f"{path}.condition",
                code="invalid_value",
                message_key="errors.field.invalid_value",
            )
        ]
    return []


def _clean_name(name: str) -> str:
    value = name.strip()
    if not 1 <= len(value) <= 200:  # noqa: PLR2004 - CHECK constraint bound
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.name",
                    code="invalid_value",
                    message_key="errors.field.invalid_value",
                )
            ]
        )
    return value


async def create_role(  # noqa: PLR0913 - keyword-only role fields
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    *,
    name: str,
    description: str | None,
    grants: Sequence[PermissionGrant],
    resources: dict[str, ResourceType],
) -> RoleDetail:
    """A new custom role."""
    clean = _validate_grants(grants, subject=subject, policy=policy, resources=resources)
    role = Role(
        key=f"custom_{uuid.uuid4().hex[:12]}",
        name=_clean_name(name),
        description=description,
        is_system=False,
    )
    await RoleRepository(session).add(role)
    await _write_grants(session, role.id, clean)
    await record_event(
        session,
        RoleChanged(
            role_id=role.id, change="created", changed_fields=["name", "description", "permissions"]
        ),
        aggregate_id=role.id,
        aggregate_version=role.version,
    )
    _refresh(session, policy)
    return RoleDetail(role, clean, 0)


async def _write_grants(
    session: AsyncSession, role_id: uuid.UUID, grants: Sequence[PermissionGrant]
) -> None:
    tenant_id = _tenant(session)
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    if grants:
        await session.execute(
            insert(RolePermission),
            [
                {
                    "tenant_id": tenant_id,
                    "role_id": role_id,
                    "permission": g.permission,
                    "scope": g.scope,
                    "condition": g.condition,
                }
                for g in grants
            ],
        )


async def _custom_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await RoleRepository(session).get(role_id)
    if role.is_system:
        # The request conflicts with what the role is (built-in), not with the caller's rights:
        # 409, so a client copies it instead (REQ-ADM-017; a recorded D-095 change, WP-042).
        raise Conflict(code="system_role_immutable")
    return role


# --- service identities (WP-048b; lane B's conditions) -------------------------------------------

# Roles a service identity (a connector's, a workflow's run-as) may never hold, by any path:
# tenant administration (it would count as "another admin", so a person could remove the last
# real one) and these rights, which change who may do what.
SERVICE_NEVER = frozenset(
    {"identity.manage", "roles.manage", "users.manage", "users.preview", "api_keys.manage"}
)


def _forbidden_for_service(role: Role, permissions: set[str]) -> bool:
    return role.key == TENANT_ADMIN or bool(permissions & SERVICE_NEVER)


async def _service_members(session: AsyncSession, user_ids: Sequence[uuid.UUID]) -> bool:
    if not user_ids:
        return False
    found = await session.scalar(
        select(User.id).where(User.id.in_(user_ids), User.user_type == "service").limit(1)
    )
    return found is not None


async def _service_holds(session: AsyncSession, role_id: uuid.UUID) -> bool:
    """A service identity holds the role, directly or through a group that carries it."""
    direct = list(
        await session.scalars(select(UserRole.user_id).where(UserRole.role_id == role_id))
    )
    groups = frozenset(
        await session.scalars(select(GroupRole.group_id).where(GroupRole.role_id == role_id))
    )
    members = list(await session.scalars(users_in_groups(groups))) if groups else []
    return await _service_members(session, [*direct, *members])


def _refuse_for_service() -> PermissionDenied:
    return PermissionDenied(code="service_identity_role_not_allowed")


async def role_allowed_for_service(
    session: AsyncSession, catalogue: Catalogue, role_id: uuid.UUID
) -> None:
    """Refuse a role a service identity may never hold."""
    role = await RoleRepository(session).get(role_id)
    detail = await _detail(session, catalogue, role)
    if _forbidden_for_service(role, {g.permission for g in detail.grants}):
        raise _refuse_for_service()


@dataclass(frozen=True)
class ServiceRole:
    """A role as a service identity's screen shows it: system roles by their key (labelled)."""

    id: uuid.UUID
    key: str
    name: str
    system: bool


def _service_role(role: Role) -> ServiceRole:
    return ServiceRole(role.id, role.key, role.name, role.is_system)


async def roles_for_service(
    session: AsyncSession, policy: PolicyService, subject: Subject | None = None
) -> list[ServiceRole]:
    """Every role a service identity may hold, by the rule `role_allowed_for_service` applies.

    Never tenant administration, nor a role that manages identities, roles or API keys or
    previews people; given `subject`, never a role beyond that admin's own rights either (lane
    B's #416 review), so a picker never offers what a save would refuse.
    """
    allowed = []
    for role, _users in await list_roles(session):
        detail = await _detail(session, policy.catalogue, role)
        if _forbidden_for_service(role, {g.permission for g in detail.grants}):
            continue
        if subject is not None:  # only what this admin may hand out, as a save checks
            try:
                await _assignable(session, policy, subject, role.id)
            except PermissionDenied:
                continue
        allowed.append(_service_role(role))
    return allowed


async def roles_held(session: AsyncSession, user_id: uuid.UUID) -> list[ServiceRole]:
    """The roles given to one user directly (a service identity has no groups), by name."""
    rows = await session.scalars(
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, Role.deleted_at.is_(None))
        .order_by(Role.is_system.desc(), Role.name)
    )
    return [_service_role(r) for r in rows]


async def update_role(  # noqa: PLR0913 - keyword-only role fields
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    role_id: uuid.UUID,
    *,
    expected_version: int,
    name: str | None,
    description: str | None,
    grants: Sequence[PermissionGrant] | None,
    resources: dict[str, ResourceType],
) -> RoleDetail:
    """Edit a custom role (If-Match). A non-admin may only edit roles they could build."""
    role = await _custom_role(session, role_id)
    current = await _detail(session, policy.catalogue, role)
    # Editing a role that already holds more than the editor would be a back door: refused.
    _validate_grants(current.grants, subject=subject, policy=policy, resources=resources)
    changes: dict[str, Any] = {}
    if name is not None:
        changes["name"] = _clean_name(name)
    if description is not None:
        changes["description"] = description
    changed = sorted(changes)
    if grants is not None:
        clean = _validate_grants(grants, subject=subject, policy=policy, resources=resources)
        changed.append("permissions")
        # A role a service identity holds never gains a right it may not have (lane B, 048b).
        if _forbidden_for_service(role, {g.permission for g in clean}) and await _service_holds(
            session, role_id
        ):
            raise _refuse_for_service()
    role = await RoleRepository(session).update(
        role_id, expected_version=expected_version, changes=changes
    )
    if grants is not None:
        await _write_grants(session, role_id, clean)
    await record_event(
        session,
        RoleChanged(role_id=role_id, change="updated", changed_fields=changed),
        aggregate_id=role_id,
        aggregate_version=role.version,
    )
    _refresh(session, policy)
    return await _detail(session, policy.catalogue, role)


async def delete_role(  # noqa: PLR0913 - keyword-only options
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    role_id: uuid.UUID,
    *,
    expected_version: int,
    reassign_to: uuid.UUID | None,
    resources: dict[str, ResourceType],
) -> int:
    """Delete a custom role; its holders move to `reassign_to` (required if it has any).

    Returns how many users were moved. 409 `role_in_use` (params: users) without a replacement;
    409 `system_role_not_deletable` for a built-in role (D-153: copy it instead).
    """
    if (await RoleRepository(session).get(role_id)).is_system:
        raise Conflict(code="system_role_not_deletable")
    role = await _custom_role(session, role_id)
    detail = await _detail(session, policy.catalogue, role)
    _validate_grants(detail.grants, subject=subject, policy=policy, resources=resources)
    holders = list(
        await session.scalars(select(UserRole.user_id).where(UserRole.role_id == role_id))
    )
    if holders and reassign_to is None:
        raise Conflict(code="role_in_use", params={"users": len(holders)})
    if holders and reassign_to is not None:
        if reassign_to == role_id:
            raise ValidationFailed(params={"field": "reassign_to"})
        await _assignable(session, policy, subject, reassign_to)
        for user_id in holders:
            await _assign(session, user_id, reassign_to)
            await _remove(session, user_id, role_id)
    await RoleRepository(session).soft_delete(role_id, expected_version=expected_version)
    await record_event(
        session,
        RoleChanged(role_id=role_id, change="deleted", changed_fields=[]),
        aggregate_id=role_id,
    )
    _refresh(session, policy)
    return len(holders)


async def _assignable(
    session: AsyncSession, policy: PolicyService, subject: Subject, role_id: uuid.UUID
) -> Role:
    """The role, if `subject` may hand it out (or take it away)."""
    role = await RoleRepository(session).get(role_id)
    if role.key == TENANT_ADMIN:
        if not subject.is_tenant_admin:
            raise PermissionDenied(code="privilege_escalation", params={"role": TENANT_ADMIN})
        return role
    detail = await _detail(session, policy.catalogue, role)
    for grant in detail.grants:
        if policy.catalogue.get(grant.permission) is None:
            continue
        if not can_delegate(subject, grant.permission, grant.scope, grant.condition):
            raise PermissionDenied(
                code="privilege_escalation",
                params={"permission": grant.permission, "scope": grant.scope},
            )
    return role


async def _assign(session: AsyncSession, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
    context = session.info[SESSION_TENANT_KEY]
    try:
        result = await session.execute(
            insert(UserRole)
            .values(
                tenant_id=context.tenant_id,
                user_id=user_id,
                role_id=role_id,
                created_by=context.user_id,
            )
            .on_conflict_do_nothing()
            .returning(UserRole.role_id)
        )
    except IntegrityError as exc:  # same-tenant FK: no such user here
        raise NotFound(code="user_not_found") from exc
    added = result.first() is not None
    if added:
        await record_event(
            session,
            UserRoleChanged(user_id=user_id, role_id=role_id, change="assigned"),
            aggregate_id=user_id,
        )
    return added


async def _remove(session: AsyncSession, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
    result = await session.execute(
        delete(UserRole)
        .where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        .returning(UserRole.role_id)
    )
    removed = result.first() is not None
    if removed:
        await record_event(
            session,
            UserRoleChanged(user_id=user_id, role_id=role_id, change="removed"),
            aggregate_id=user_id,
        )
    return removed


async def assign_role(
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> bool:
    """Give `user_id` the role (idempotent). No escalation, also not for oneself."""
    await _assignable(session, policy, subject, role_id)
    if await session.scalar(select(User.id).where(User.id == user_id)) is None:
        raise NotFound(code="user_not_found")
    added = await _assign(session, user_id, role_id)
    _refresh(session, policy)
    return added


async def remove_role(
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> bool:
    """Take the role away (idempotent). The last tenant admin keeps theirs."""
    role = await _assignable(session, policy, subject, role_id)
    if role.key == TENANT_ADMIN:
        # Two admins removing each other at once must not leave the tenant without one.
        lock = func.hashtextextended(f"authz:{_tenant(session)}:admins", 0)
        await session.execute(select(func.pg_advisory_xact_lock(lock)))
        # Admins through groups count too (WP-042); the person may stay admin through one.
        if not await _tenant_admin_holders(session, without_direct=user_id):
            raise Conflict(code="last_tenant_admin")
    removed = await _remove(session, user_id, role_id)
    _refresh(session, policy)
    return removed


async def _tenant_admin_holders(
    session: AsyncSession,
    *,
    without_group: uuid.UUID | None = None,
    without_direct: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    """Active people holding tenant admin, directly or through an active group (WP-042).

    `without_group` / `without_direct`: as if that group's link, or that person's own role, were
    already gone (the change being checked).
    """
    role_id = (await ensure_system_roles(session))[TENANT_ADMIN]
    direct = set(
        await session.scalars(
            select(UserRole.user_id)
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role_id == role_id, User.status == "active", User.deleted_at.is_(None))
        )
    )
    if without_direct is not None:
        direct.discard(without_direct)
    carrying = {
        group
        for group in await session.scalars(
            select(GroupRole.group_id).where(GroupRole.role_id == role_id)
        )
        if group != without_group
    }
    active = await active_groups(session, frozenset(carrying))
    through: set[uuid.UUID] = set()
    if active:
        through = set(
            await session.scalars(
                select(User.id).where(
                    User.id.in_(users_in_groups(active)),
                    User.status == "active",
                    User.deleted_at.is_(None),
                )
            )
        )
    return direct | through


async def add_group_role(
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    group_id: uuid.UUID,
    role_id: uuid.UUID,
) -> bool:
    """A support group carries the role: its members hold it (idempotent; no escalation)."""
    await _assignable(session, policy, subject, role_id)
    # Its service identity members would hold it too (lane B, WP-048b).
    role = await RoleRepository(session).get(role_id)
    detail = await _detail(session, policy.catalogue, role)
    if _forbidden_for_service(
        role, {g.permission for g in detail.grants}
    ) and await _service_members(
        session, list(await session.scalars(users_in_groups(frozenset({group_id}))))
    ):
        raise _refuse_for_service()
    if group_id not in await active_groups(session, frozenset({group_id})):
        raise NotFound(code="group_not_found")
    context = session.info[SESSION_TENANT_KEY]
    result = await session.execute(
        insert(GroupRole)
        .values(
            tenant_id=context.tenant_id,
            group_id=group_id,
            role_id=role_id,
            created_by=context.user_id,
        )
        .on_conflict_do_nothing()
        .returning(GroupRole.role_id)
    )
    added = result.first() is not None
    if added:
        await record_event(
            session,
            GroupRoleChanged(group_id=group_id, role_id=role_id, change="added"),
            aggregate_id=group_id,
        )
        _refresh(session, policy)
    return added


async def remove_group_role(
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    group_id: uuid.UUID,
    role_id: uuid.UUID,
) -> bool:
    """The group no longer carries the role. The tenant never loses its last admin this way."""
    role = await _assignable(session, policy, subject, role_id)
    if role.key == TENANT_ADMIN:
        lock = func.hashtextextended(f"authz:{_tenant(session)}:admins", 0)
        await session.execute(select(func.pg_advisory_xact_lock(lock)))
        if not await _tenant_admin_holders(session, without_group=group_id):
            raise Conflict(code="last_tenant_admin")
    result = await session.execute(
        delete(GroupRole)
        .where(GroupRole.group_id == group_id, GroupRole.role_id == role_id)
        .returning(GroupRole.role_id)
    )
    removed = result.first() is not None
    if removed:
        await record_event(
            session,
            GroupRoleChanged(group_id=group_id, role_id=role_id, change="removed"),
            aggregate_id=group_id,
        )
        _refresh(session, policy)
    return removed


# The running policy service (set at start-up): the catalogue the grantable check reads.
_POLICY: list[PolicyService] = []


def use_policy(policy: PolicyService | None) -> None:
    """At start-up (and None at shutdown)."""
    _POLICY.clear()
    if policy is not None:
        _POLICY.append(policy)


async def check_group_grantable(
    session: AsyncSession, subject: Subject, group_id: uuid.UUID
) -> None:
    """403 privilege_escalation unless `subject` could give every role the group carries.

    For anything that adds people to a group outside a person's own action, checked when it is
    set up: a directory mapping a directory group onto a SupportX group (lane B, WP-042).
    """
    if not _POLICY:
        msg = "check_group_grantable before the policy service started"
        raise RuntimeError(msg)
    carried = await session.scalars(select(GroupRole.role_id).where(GroupRole.group_id == group_id))
    for role_id in list(carried):
        await _assignable(session, _POLICY[0], subject, role_id)


def member_guard(
    policy: PolicyService,
) -> Callable[[AsyncSession, object, uuid.UUID, uuid.UUID], Awaitable[None]]:
    """The check organization runs before a person adds a member to a group (WP-042, lane B).

    A group that carries roles hands them out with each new member, so the person adding needs
    every one of them as if assigning it directly (`_assignable`); else 403 privilege_escalation.
    """

    async def guard(
        session: AsyncSession, by: object, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        if not isinstance(by, Subject):
            raise TypeError(by)
        carried = list(
            await session.scalars(select(GroupRole.role_id).where(GroupRole.group_id == group_id))
        )
        service = await _service_members(session, [user_id])
        for role_id in carried:
            await _assignable(session, policy, by, role_id)
            if service:  # a service identity never gets a forbidden role through a group
                await role_allowed_for_service(session, policy.catalogue, role_id)

    return guard


async def guard_group_disable(session: AsyncSession, group_id: uuid.UUID) -> None:
    """409 `last_tenant_admin` if disabling this group would leave the tenant without an admin."""
    role_id = (await ensure_system_roles(session))[TENANT_ADMIN]
    carries = await session.scalar(
        select(GroupRole.role_id).where(
            GroupRole.group_id == group_id, GroupRole.role_id == role_id
        )
    )
    if carries is None:
        return
    lock = func.hashtextextended(f"authz:{_tenant(session)}:admins", 0)
    await session.execute(select(func.pg_advisory_xact_lock(lock)))
    if not await _tenant_admin_holders(session, without_group=group_id):
        raise Conflict(code="last_tenant_admin")


async def roles_through_groups(
    session: AsyncSession, group_ids: frozenset[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(role, group) pairs a person holds through their active groups (the Access drawer)."""
    active = await active_groups(session, group_ids)
    if not active:
        return []
    rows = await session.execute(
        select(GroupRole.role_id, GroupRole.group_id)
        .where(GroupRole.group_id.in_(active))
        .order_by(GroupRole.role_id, GroupRole.group_id)
    )
    return [(row.role_id, row.group_id) for row in rows]


async def groups_of_role(session: AsyncSession, role_id: uuid.UUID) -> list[uuid.UUID]:
    """The support groups carrying the role (the role editor lists them)."""
    found = await session.scalars(
        select(GroupRole.group_id).where(GroupRole.role_id == role_id).order_by(GroupRole.group_id)
    )
    return list(found)


async def grant_system_role(session: AsyncSession, user_id: uuid.UUID, key: str) -> bool:
    """Give a person a system role in a person change (WP-021; the caller checked rights)."""
    ids = await ensure_system_roles(session)
    added = await _assign(session, user_id, ids[key])
    access_changed(session)
    return added


async def revoke_roles(
    session: AsyncSession, user_id: uuid.UUID, role_ids: Sequence[uuid.UUID]
) -> None:
    """Take roles away as part of a person change (WP-021); the last tenant admin keeps theirs."""
    ids = await ensure_system_roles(session)
    if ids[TENANT_ADMIN] in role_ids:
        await guard_last_admin(session, user_id)
    for role_id in role_ids:
        await _remove(session, user_id, role_id)
    access_changed(session)


async def guard_last_admin(session: AsyncSession, user_id: uuid.UUID) -> None:
    """409 `last_tenant_admin` if `user_id` is the only active tenant admin."""
    # Two admins removing each other at once must not leave the tenant without one.
    lock = func.hashtextextended(f"authz:{_tenant(session)}:admins", 0)
    await session.execute(select(func.pg_advisory_xact_lock(lock)))
    holders = await _tenant_admin_holders(session)  # directly or through groups (WP-042)
    if user_id in holders and not holders - {user_id}:
        raise Conflict(code="last_tenant_admin")


async def holds_tenant_admin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the person holds the tenant admin role."""
    role_id = (await ensure_system_roles(session))[TENANT_ADMIN]
    found = await session.scalar(
        select(UserRole.user_id).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
    )
    return found is not None


async def user_role_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Role IDs held by a user."""
    return list(await session.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id)))


def keycloak_role_keys(identity_roles: Sequence[str]) -> list[str]:
    """The one-time mapping (D-029): Keycloak realm roles → SupportX system roles."""
    keys = [key for key in (TENANT_ADMIN, "technician") if key in identity_roles]
    return keys or ["requester"]


async def map_identity_roles(
    session: AsyncSession, user_id: uuid.UUID, identity_roles: Sequence[str], now: datetime
) -> list[str]:
    """First login after WP-016: assign the mapped system roles once, then mark the user."""
    mapped = await session.scalar(select(User.roles_mapped_at).where(User.id == user_id))
    if mapped is not None:
        return []
    ids = await ensure_system_roles(session)
    keys = keycloak_role_keys(identity_roles)
    for key in keys:
        await _assign(session, user_id, ids[key])
    await session.execute(update(User).where(User.id == user_id).values(roles_mapped_at=now))
    return keys
