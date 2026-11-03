"""Directory connectors HTTP API under /api/v1/integrations/directories (WP-040 session 2).

Everything needs `integrations.manage_identity`. The client secret or certificate goes in and
never comes out (only its type, age and "ending in ..a3f9"). Changes take If-Match (a full
replacement: the screen sends every setting) and are audited; create takes an Idempotency-Key.
No business logic here.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.config import Settings
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.integrations.domain.directory import EmailFrom, SyncScope
from app.modules.integrations.domain.mailboxes import CredentialKind
from app.modules.integrations.service import directories as service
from app.modules.integrations.service.catalogue import manage_permission
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.connectors.ports import ConnectorCategory

MANAGE = manage_permission(ConnectorCategory.IDENTITY)
Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": f"Missing permission ({MANAGE})."},
    404: {"model": ProblemDetail, "description": "No such directory (directory_not_found)."},
}
CONFLICT: Responses = {409: {"model": ProblemDetail, "description": "Stale If-Match, or taken."}}
SECRET_MAX = 20_000  # a PEM with a private key and its certificate chain

router = APIRouter(
    prefix="/integrations/directories",
    tags=["integrations"],
    dependencies=[Depends(rate_limit("integrations"))],
    responses=RESPONSES,
)
Manage = Annotated[Subject, Depends(require_permission(MANAGE))]


def _app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(_app_settings)]


class DirectoryGroupIn(BaseModel):
    """A directory group: its Graph object ID and the name shown."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=36, max_length=36)
    name: str = Field(default="", max_length=200)


class GroupMappingIn(DirectoryGroupIn):
    """A directory group whose members fill a SupportX group."""

    group_id: uuid.UUID


class MappingIn(BaseModel):
    """Where person fields come from (defaults: mail, department, officeLocation)."""

    model_config = ConfigDict(extra="forbid")

    email_from: EmailFrom = EmailFrom.MAIL
    department_from: str = Field(default="department", max_length=40)
    site_from: str = Field(default="officeLocation", max_length=40)
    include_guests: bool = False


class DirectoryIn(BaseModel):
    """Every setting of a directory connector (create and replace)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    directory_tenant: str = Field(
        min_length=1, max_length=200, description="Entra tenant ID, or its primary domain."
    )
    client_id: str = Field(min_length=36, max_length=36, description="The sync app's ID.")
    credential_kind: CredentialKind
    credential: str | None = Field(
        default=None,
        max_length=SECRET_MAX,
        description="Client secret or PEM certificate; required on create, kept when left out.",
    )
    scope: SyncScope = SyncScope.ALL_USERS
    scope_groups: list[DirectoryGroupIn] = Field(default_factory=list, max_length=100)
    group_mappings: list[GroupMappingIn] = Field(default_factory=list, max_length=100)
    mapping: MappingIn = Field(default_factory=MappingIn)
    interval_minutes: int = Field(default=30, ge=15, le=1440)
    enabled: bool = True


class SecretOut(BaseModel):
    """What may be said about the stored secret: never its value."""

    secret_type: str
    ending: str | None = Field(description="Last four characters, for display only.")
    set_at: datetime


class DirectoryOut(BaseModel):
    """A directory connector as its page shows it."""

    id: uuid.UUID
    name: str
    source: str
    directory_tenant: str
    client_id: str
    credential_kind: CredentialKind
    secret: SecretOut | None
    scope: SyncScope
    scope_groups: list[dict[str, Any]]  # Any: {external_id, name}
    group_mappings: list[dict[str, Any]]  # Any: {external_id, name, group_id}
    mapping: dict[str, Any]  # Any: the MappingIn fields
    interval_minutes: int
    enabled: bool
    people: int = Field(description="People this directory keeps.")
    last_synced_at: datetime | None
    next_sync_at: datetime | None
    last_skips: dict[str, int] = Field(description="Last run's skipped by reason code.")
    version: int

    @classmethod
    def of(cls, view: service.DirectoryView) -> "DirectoryOut":
        """From the service's view."""
        row, secret = view.row, view.secret
        return cls(
            id=row.id,
            name=row.name,
            source=row.source,
            directory_tenant=row.directory_tenant,
            client_id=row.client_id,
            credential_kind=CredentialKind(row.credential_kind),
            secret=None
            if secret is None
            else SecretOut(
                secret_type=secret.secret_type, ending=secret.last_four, set_at=secret.set_at
            ),
            scope=SyncScope(row.scope),
            scope_groups=list(row.scope_groups),
            group_mappings=list(row.group_mappings),
            mapping=dict(row.mapping),
            interval_minutes=row.interval_minutes,
            enabled=row.enabled,
            people=view.people,
            last_synced_at=row.last_synced_at,
            next_sync_at=row.next_sync_at if row.enabled else None,
            last_skips={k: int(v) for k, v in row.last_skips.items()},
            version=row.version,
        )


def _values(body: DirectoryIn) -> dict[str, Any]:
    return body.model_dump(mode="json", exclude={"credential"})


@router.get("", summary="Directory connectors")
async def list_directories(session: TenantSession, subject: Manage) -> list[DirectoryOut]:
    """Every directory connector with its last run."""
    del subject
    return [DirectoryOut.of(view) for view in await service.list_directories(session)]


@router.get("/{directory_id}", summary="A directory connector")
async def get_directory(
    directory_id: uuid.UUID, session: TenantSession, subject: Manage, response: Response
) -> DirectoryOut:
    """One connector; its ETag is the version to send back."""
    del subject
    view = await service.get_directory(session, directory_id)
    set_etag(response, view.row.version)
    return DirectoryOut.of(view)


@router.post(
    "",
    summary="Add a directory connector",
    status_code=status.HTTP_201_CREATED,
    response_model=DirectoryOut,
    responses=CONFLICT,
    dependencies=[audited("directory.created", object_type="directory_connector")],
)
async def create_directory(
    body: DirectoryIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    settings: AppSettings,
) -> Response:
    """Send an Idempotency-Key: a retried request returns the same 201. Syncs within a minute."""

    async def run() -> Created:
        view = await service.create_directory(
            session, settings, _values(body), credential=body.credential, by=subject
        )
        out = DirectoryOut.of(view)
        return Created(body=out, headers={"ETag": f'"{out.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.put(
    "/{directory_id}",
    summary="Change a directory connector",
    responses=CONFLICT,
    dependencies=[
        audited("directory.changed", object_type="directory_connector", object_param="directory_id")
    ],
)
async def update_directory(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    directory_id: uuid.UUID,
    body: DirectoryIn,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    settings: AppSettings,
) -> DirectoryOut:
    """If-Match: the version you read. Changing who is synced reads everyone again next run."""
    view = await service.update_directory(
        session,
        settings,
        directory_id,
        _values(body),
        expected_version=version,
        credential=body.credential,
        by=subject,
    )
    set_etag(response, view.row.version)
    return DirectoryOut.of(view)


@router.delete(
    "/{directory_id}",
    summary="Remove a directory connector",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[
        audited("directory.removed", object_type="directory_connector", object_param="directory_id")
    ],
)
async def remove_directory(
    directory_id: uuid.UUID, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> Response:
    """Stop syncing. Its people stay, and SupportX keeps them from now on."""
    del subject
    await service.remove_directory(session, directory_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{directory_id}/sync",
    summary="Sync now",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        audited(
            "directory.sync_requested",
            object_type="directory_connector",
            object_param="directory_id",
        )
    ],
)
async def sync_now(
    directory_id: uuid.UUID, session: TenantSession, subject: Manage
) -> DirectoryOut:
    """Runs within a minute instead of at its interval; the page updates live when it ends."""
    del subject
    return DirectoryOut.of(await service.sync_now(session, directory_id))


class DirectoryGroupOut(BaseModel):
    """A directory group found by name."""

    external_id: str
    name: str


@router.get("/{directory_id}/groups", summary="Find directory groups by name")
async def find_groups(
    directory_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    settings: AppSettings,
    q: Annotated[str, Query(min_length=1, max_length=100)],
) -> list[DirectoryGroupOut]:
    """Up to 25 groups whose name starts with `q`, asked of the directory with the sync app."""
    del subject
    found = await service.find_groups(session, settings, directory_id, q)
    return [DirectoryGroupOut(external_id=g, name=n) for g, n in found]
