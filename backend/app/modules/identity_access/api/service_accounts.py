"""Admin > Service accounts (WP-057 S4a, REQ-SEC-036): non-person identities with an owner.

Every route needs `api_keys.manage`, the right that already covers the keys' service owners.
Roles are given and taken only through the guarded service-role path (no tenant
administration, nothing beyond your own rights); giving one asks for a recent sign-in, as a
workflow's run-as identity does. Connector and workflow identities are listed read-only.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.recent_auth import RecentAuth
from app.modules.audit import AuditNote, audited
from app.modules.identity_access.api.access import Policy
from app.modules.identity_access.api.service_roles import (
    ServiceRoleOut,
    ServiceRolesOut,
    service_roles_out,
)
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.service import service_accounts as service
from app.modules.identity_access.service.service_identities import (
    assign_service_identity_role,
    remove_service_identity_role,
)
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Manage = Annotated[Subject, Depends(require_permission(service.MANAGE))]

router = APIRouter(
    prefix="/service-accounts",
    tags=["service-accounts"],
    dependencies=[Depends(rate_limit("identity"))],
)


class ServiceAccountOut(BaseModel):
    """A service identity: who answers for it, what it is for, its roles and keys."""

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID | None
    owner_name: str | None
    managed_here: bool = Field(
        description="False: a connector's or workflow's identity, changed on its own screen."
    )
    needs_new_owner: bool = Field(
        description="Its owner was deactivated: give it a new one (REQ-ADM-011)."
    )
    active: bool
    keys: int = Field(description="Active API keys it owns.")
    roles: list[ServiceRoleOut]
    version: int

    @classmethod
    def of(cls, view: service.ServiceAccountView) -> "ServiceAccountOut":
        """From the service's view."""
        return cls(
            id=view.id,
            name=view.name,
            description=view.description,
            owner_id=view.owner_id,
            owner_name=view.owner_name,
            managed_here=view.managed_here,
            needs_new_owner=view.needs_new_owner,
            active=view.active,
            keys=view.keys,
            roles=[
                ServiceRoleOut(id=r.id, key=r.key, name=r.name, system=r.system) for r in view.roles
            ],
            version=view.version,
        )


class ServiceAccountIn(BaseModel):
    """A new service account: its name, its owner and what it is for."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=service.NAME_MAX)
    description: str | None = Field(default=None, max_length=service.DESCRIPTION_MAX)
    owner_id: uuid.UUID = Field(description="An active technician who answers for it.")


class ServiceAccountPatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=service.NAME_MAX)
    description: str | None = Field(default=None, max_length=service.DESCRIPTION_MAX)
    owner_id: uuid.UUID | None = None
    active: bool | None = Field(default=None, description="Off: its keys stop working at once.")


@router.get("", summary="Service accounts")
async def list_accounts(session: TenantSession, subject: Manage) -> list[ServiceAccountOut]:
    """Every service identity of the tenant, by name."""
    return [ServiceAccountOut.of(v) for v in await service.list_service_accounts(session, subject)]


@router.post(
    "",
    summary="Make a service account",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceAccountOut,
)
async def create_account(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: ServiceAccountIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
    note: Annotated[
        AuditNote, audited("identity_access.service_account_created", object_type="user")
    ],
) -> Response:
    """No roles yet: give them next (Idempotency-Key)."""
    note.skip = True

    async def run() -> Created:
        view = await service.create_service_account(
            session,
            subject,
            name=body.name,
            description=body.description,
            owner_id=body.owner_id,
            source=source_of(request),
        )
        note.skip = False
        note.object_id = str(view.id)
        note.details = {"owner_id": str(body.owner_id)}
        return Created(ServiceAccountOut.of(view), {"ETag": f'"{view.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/{account_id}", summary="A service account")
async def get_account(
    account_id: uuid.UUID, session: TenantSession, subject: Manage, response: Response
) -> ServiceAccountOut:
    """403 `not_a_service_identity` for a person."""
    view = await service.service_account(session, subject, account_id)
    set_etag(response, view.version)
    return ServiceAccountOut.of(view)


@router.patch("/{account_id}", summary="Change a service account")
async def change_account(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    account_id: uuid.UUID,
    body: ServiceAccountPatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    request: Request,
    note: Annotated[
        AuditNote,
        audited(
            "identity_access.service_account_changed",
            object_type="user",
            object_param="account_id",
        ),
    ],
) -> ServiceAccountOut:
    """Name, description, owner, active (If-Match); only accounts made here."""
    values = body.model_dump(exclude_unset=True)
    note.details = {"changed_fields": sorted(values)}
    view = await service.update_service_account(
        session,
        subject,
        account_id,
        expected_version=version,
        values=values,
        source=source_of(request),
    )
    set_etag(response, view.version)
    return ServiceAccountOut.of(view)


@router.get("/{account_id}/roles", summary="A service account's roles and those it may hold")
async def account_roles(
    account_id: uuid.UUID, session: TenantSession, subject: Manage, policy: Policy
) -> ServiceRolesOut:
    """The roles given to it and the roles you may give it (the picker)."""
    await service.service_account(session, subject, account_id)
    return await service_roles_out(session, policy, subject, account_id)


@router.put(
    "/{account_id}/roles/{role_id}",
    summary="Give a service account a role",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        RecentAuth,
        audited(
            "identity_access.service_account_role_added",
            object_type="user",
            object_param="account_id",
            detail_params=("role_id",),
        ),
    ],
)
async def add_role(
    account_id: uuid.UUID,
    role_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    policy: Policy,
) -> Response:
    """Idempotent; never tenant administration or more than your own rights."""
    await service.service_account(session, subject, account_id)
    await assign_service_identity_role(session, policy, subject, account_id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{account_id}/roles/{role_id}",
    summary="Take a role from a service account",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited(
            "identity_access.service_account_role_removed",
            object_type="user",
            object_param="account_id",
            detail_params=("role_id",),
        )
    ],
)
async def remove_role(
    account_id: uuid.UUID,
    role_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    policy: Policy,
) -> Response:
    """Idempotent; through the same guarded path."""
    await service.service_account(session, subject, account_id)
    await remove_service_identity_role(session, policy, subject, account_id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
