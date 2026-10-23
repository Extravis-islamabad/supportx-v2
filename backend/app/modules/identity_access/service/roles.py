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
from collections.abc import Sequence
from dataclasses import dataclass
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
from app.modules.identity_access.events import RoleChanged, UserRoleChanged
from app.modules.identity_access.infra.models import Role, RolePermission, User, UserRole
from app.modules.identity_access.service.policy import PolicyService, ResourceType
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


def _tenant(session: AsyncSession) -> uuid.UUID:
    context: TenantContext = session.info[SESSION_TENANT_KEY]
    return context.tenant_id


def _refresh(session: AsyncSession, policy: PolicyService) -> None:
    """Compiled permissions of the tenant go stale once this transaction commits."""
    del policy  # registered as the process's access invalidator at startup
    access_changed(session)


async def ensure_system_roles(session: AsyncSession) -> dict[str, uuid.UUID]:
    """Create the tenant's three system roles if missing; returns key → role ID."""
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


async def get_role(session: AsyncSession, catalogue: Catalogue, role_id: uuid.UUID) -> RoleDetail:
    """One role with its permission matrix."""
    role = await RoleRepository(session).get(role_id)
    return await _detail(session, catalogue, role)


async def _detail(session: AsyncSession, catalogue: Catalogue, role: Role) -> RoleDetail:
    if role.is_system:
        grants = [PermissionGrant(p, s) for p, s in catalogue.system_grants(role.key)]
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
    return RoleDetail(role, grants, int(count or 0))


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
        raise PermissionDenied(code="system_role_immutable")
    return role


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

    Returns how many users were moved. 409 `role_in_use` (params: users) without a replacement.
    """
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
        admins = await session.scalar(
            select(func.count())
            .select_from(UserRole)
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role_id == role_id, User.status == "active", User.deleted_at.is_(None))
        )
        holds = await session.scalar(
            select(UserRole.user_id).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        )
        if holds is not None and int(admins or 0) <= 1:
            raise Conflict(code="last_tenant_admin")
    removed = await _remove(session, user_id, role_id)
    _refresh(session, policy)
    return removed


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
