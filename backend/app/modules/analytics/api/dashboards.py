"""Dashboards over HTTP (WP-036): `/api/v1/dashboards`.

Widgets carry report definitions; the console runs each through `POST /reports/run` (with the
dashboard's filters added), so a widget counts exactly what the viewer could list.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.core.tenancy import TenantContext, resolve_tenant
from app.modules.analytics.api.routes import CONFLICT, RESPONSES, _validator
from app.modules.analytics.domain.dashboard import DashboardBody
from app.modules.analytics.service import dashboards
from app.modules.analytics.service.library import VIEW
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/dashboards",
    tags=["dashboards"],
    dependencies=[Depends(rate_limit("reports"))],
    responses={**RESPONSES, 404: {"model": ProblemDetail, "description": "No such dashboard."}},
)

Viewer = Annotated[Subject, Depends(require_permission(VIEW))]
Tenant = Annotated[TenantContext, Depends(resolve_tenant)]
NAME_LANGUAGES = ("en", "ar", "ur")


# --- schemas ------------------------------------------------------------------------------------


class DashboardOut(BaseModel):
    """A dashboard as you see it: built-in (`builtin` set) or user-made."""

    ref: str = Field(description='"builtin:<code>" or the dashboard id.')
    builtin: str | None = Field(description="The built-in code (named by `dashboard.<code>`).")
    name: str | None = Field(description="A user-made dashboard's name; None for built-ins.")
    names: dict[str, str]
    description: str | None
    owner_id: str | None
    shared: bool
    copied_from: str | None
    body: DashboardBody
    version: int
    updated_at: datetime | None
    can_edit: bool

    @classmethod
    def of(cls, found: dashboards.DashboardView) -> "DashboardOut":
        """From the service view."""
        record = found.record
        return cls(
            ref=found.ref,
            builtin=found.builtin,
            name=record.name if record else None,
            names=dict(record.names) if record else {},
            description=record.description if record else None,
            owner_id=str(record.owner_id) if record else None,
            shared=found.shared,
            copied_from=record.copied_from if record else None,
            body=found.body,
            version=record.version if record else 1,
            updated_at=record.updated_at if record else None,
            can_edit=found.can_edit,
        )


class DashboardListOut(BaseModel):
    """The dashboard picker (REQ-DSH-005): every dashboard you may see, your favourites, home."""

    items: list[DashboardOut]
    favourites: list[str]
    home: str
    home_chosen: bool = Field(description="True: your own choice; False: your role's home.")


class DashboardIn(BaseModel):
    """A new dashboard (private unless `shared`, which needs `dashboards.share`)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    names: dict[Literal["en", "ar", "ur"], str] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=1000)
    shared: bool = False
    body: DashboardBody = Field(default_factory=DashboardBody)
    copied_from: str | None = Field(default=None, max_length=100)


class DashboardPatch(BaseModel):
    """The fields to change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    names: dict[Literal["en", "ar", "ur"], str] | None = None
    description: str | None = Field(default=None, max_length=1000)
    shared: bool | None = None
    body: DashboardBody | None = None


class HomeIn(BaseModel):
    """Your home dashboard; None goes back to your role's (REQ-DSH-002 AC2)."""

    model_config = ConfigDict(extra="forbid")

    dashboard_ref: str | None = Field(default=None, max_length=100)


class HomeOut(BaseModel):
    """Which dashboard your home page shows."""

    dashboard_ref: str
    chosen: bool


class RoleHomeIn(BaseModel):
    """A role's home dashboard: built-in or shared; None clears it."""

    model_config = ConfigDict(extra="forbid")

    dashboard_ref: str | None = Field(default=None, max_length=100)


# --- routes -------------------------------------------------------------------------------------


@router.get("", summary="Dashboards you may see")
async def list_dashboards(session: TenantSession, subject: Viewer) -> DashboardListOut:
    """Built-in first, then shared and your own; with your favourites and your home."""
    views = await dashboards.list_dashboards(session, subject)
    found = await dashboards.home(session, subject)
    return DashboardListOut(
        items=[DashboardOut.of(v) for v in views],
        favourites=await dashboards.favourites(session, subject),
        home=found.ref,
        home_chosen=found.chosen,
    )


@router.get("/home", summary="Your home dashboard")
async def get_home(session: TenantSession, subject: Viewer) -> HomeOut:
    """Your choice, else your role's, else the built-in home of your role."""
    found = await dashboards.home(session, subject)
    return HomeOut(dashboard_ref=found.ref, chosen=found.chosen)


@router.put("/home", summary="Choose your home dashboard")
async def put_home(body: HomeIn, session: TenantSession, subject: Viewer) -> HomeOut:
    """A dashboard you can see, or null to go back to your role's home."""
    found = await dashboards.set_home(session, subject, body.dashboard_ref)
    return HomeOut(dashboard_ref=found.ref, chosen=found.chosen)


@router.get("/role-homes", summary="Home dashboards set per role")
async def get_role_homes(session: TenantSession, subject: Viewer) -> dict[str, str]:
    """Needs `dashboards.manage_defaults`. Role key → dashboard reference."""
    return await dashboards.role_homes(session, subject)


@router.put(
    "/role-homes/{role_key}",
    summary="Set a role's home dashboard",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[audited("dashboard.role_home_set", object_type="role", object_param="role_key")],
)
async def put_role_home(
    role_key: str, body: RoleHomeIn, session: TenantSession, subject: Viewer
) -> None:
    """Needs `dashboards.manage_defaults`; a built-in or shared dashboard, or null."""
    await dashboards.set_role_home(session, subject, role_key, body.dashboard_ref)


@router.put("/favourites/{ref}", summary="Star a dashboard", status_code=status.HTTP_204_NO_CONTENT)
async def star(ref: str, session: TenantSession, subject: Viewer) -> None:
    """Moves it to your favourites at once (REQ-DSH-005 AC1)."""
    await dashboards.set_favourite(session, subject, ref, starred=True)


@router.delete(
    "/favourites/{ref}", summary="Unstar a dashboard", status_code=status.HTTP_204_NO_CONTENT
)
async def unstar(ref: str, session: TenantSession, subject: Viewer) -> None:
    """Idempotent."""
    await dashboards.set_favourite(session, subject, ref, starred=False)


@router.post(
    "",
    summary="Create or copy a dashboard",
    status_code=status.HTTP_201_CREATED,
    response_model=DashboardOut,
)
async def create_dashboard(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: DashboardIn,
    session: TenantSession,
    subject: Viewer,
    context: Tenant,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Needs `dashboards.create`. A copy names its original in `copied_from` (REQ-DSH-021)."""

    async def go() -> Created:
        saved = await dashboards.create_dashboard(
            session,
            subject,
            name=body.name,
            names={str(k): v for k, v in body.names.items()},
            description=body.description,
            shared=body.shared,
            body=body.body,
            copied_from=body.copied_from,
            validate=_validator(request, session, context, subject),
            source=source_of(request),
        )
        out = DashboardOut.of(saved)
        return Created(
            body=out,
            headers={"Location": f"/api/v1/dashboards/{out.ref}", "ETag": f'"{out.version}"'},
        )

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.get("/{ref}", summary="Get a dashboard")
async def get_dashboard(
    ref: str, session: TenantSession, subject: Viewer, response: Response
) -> DashboardOut:
    """A built-in one, a shared one, or your own; 404 otherwise."""
    found = await dashboards.get_dashboard(session, subject, ref)
    out = DashboardOut.of(found)
    set_etag(response, out.version)
    return out


@router.patch("/{ref}", summary="Change a dashboard", responses=CONFLICT)
async def update_dashboard(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ref: str,
    body: DashboardPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    context: Tenant,
    response: Response,
    request: Request,
) -> DashboardOut:
    """The fields you send, with If-Match. Built-in dashboards are never changed (copy them)."""
    values = {name: getattr(body, name) for name in body.model_fields_set}
    saved = await dashboards.update_dashboard(
        session,
        subject,
        ref,
        expected_version=version,
        values=values,
        validate=_validator(request, session, context, subject),
        source=source_of(request),
    )
    out = DashboardOut.of(saved)
    set_etag(response, out.version)
    return out


@router.delete(
    "/{ref}",
    summary="Delete a dashboard",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_dashboard(
    ref: str,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
) -> None:
    """Needs If-Match."""
    await dashboards.delete_dashboard(
        session, subject, ref, expected_version=version, source=source_of(request)
    )
