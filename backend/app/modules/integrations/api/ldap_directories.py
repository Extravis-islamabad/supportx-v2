"""AD/LDAP directories HTTP API under /api/v1/integrations/ldap-directories (WP-040, D-118).

Everything needs `integrations.manage_identity`, as for Entra directories. The bind password
goes in and never comes out (only its type and age). Changes take If-Match (a full replacement)
and are audited, including the protection chosen: plain LDAP is allowed only by an explicit,
audited choice. Create takes an Idempotency-Key. No business logic here.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.config import Settings
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.integrations.domain.ldap import Security, Vendor
from app.modules.integrations.service import ldap_directories as service
from app.modules.integrations.service.catalogue import manage_permission
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.connectors.ports import ConnectorCategory

MANAGE = manage_permission(ConnectorCategory.IDENTITY)
Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {
        "model": ProblemDetail,
        "description": f"Missing permission ({MANAGE}), or the add-on (entitlement_required).",
    },
    404: {"model": ProblemDetail, "description": "No such directory (directory_not_found)."},
    409: {
        "model": ProblemDetail,
        "description": "Stale If-Match, a taken name, or a shared realm (ldap_single_tenant_only).",
    },
    503: {
        "model": ProblemDetail,
        "description": "AD/LDAP not turned on here (ldap_federation_not_installed).",
    },
}
PASSWORD_MAX = 1000

router = APIRouter(
    prefix="/integrations/ldap-directories",
    tags=["integrations"],
    dependencies=[Depends(rate_limit("integrations"))],
    responses=RESPONSES,
)
Manage = Annotated[Subject, Depends(require_permission(MANAGE))]


def _multi_tenant(request: Request) -> bool:
    # The installation's own fact, as identity settings use it (never a deployment-mode branch).
    return bool(request.app.state.settings.multi_tenant)


def _app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(_app_settings)]
MultiTenant = Annotated[bool, Depends(_multi_tenant)]


class LdapDirectoryIn(BaseModel):
    """Every setting of an AD/LDAP directory (create and replace)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    host: str = Field(min_length=1, max_length=253, description="Server name or IP address.")
    port: int | None = Field(default=None, description="Default 636 for LDAPS, else 389.")
    security: Security = Security.LDAPS
    allow_plain: bool = Field(
        default=False, description="Required (and audited) to save `security: plain`."
    )
    vendor: Vendor = Vendor.ACTIVE_DIRECTORY
    bind_dn: str = Field(min_length=1, max_length=500)
    bind_password: str | None = Field(
        default=None,
        max_length=PASSWORD_MAX,
        description="The bind account's password; required on create, kept when left out.",
    )
    users_dn: str = Field(min_length=1, max_length=500)
    groups_dn: str | None = Field(default=None, max_length=500)
    user_filter: str | None = Field(default=None, max_length=500)
    department_from: str = Field(default="department", max_length=64)
    site_from: str = Field(default="physicalDeliveryOfficeName", max_length=64)
    changed_sync_seconds: int = Field(default=1800, ge=300, le=86400)
    full_sync_seconds: int = Field(default=86400, ge=3600, le=7 * 86400)
    enabled: bool = True


class PasswordOut(BaseModel):
    """What may be said about the stored bind password: never its value."""

    secret_type: str
    set_at: datetime


class LdapDirectoryOut(BaseModel):
    """An AD/LDAP directory as its page shows it."""

    id: uuid.UUID
    name: str
    settings: dict[str, Any]  # Any: the LdapDirectoryIn fields, without the password
    bind_password: PasswordOut | None
    enabled: bool
    federation_state: str | None = Field(description="pending, applied or failed.")
    federation_error: str | None = Field(description="A reason code when failed.")
    people: int = Field(description="People this directory keeps.")
    version: int

    @classmethod
    def of(cls, view: service.DirectoryView) -> "LdapDirectoryOut":
        """From the service's view of a directory."""
        row = view.row
        password = (
            PasswordOut(secret_type=view.secret.secret_type, set_at=view.secret.set_at)
            if view.secret is not None
            else None
        )
        return cls(
            id=row.id,
            name=row.name,
            settings=dict(row.ldap or {}),
            bind_password=password,
            enabled=row.enabled,
            federation_state=row.federation_state,
            federation_error=row.federation_error,
            people=view.people,
            version=row.version,
        )


def _values(body: LdapDirectoryIn) -> dict[str, Any]:
    values = body.model_dump(mode="json", exclude={"bind_password"})
    if values["port"] is None:
        del values["port"]  # the default follows the protection
    return values


def _note(note: AuditNote, body: LdapDirectoryIn) -> None:
    # The protection is recorded on every save: plain LDAP is an explicit, audited choice.
    note.details = {
        "source": "ldap",
        "security": body.security.value,
        "allow_plain": body.allow_plain,
    }


@router.get("", summary="AD/LDAP directories")
async def list_ldap_directories(session: TenantSession, subject: Manage) -> list[LdapDirectoryOut]:
    """Every AD/LDAP directory, with how its connection in the identity service stands."""
    del subject
    return [LdapDirectoryOut.of(v) for v in await service.list_ldap_directories(session)]


@router.get("/{directory_id}", summary="An AD/LDAP directory")
async def get_ldap_directory(
    directory_id: uuid.UUID, session: TenantSession, subject: Manage, response: Response
) -> LdapDirectoryOut:
    """One directory; its ETag is the version to send back."""
    del subject
    view = await service.get_ldap_directory(session, directory_id)
    set_etag(response, view.row.version)
    return LdapDirectoryOut.of(view)


@router.post(
    "",
    summary="Connect an AD/LDAP directory",
    status_code=status.HTTP_201_CREATED,
    response_model=LdapDirectoryOut,
)
async def create_ldap_directory(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: LdapDirectoryIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    settings: AppSettings,
    multi_tenant: MultiTenant,
    note: Annotated[AuditNote, audited("directory.created", object_type="directory_connector")],
) -> Response:
    """Send an Idempotency-Key. The identity service connects it within moments (live state)."""
    _note(note, body)

    async def run() -> Created:
        view = await service.create_ldap_directory(
            session,
            settings,
            subject.tenant_id,
            _values(body),
            bind_password=body.bind_password,
            multi_tenant=multi_tenant,
        )
        note.object_id = str(view.row.id)
        out = LdapDirectoryOut.of(view)
        return Created(body=out, headers={"ETag": f'"{out.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.put("/{directory_id}", summary="Change an AD/LDAP directory")
async def update_ldap_directory(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    directory_id: uuid.UUID,
    body: LdapDirectoryIn,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    settings: AppSettings,
    multi_tenant: MultiTenant,
    note: Annotated[
        AuditNote,
        audited(
            "directory.changed", object_type="directory_connector", object_param="directory_id"
        ),
    ],
) -> LdapDirectoryOut:
    """If-Match: the version you read. The identity service is updated within moments."""
    _note(note, body)
    view = await service.update_ldap_directory(
        session,
        settings,
        subject.tenant_id,
        directory_id,
        _values(body),
        expected_version=version,
        bind_password=body.bind_password,
        multi_tenant=multi_tenant,
    )
    set_etag(response, view.row.version)
    return LdapDirectoryOut.of(view)


@router.delete(
    "/{directory_id}",
    summary="Disconnect an AD/LDAP directory",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited("directory.removed", object_type="directory_connector", object_param="directory_id")
    ],
)
async def remove_ldap_directory(
    directory_id: uuid.UUID, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> Response:
    """Its people stay, and SupportX keeps them from now on."""
    del subject
    await service.remove_ldap_directory(session, directory_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
