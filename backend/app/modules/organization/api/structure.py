"""Sites, support groups, departments and desks over HTTP (WP-021; ADR-032). No logic here.

Sites and groups keep their WP-016 paths (/organization/sites, /organization/groups) and gain
their details; members stay on the member endpoints (units.py). Every write is audited and
sends If-Match (except creates, which take an Idempotency-Key).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.entitlements import route_guard
from app.core.errors import ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.organization.infra.models import Department, Desk, Site
from app.modules.organization.service import structure
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such site, group, department or desk."},
    409: {"model": ProblemDetail, "description": "Stale If-Match, or still in use."},
    422: {"model": ProblemDetail, "description": "Problems by field."},
}
RATE = [Depends(rate_limit("organization"))]


# --- sites ----------------------------------------------------------------------------------------


class SiteOut(BaseModel):
    """A site with its details and the IDs of its members (the `site` scope)."""

    id: uuid.UUID
    name: str
    description: str | None
    region: str | None
    time_zone: str | None
    default_language: str | None
    address: str | None
    phone: str | None
    email: str | None
    is_default: bool
    disabled: bool = Field(description="Inactive: kept where used, not offered for new ones.")
    member_ids: list[uuid.UUID]
    version: int = Field(description="Send back as If-Match to change it.")


class SiteIn(BaseModel):
    """A new site."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    region: str | None = Field(default=None, max_length=100)
    time_zone: str | None = Field(
        default=None, max_length=64, description="IANA, e.g. Asia/Riyadh."
    )
    default_language: str | None = Field(default=None, max_length=2)
    address: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=320)


class SitePatch(BaseModel):
    """What to change (only what is sent); `disabled` makes it inactive or active again."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    region: str | None = Field(default=None, max_length=100)
    time_zone: str | None = Field(default=None, max_length=64)
    default_language: str | None = Field(default=None, max_length=2)
    address: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=320)
    disabled: bool | None = None


def _site_out(row: Site, member_ids: list[uuid.UUID]) -> SiteOut:
    return SiteOut(
        id=row.id,
        name=row.name,
        description=row.description,
        region=row.region,
        time_zone=row.time_zone,
        default_language=row.default_language,
        address=row.address,
        phone=row.phone,
        email=row.email,
        is_default=row.is_default,
        disabled=row.disabled_at is not None,
        member_ids=member_ids,
        version=row.version,
    )


sites = APIRouter(
    prefix="/organization/sites", tags=["organization"], dependencies=RATE, responses=RESPONSES
)
SITES_VIEW = Depends(require_permission("sites.view"))
SITES_MANAGE = Depends(require_permission("sites.manage"))


@sites.get("", summary="List sites", dependencies=[SITES_VIEW])
async def list_sites(session: TenantSession) -> list[SiteOut]:
    """Every site by name, inactive ones included (marked), with member IDs."""
    rows = await structure.list_sites(session)
    members = await structure.site_members(session)
    return [_site_out(r, members.get(r.id, [])) for r in rows]


@sites.post(
    "",
    summary="Add a site",
    status_code=status.HTTP_201_CREATED,
    dependencies=[SITES_MANAGE],
    response_model=SiteOut,
    responses={201: {"model": SiteOut, "description": "Created (or replayed)."}},
)
async def create_site(
    body: SiteIn,
    session: TenantSession,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("site.created", object_type="site")],
) -> Response:
    """A new site (Idempotency-Key supported)."""
    note.skip = True

    async def operation() -> Created:
        row = await structure.save_site(session, None, body.model_dump(exclude_unset=True))
        note.skip = False
        note.object_id = str(row.id)
        return Created(_site_out(row, []), {"ETag": f'"{row.version}"'})

    return await idempotency.run(body, operation)


@sites.patch(
    "/{unit_id}",
    summary="Change a site",
    dependencies=[
        SITES_MANAGE,
        audited("site.changed", object_type="site", object_param="unit_id"),
    ],
)
async def patch_site(
    unit_id: uuid.UUID,
    body: SitePatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
) -> SiteOut:
    """Details, or `disabled` (never the default site)."""
    row = await structure.save_site(
        session, unit_id, body.model_dump(exclude_unset=True), expected_version=version
    )
    set_etag(response, row.version)
    members = await structure.site_members(session)
    return _site_out(row, members.get(row.id, []))


@sites.delete(
    "/{unit_id}",
    summary="Remove a site nothing uses",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        SITES_MANAGE,
        audited("site.deleted", object_type="site", object_param="unit_id"),
    ],
)
async def delete_site(
    unit_id: uuid.UUID, version: ExpectedVersion, session: TenantSession
) -> Response:
    """409 `site_in_use` (counts) while used; `default_site_required` for the default site.

    Members, people, records, departments and groups serving it keep it in use: make it
    inactive instead.
    """
    await structure.remove_unit(session, "site", unit_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- support groups -------------------------------------------------------------------------------


class GroupOut(BaseModel):
    """A support group with its details, the sites it serves and its members."""

    id: uuid.UUID
    name: str
    description: str | None
    lead_id: uuid.UUID | None
    email: str | None = Field(description="The group's own address (notifications, mail).")
    sender_name: str | None
    desk_id: uuid.UUID
    site_ids: list[uuid.UUID] = Field(description="The sites it serves (one or many).")
    disabled: bool
    member_ids: list[uuid.UUID]
    version: int


class GroupIn(BaseModel):
    """A new support group."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    lead_id: uuid.UUID | None = None
    email: str | None = Field(default=None, max_length=320)
    sender_name: str | None = Field(default=None, max_length=200)
    desk_id: uuid.UUID | None = Field(default=None, description="Default: the IT desk.")
    site_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class GroupPatch(BaseModel):
    """What to change (only what is sent); `site_ids` replaces the list."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    lead_id: uuid.UUID | None = None
    email: str | None = Field(default=None, max_length=320)
    sender_name: str | None = Field(default=None, max_length=200)
    desk_id: uuid.UUID | None = None
    site_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    disabled: bool | None = None


def _group_out(detail: structure.GroupDetail) -> GroupOut:
    group = detail.group
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        lead_id=group.lead_id,
        email=group.email,
        sender_name=group.sender_name,
        desk_id=group.desk_id,
        site_ids=detail.site_ids,
        disabled=group.disabled_at is not None,
        member_ids=detail.member_ids,
        version=group.version,
    )


groups = APIRouter(
    prefix="/organization/groups", tags=["organization"], dependencies=RATE, responses=RESPONSES
)
GROUPS_VIEW = Depends(require_permission("groups.view"))
GROUPS_MANAGE = Depends(require_permission("groups.manage"))


@groups.get("", summary="List support groups", dependencies=[GROUPS_VIEW])
async def list_groups(
    session: TenantSession,
    site_id: Annotated[
        uuid.UUID | None, Query(description="Only groups serving this site.")
    ] = None,
) -> list[GroupOut]:
    """Every group by name, inactive ones included (marked)."""
    return [_group_out(d) for d in await structure.list_groups(session, site_id=site_id)]


@groups.post(
    "",
    summary="Add a support group",
    status_code=status.HTTP_201_CREATED,
    dependencies=[GROUPS_MANAGE],
    response_model=GroupOut,
    responses={201: {"model": GroupOut, "description": "Created (or replayed)."}},
)
async def create_group(
    body: GroupIn,
    session: TenantSession,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("group.created", object_type="group")],
) -> Response:
    """A new group (Idempotency-Key supported). A group without members can be saved."""
    note.skip = True

    async def operation() -> Created:
        detail = await structure.save_group(session, None, body.model_dump(exclude_unset=True))
        note.skip = False
        note.object_id = str(detail.group.id)
        return Created(_group_out(detail), {"ETag": f'"{detail.group.version}"'})

    return await idempotency.run(body, operation)


@groups.patch(
    "/{unit_id}",
    summary="Change a support group",
    dependencies=[
        GROUPS_MANAGE,
        audited("group.changed", object_type="group", object_param="unit_id"),
    ],
)
async def patch_group(
    unit_id: uuid.UUID,
    body: GroupPatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
) -> GroupOut:
    """Details, lead, sites served, desk, or `disabled`."""
    detail = await structure.save_group(
        session, unit_id, body.model_dump(exclude_unset=True), expected_version=version
    )
    set_etag(response, detail.group.version)
    return _group_out(detail)


@groups.delete(
    "/{unit_id}",
    summary="Remove a support group nothing uses",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        GROUPS_MANAGE,
        audited("group.deleted", object_type="group", object_param="unit_id"),
    ],
)
async def delete_group(
    unit_id: uuid.UUID, version: ExpectedVersion, session: TenantSession
) -> Response:
    """409 `group_in_use` (with the counts) while members or records use it."""
    await structure.remove_unit(session, "group", unit_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- departments ----------------------------------------------------------------------------------


class DepartmentOut(BaseModel):
    """A department."""

    id: uuid.UUID
    name: str
    code: str | None = Field(description="Unique per tenant; directory sync maps by it.")
    site_id: uuid.UUID | None
    head_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    description: str | None
    disabled: bool
    version: int

    @classmethod
    def of(cls, row: Department) -> "DepartmentOut":
        """From a row."""
        return cls(
            id=row.id,
            name=row.name,
            code=row.code,
            site_id=row.site_id,
            head_id=row.head_id,
            parent_id=row.parent_id,
            description=row.description,
            disabled=row.disabled_at is not None,
            version=row.version,
        )


class DepartmentIn(BaseModel):
    """A new department."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    code: str | None = Field(default=None, max_length=50)
    site_id: uuid.UUID | None = None
    head_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=2000)


class DepartmentPatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=50)
    site_id: uuid.UUID | None = None
    head_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=2000)
    disabled: bool | None = None


departments = APIRouter(
    prefix="/organization/departments",
    tags=["organization"],
    dependencies=RATE,
    responses=RESPONSES,
)
DEPARTMENTS_VIEW = Depends(require_permission("departments.view"))
DEPARTMENTS_MANAGE = Depends(require_permission("departments.manage"))


@departments.get("", summary="List departments", dependencies=[DEPARTMENTS_VIEW])
async def list_departments(
    session: TenantSession,
    site_id: Annotated[uuid.UUID | None, Query(description="Only this site's departments.")] = None,
) -> list[DepartmentOut]:
    """Every department by name, inactive ones included (marked)."""
    return [DepartmentOut.of(r) for r in await structure.list_departments(session, site_id=site_id)]


@departments.post(
    "",
    summary="Add a department",
    status_code=status.HTTP_201_CREATED,
    dependencies=[DEPARTMENTS_MANAGE],
    response_model=DepartmentOut,
    responses={201: {"model": DepartmentOut, "description": "Created (or replayed)."}},
)
async def create_department(
    body: DepartmentIn,
    session: TenantSession,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("department.created", object_type="department")],
) -> Response:
    """A new department (Idempotency-Key supported)."""
    note.skip = True

    async def operation() -> Created:
        row = await structure.save_department(session, None, body.model_dump(exclude_unset=True))
        note.skip = False
        note.object_id = str(row.id)
        return Created(DepartmentOut.of(row), {"ETag": f'"{row.version}"'})

    return await idempotency.run(body, operation)


@departments.patch(
    "/{department_id}",
    summary="Change a department",
    dependencies=[
        DEPARTMENTS_MANAGE,
        audited("department.changed", object_type="department", object_param="department_id"),
    ],
)
async def patch_department(
    department_id: uuid.UUID,
    body: DepartmentPatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
) -> DepartmentOut:
    """Details, parent (never its own ancestor), or `disabled`."""
    row = await structure.save_department(
        session, department_id, body.model_dump(exclude_unset=True), expected_version=version
    )
    set_etag(response, row.version)
    return DepartmentOut.of(row)


@departments.delete(
    "/{department_id}",
    summary="Remove a department nothing uses",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        DEPARTMENTS_MANAGE,
        audited("department.deleted", object_type="department", object_param="department_id"),
    ],
)
async def delete_department(
    department_id: uuid.UUID, version: ExpectedVersion, session: TenantSession
) -> Response:
    """409 `department_in_use` while people, records or child departments use it."""
    await structure.remove_unit(session, "department", department_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- desks ----------------------------------------------------------------------------------------


class DeskOut(BaseModel):
    """A desk (ESM). Screens show desks only to tenants with the ESM feature."""

    id: uuid.UUID
    code: str
    labels: dict[str, str]
    is_default: bool
    disabled: bool
    version: int
    created_at: datetime

    @classmethod
    def of(cls, row: Desk) -> "DeskOut":
        """From a row."""
        return cls(
            id=row.id,
            code=row.code,
            labels=row.labels,
            is_default=row.is_default,
            disabled=row.disabled_at is not None,
            version=row.version,
            created_at=row.created_at,
        )


class DeskIn(BaseModel):
    """A new desk."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=40, description="Stable, lowercase: hr, facilities ...")
    labels: dict[str, str] = Field(description="Name per language; en required.")


class DeskPatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = None
    disabled: bool | None = None


desks = APIRouter(
    prefix="/organization/desks", tags=["organization"], dependencies=RATE, responses=RESPONSES
)
SETTINGS_MANAGE = Depends(require_permission("settings.manage"))
ESM = Depends(route_guard("esm"))


@desks.get("", summary="List desks", dependencies=[Depends(require_signed_in())])
async def list_desks(session: TenantSession) -> list[DeskOut]:
    """Every desk, the IT desk first (always at least that one)."""
    return [DeskOut.of(r) for r in await structure.list_desks(session)]


@desks.post(
    "",
    summary="Add a desk (ESM)",
    status_code=status.HTTP_201_CREATED,
    dependencies=[SETTINGS_MANAGE, ESM],
    response_model=DeskOut,
    responses={201: {"model": DeskOut, "description": "Created (or replayed)."}},
)
async def create_desk(
    body: DeskIn,
    session: TenantSession,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("desk.created", object_type="desk")],
) -> Response:
    """Needs the ESM feature; counts against the licence limit `desks` (D-061, D-092)."""
    note.skip = True

    async def operation() -> Created:
        row = await structure.create_licensed_desk(session, body.model_dump())
        note.skip = False
        note.object_id = str(row.id)
        return Created(DeskOut.of(row), {"ETag": f'"{row.version}"'})

    return await idempotency.run(body, operation)


@desks.patch(
    "/{desk_id}",
    summary="Change a desk (ESM)",
    dependencies=[
        SETTINGS_MANAGE,
        ESM,
        audited("desk.changed", object_type="desk", object_param="desk_id"),
    ],
)
async def patch_desk(
    desk_id: uuid.UUID,
    body: DeskPatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
) -> DeskOut:
    """Name, or `disabled` (never the IT desk)."""
    row = await structure.save_desk(
        session, desk_id, body.model_dump(exclude_unset=True), expected_version=version
    )
    set_etag(response, row.version)
    return DeskOut.of(row)
