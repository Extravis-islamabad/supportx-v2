"""Access administration API: permission catalogue, roles, role assignments (WP-016).

Coarse permissions are checked here (`roles.view`, `roles.manage`, `users.view`,
`users.manage`); the protections (system roles, last admin, no privilege escalation, roles in
use) are enforced in service/roles.py.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import Scope, require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail, ServiceUnavailable
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.service import roles as role_service
from app.modules.identity_access.service.policy import PolicyService
from app.modules.organization import memberships
from app.shared.api.concurrency import ExpectedVersion, not_modified, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

POLICY_STATE = "policy"

router = APIRouter(
    tags=["access"],
    dependencies=[Depends(rate_limit("access"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or privilege escalation."},
        404: {"model": ProblemDetail, "description": "No such role or user."},
        409: {
            "model": ProblemDetail,
            "description": "Stale If-Match, role in use, last tenant admin.",
        },
        422: {"model": ProblemDetail, "description": "Invalid permissions, scopes or conditions."},
    },
)

ViewRoles = Annotated[Subject, Depends(require_permission("roles.view"))]
ManageRoles = Annotated[Subject, Depends(require_permission("roles.manage"))]
ViewUsers = Annotated[Subject, Depends(require_permission("users.view"))]
ManageUsers = Annotated[Subject, Depends(require_permission("users.manage"))]


def get_policy(request: Request) -> PolicyService:
    """The running policy service."""
    policy: PolicyService | None = getattr(request.app.state, POLICY_STATE, None)
    if policy is None:
        raise ServiceUnavailable(code="authorization_unavailable")
    return policy


Policy = Annotated[PolicyService, Depends(get_policy)]


class PermissionOut(BaseModel):
    """A catalogue permission. Labels: `permission.<key>` and `permission.<key>.description`."""

    key: str
    module: str
    feature: str | None
    scopes: list[Scope] = Field(description="Scopes a role may grant it with, broadest first.")
    entitled: bool = Field(description="False: the tenant's plan lacks the feature (locked).")
    conditions_supported: bool = Field(description="Attribute rules can be attached.")


class GrantIO(BaseModel):
    """One permission of a role."""

    permission: str = Field(max_length=100)
    scope: Scope
    condition: dict[str, Any] | None = Field(
        default=None, description="Optional attribute rule (filter DSL, FilterExpression)."
    )


class RoleSummary(BaseModel):
    """A role in the list. System roles render their name via `role.<key>` labels."""

    id: uuid.UUID
    key: str
    name: str
    description: str | None
    is_system: bool
    user_count: int
    version: int


class RoleDetailOut(RoleSummary):
    """A role with its permission matrix."""

    permissions: list[GrantIO]


class RoleCreate(BaseModel):
    """A new custom role."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[GrantIO] = Field(default_factory=list, max_length=300)


class RolePatch(BaseModel):
    """Changes to a custom role; `permissions` replaces the whole matrix when given."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[GrantIO] | None = Field(default=None, max_length=300)


class UserAccessOut(BaseModel):
    """Roles, sites and support groups of a user."""

    user_id: uuid.UUID
    role_ids: list[uuid.UUID]
    site_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]


def _grants(items: list[GrantIO]) -> list[role_service.PermissionGrant]:
    return [role_service.PermissionGrant(g.permission, g.scope, g.condition) for g in items]


def _detail(detail: role_service.RoleDetail) -> RoleDetailOut:
    role = detail.role
    return RoleDetailOut(
        id=role.id,
        key=role.key,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        user_count=detail.user_count,
        version=role.version,
        permissions=[
            GrantIO(permission=g.permission, scope=g.scope, condition=g.condition)
            for g in detail.grants
        ],
    )


@router.get("/permissions", summary="Permission catalogue")
async def list_permissions(subject: ViewRoles, policy: Policy) -> list[PermissionOut]:
    """Every permission, with whether the tenant's plan includes it."""
    features = await policy.entitled_features(subject.tenant_id, None)
    return [
        PermissionOut(
            key=spec.key,
            module=spec.module,
            feature=spec.feature,
            scopes=list(spec.scopes),
            entitled=spec.feature is None or spec.feature in features,
            conditions_supported=spec.module in policy.resources,
        )
        for spec in policy.catalogue.permissions.values()
    ]


@router.get("/roles", summary="List roles")
async def list_roles(session: TenantSession, subject: ViewRoles) -> list[RoleSummary]:
    """System roles first, then custom roles by name, with how many users hold each."""
    del subject
    return [
        RoleSummary(
            id=role.id,
            key=role.key,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            user_count=count,
            version=role.version,
        )
        for role, count in await role_service.list_roles(session)
    ]


@router.get("/roles/{role_id}", summary="Get a role")
async def get_role(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    role_id: uuid.UUID,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: ViewRoles,
    policy: Policy,
) -> RoleDetailOut:
    """One role with its permission matrix and ETag."""
    del subject
    detail = await role_service.get_role(session, policy.catalogue, role_id)
    cached = not_modified(request, detail.role.version)
    if cached is not None:
        return cached  # type: ignore[return-value]  # 304 without a body
    set_etag(response, detail.role.version)
    return _detail(detail)


@router.post(
    "/roles",
    summary="Create a custom role",
    status_code=status.HTTP_201_CREATED,
    response_model=RoleDetailOut,
    responses={201: {"model": RoleDetailOut, "description": "Created (or replayed)."}},
)
async def create_role(
    body: RoleCreate,
    session: TenantSession,
    subject: ManageRoles,
    policy: Policy,
    idempotency: Idempotency,
) -> Response:
    """Create a role (Idempotency-Key supported). No permission beyond your own (unless admin)."""

    async def operation() -> Created:
        detail = await role_service.create_role(
            session,
            policy,
            subject,
            name=body.name,
            description=body.description,
            grants=_grants(body.permissions),
            resources=dict(policy.resources),
        )
        out = _detail(detail)
        return Created(out, {"ETag": f'"{out.version}"', "Location": f"/api/v1/roles/{out.id}"})

    return await idempotency.run(body, operation)


@router.patch("/roles/{role_id}", summary="Edit a custom role")
async def update_role(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    role_id: uuid.UUID,
    body: RolePatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: ManageRoles,
    policy: Policy,
) -> RoleDetailOut:
    """Edit name, description and/or the permission matrix (If-Match). System roles: 403."""
    detail = await role_service.update_role(
        session,
        policy,
        subject,
        role_id,
        expected_version=version,
        name=body.name,
        description=body.description,
        grants=None if body.permissions is None else _grants(body.permissions),
        resources=dict(policy.resources),
    )
    set_etag(response, detail.role.version)
    return _detail(detail)


@router.delete(
    "/roles/{role_id}", summary="Delete a custom role", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_role(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    role_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: ManageRoles,
    policy: Policy,
    reassign_to: Annotated[
        uuid.UUID | None,
        Query(description="Required when users hold the role: they move to this role."),
    ] = None,
) -> Response:
    """Delete (If-Match). A role in use needs `reassign_to`: access is never silently removed."""
    await role_service.delete_role(
        session,
        policy,
        subject,
        role_id,
        expected_version=version,
        reassign_to=reassign_to,
        resources=dict(policy.resources),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{user_id}/access", summary="Roles, sites and groups of a user")
async def get_user_access(
    user_id: uuid.UUID, session: TenantSession, subject: ViewUsers
) -> UserAccessOut:
    """What a user holds (for the admin's user drawer)."""
    del subject
    role_ids = await role_service.user_role_ids(session, user_id)
    units = await memberships(session, user_id)
    return UserAccessOut(
        user_id=user_id,
        role_ids=sorted(role_ids),
        site_ids=sorted(units.site_ids),
        group_ids=sorted(units.group_ids),
    )


@router.put(
    "/users/{user_id}/roles/{role_id}",
    summary="Assign a role",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def assign_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    session: TenantSession,
    subject: ManageUsers,
    policy: Policy,
) -> Response:
    """Idempotent. Only roles within your own permissions (tenant admins: any)."""
    await role_service.assign_role(session, policy, subject, user_id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/users/{user_id}/roles/{role_id}",
    summary="Remove a role",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    session: TenantSession,
    subject: ManageUsers,
    policy: Policy,
) -> Response:
    """Idempotent. The last tenant admin cannot lose the role (409 last_tenant_admin)."""
    await role_service.remove_role(session, policy, subject, user_id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
