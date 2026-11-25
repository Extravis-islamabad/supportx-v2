"""Group mappings' routes (WP-057 S5c-1a, REQ-SEC-014; lane B blocks).

`identity.manage`, every write audited and asking for a recent sign-in.
- `GET /identity/group-mappings?source_kind=&source_id=`: a source's mappings.
- `POST /identity/group-mappings`: a new mapping onto a role or a support group (Idempotency-Key).
  - An SSO source: 422 `idp_group_mappings_coming_soon` until S5c-1b.
  - A privileged target without the tenant opt-in: 409 `mapping_grants_privileged_access`.
- `GET /identity/group-mappings/{id}/holders`: how many people hold access through it (the
  remove dialog's count).
- `DELETE /identity/group-mappings/{id}?on_held=keep|remove`: required when anyone holds access
  through it (the coordinator's Q2; 422 `mapping_in_use_choice_required` otherwise).
- `GET`/`PUT /identity/group-mappings/settings`: the tenant opt-in (lane B's condition 4).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import NotFound
from app.core.recent_auth import RecentAuth
from app.modules.audit import AuditNote, audited
from app.modules.identity_access.domain.group_mappings import (
    MAX_GROUP_ID,
    SSO_GROUP_MAPPINGS_READY,
    SourceKind,
)
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.models import IdpGroupMapping
from app.modules.identity_access.service import group_mappings as mappings
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/identity/group-mappings",
    tags=["identity"],
    dependencies=[Depends(rate_limit("identity"))],
)
Manage = Annotated[Subject, Depends(require_permission("identity.manage"))]


class IdpGroupMappingIn(BaseModel):
    """One external group onto exactly one role or support group."""

    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKind
    source_id: uuid.UUID = Field(description="The directory connector or SSO set-up.")
    external_group_id: str = Field(
        min_length=1, max_length=MAX_GROUP_ID, description="The group's immutable ID, exact."
    )
    external_name: str | None = Field(default=None, max_length=MAX_GROUP_ID)
    role_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None


class IdpGroupMappingOut(BaseModel):
    """A mapping as its admins see it."""

    id: uuid.UUID
    source_kind: SourceKind
    source_id: uuid.UUID
    external_group_id: str
    external_name: str | None
    role_id: uuid.UUID | None
    group_id: uuid.UUID | None
    enabled: bool
    version: int

    @classmethod
    def of(cls, row: IdpGroupMapping) -> "IdpGroupMappingOut":
        """From the row."""
        return cls(
            id=row.id,
            source_kind=SourceKind(row.source_kind),
            source_id=row.source_id,
            external_group_id=row.external_group_id,
            external_name=row.external_name,
            role_id=row.role_id,
            group_id=row.group_id,
            enabled=row.enabled,
            version=row.version,
        )


class HoldersOut(BaseModel):
    """How many people hold access through one mapping."""

    holders: int


class MappingSettingsOut(BaseModel):
    """The tenant's group-mapping settings."""

    privileged_allowed: bool = Field(
        description="A mapping may give tenant admin or another never_via_idp right."
    )
    sso_sources_ready: bool = Field(
        description="SSO set-ups may be a mapping's source (false until S5c-1b)."
    )
    version: int = Field(description="The access settings' version, for If-Match (0: never saved).")


class MappingSettingsIn(BaseModel):
    """Turn the opt-in on or off."""

    model_config = ConfigDict(extra="forbid")

    privileged_allowed: bool


@router.get("", summary="A source's group mappings")
async def list_group_mappings(
    session: TenantSession,
    subject: Manage,
    source_kind: Annotated[SourceKind, Query()],
    source_id: Annotated[uuid.UUID, Query()],
) -> list[IdpGroupMappingOut]:
    """Oldest first."""
    del subject
    rows = await mappings.list_mappings(session, source_kind, source_id)
    return [IdpGroupMappingOut.of(r) for r in rows]


@router.post("", summary="Map an external group", status_code=201, dependencies=[RecentAuth])
async def create_group_mapping(
    body: IdpGroupMappingIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote, audited("idp_group_mapping.created", object_type="idp_group_mapping")
    ],
) -> Response:
    """It applies at the next sync (directory) or sign-in (SSO, from S5c-1b)."""
    del subject
    note.details = {"source_kind": body.source_kind.value, "source_id": str(body.source_id)}

    async def operation() -> Created:
        row = await mappings.create_mapping(
            session,
            source_kind=body.source_kind,
            source_id=body.source_id,
            external_group_id=body.external_group_id,
            external_name=body.external_name,
            role_id=body.role_id,
            group_id=body.group_id,
        )
        note.object_id = str(row.id)
        return Created(IdpGroupMappingOut.of(row), {"ETag": f'"{row.version}"'})

    return await idempotency.run(body, operation)


@router.get("/settings", summary="The tenant's group-mapping settings")
async def get_mapping_settings(
    session: TenantSession, subject: Manage, response: Response
) -> MappingSettingsOut:
    """Whether privileged mappings are allowed, and whether SSO sources may be used yet."""
    del subject
    version = await mappings.settings_version(session)
    set_etag(response, version)
    return MappingSettingsOut(
        privileged_allowed=await mappings.privileged_allowed(session),
        sso_sources_ready=SSO_GROUP_MAPPINGS_READY,
        version=version,
    )


@router.put("/settings", summary="Allow privileged mappings, or not", dependencies=[RecentAuth])
async def save_mapping_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: MappingSettingsIn,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    note: Annotated[
        AuditNote,
        audited("idp_group_mapping.privileged_opt_in_changed", object_type="access_settings"),
    ],
) -> MappingSettingsOut:
    """Turning it off removes nothing; new privileged mappings are refused again."""
    del subject
    note.details = {"privileged_allowed": str(body.privileged_allowed).lower()}
    await mappings.set_privileged_allowed(
        session, allowed=body.privileged_allowed, expected_version=version
    )
    saved = await mappings.settings_version(session)
    set_etag(response, saved)
    return MappingSettingsOut(
        privileged_allowed=body.privileged_allowed,
        sso_sources_ready=SSO_GROUP_MAPPINGS_READY,
        version=saved,
    )


@router.get("/{mapping_id}/holders", summary="People holding access through a mapping")
async def mapping_holders(
    mapping_id: uuid.UUID, session: TenantSession, subject: Manage
) -> HoldersOut:
    """The remove dialog's count (the coordinator's Q2)."""
    del subject
    found = await session.get(IdpGroupMapping, mapping_id)
    if found is None or found.deleted_at is not None:
        raise NotFound(code="mapping_not_found")
    return HoldersOut(holders=await mappings.holders(session, mapping_id))


@router.delete(
    "/{mapping_id}", summary="Remove a group mapping", status_code=204, dependencies=[RecentAuth]
)
async def delete_group_mapping(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    mapping_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    note: Annotated[
        AuditNote,
        audited(
            "idp_group_mapping.removed", object_type="idp_group_mapping", object_param="mapping_id"
        ),
    ],
    on_held: Annotated[Literal["keep", "remove"] | None, Query()] = None,
) -> Response:
    """What it gave stays as hand-made ("keep") or goes now ("remove"); never silent."""
    del subject
    note.details = {"on_held": on_held or ""}
    await mappings.remove_mapping(session, mapping_id, on_held=on_held, expected_version=version)
    return Response(status_code=204)
