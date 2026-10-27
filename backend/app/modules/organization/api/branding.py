"""Tenant branding API (WP-017, REQ-ADM-055, REQ-PRT-016, REQ-SEC-003).

Signed in:
- `GET /organization/branding`: the brand of your tenant, for the console and portal theme;
- `GET /organization/branding/settings`, `PUT` (If-Match; "0" creates), `POST .../check`:
  the branding screen (`branding.manage`), audited as `branding.updated`.

Public (the sign-in page, e-mails and the apps before sign-in need them):
- `GET /public/branding`: colours and logo URLs of the address used (unknown address: the
  default);
- `GET /public/branding/{tenant_id}/login.css`: the sign-in page's stylesheet;
- `GET /public/branding/{tenant_id}/{asset}`: a generated logo, icon or favicon. Versioned URLs
  (`?v=`) are cached for a year; anything else for five minutes.

What the public routes may tell (WP-017 review): a tenant's own logo and colours, for its own
address, and nothing else: no names or texts, no slug, no settings, no list. They are keyed by the
tenant's ID, an unguessable UUID (Keycloak has it as the organization's `tenant_id` attribute),
never by the guessable slug; an unknown or malformed ID gets exactly what a tenant without a
brand gets (the default stylesheet, 404 for images), so the routes cannot be used to find
tenants. Only the stylesheet and images may be used cross-origin.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.authorization import public_route, require_permission, require_signed_in
from app.core.database import Database, TenantSession, get_database
from app.core.entitlements import entitlement_exempt
from app.core.errors import NotFound, ProblemDetail
from app.core.tenancy import TenantContext
from app.modules.audit import AuditNote, audited
from app.modules.organization.domain.branding import CheckCode
from app.modules.organization.domain.login_css import LoginLogos, login_css
from app.modules.organization.domain.tenant import TenantStatus
from app.modules.organization.service import branding, hosts
from app.modules.organization.service.file_access import MANAGE
from app.modules.organization.service.tenants import get_current_tenant
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.ratelimit import rate_limit
from app.shared.files.service.core import FileServices

FILES_STATE = "files"  # the system module keeps the API's FileServices on app.state
PUBLIC_PREFIX = "/api/v1/public/branding"
LONG_CACHE = "public, max-age=31536000, immutable"
# The sign-in page (Keycloak, another origin in Compose) and mail clients load these: the API's
# default `Cross-Origin-Resource-Policy: same-origin` would block them. They are public anyway.
CROSS_ORIGIN = {"Cross-Origin-Resource-Policy": "cross-origin"}
SHORT_CACHE = "public, max-age=300"

SignedIn = Annotated[Any, Depends(require_signed_in())]
Manage = Annotated[Any, Depends(require_permission(MANAGE))]


def _files(request: Request) -> FileServices:
    """The API's file services (set by the system module at startup; built once otherwise)."""
    found: FileServices | None = getattr(request.app.state, FILES_STATE, None)
    if found is None:
        found = FileServices.from_settings(request.app.state.settings)
        setattr(request.app.state, FILES_STATE, found)
    return found


Files = Annotated[FileServices, Depends(_files)]

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission."},
}


Gradient = Annotated[list[Annotated[str, Field(max_length=7)]], Field(min_length=2, max_length=2)]


class Logos(BaseModel):
    """Public URLs of the generated images (None: the SupportX default is shown)."""

    full: str | None = None
    full_on_dark: str | None = None
    full_high_contrast: str | None = None
    icon: str | None = None
    icon_high_contrast: str | None = None
    favicon: str | None = None
    apple_touch_icon: str | None = None
    icon_192: str | None = None
    icon_512: str | None = None


class PublicBrandingOut(BaseModel):
    """What anyone may learn about an address before sign-in: its logo and colours only."""

    customised: bool = Field(
        description="False: the SupportX default (also for unknown addresses)."
    )
    primary_colour: str = Field(description="The seed of every primary shade.")
    gradient: list[str] = Field(min_length=2, max_length=2)
    logos: Logos


class BrandingOut(BaseModel):
    """The brand a surface shows. Empty texts and null logos mean the default."""

    customised: bool
    primary_colour: str = Field(description="The seed of every primary shade.")
    gradient: list[str] = Field(min_length=2, max_length=2)
    product_name: dict[str, str]
    portal_name: dict[str, str]
    welcome_text: dict[str, str]
    logos: Logos
    version: int


class BrandingSettingsOut(BrandingOut):
    """The branding screen: what was chosen (null = default) and the uploads behind the logos."""

    chosen_primary_colour: str | None
    chosen_gradient: list[str] | None
    logo_file_id: uuid.UUID | None
    logo_dark_file_id: uuid.UUID | None
    icon_file_id: uuid.UUID | None


class BrandingIn(BaseModel):
    """The whole branding; null or empty restores that part's default."""

    primary_colour: str | None = Field(default=None, max_length=7)
    gradient: Gradient | None = None
    product_name: dict[str, str] = Field(default_factory=dict, max_length=3)
    portal_name: dict[str, str] = Field(default_factory=dict, max_length=3)
    welcome_text: dict[str, str] = Field(default_factory=dict, max_length=3)
    logo_file_id: uuid.UUID | None = None
    logo_dark_file_id: uuid.UUID | None = None
    icon_file_id: uuid.UUID | None = None


class ColoursIn(BaseModel):
    """Colours to check before saving (the live preview)."""

    primary_colour: str | None = Field(default=None, max_length=7)
    gradient: Gradient | None = None


class CheckOut(BaseModel):
    """One contrast check (labels: `branding.check.<code>`)."""

    code: CheckCode
    ratio: float
    required: float
    passed: bool


class ColourReportOut(BaseModel):
    """Every check, and the nearest passing colours when one fails."""

    passes: bool
    checks: list[CheckOut]
    suggested_primary: str | None
    suggested_gradient: list[str] | None


ASSET_FIELDS = {
    "logo.png": "full",
    "logo-dark.png": "full_on_dark",
    "logo-high-contrast.png": "full_high_contrast",
    "icon.png": "icon",
    "icon-high-contrast.png": "icon_high_contrast",
    "favicon.ico": "favicon",
    "apple-touch-icon.png": "apple_touch_icon",
    "icon-192.png": "icon_192",
    "icon-512.png": "icon_512",
}


def asset_url(tenant_id: uuid.UUID, name: str, version: str | None) -> str:
    """The public, versioned URL of one generated image (same host as the page)."""
    return f"{PUBLIC_PREFIX}/{tenant_id}/{name}?v={version or '0'}"


DEFAULT_VIEW = branding.BrandingView(
    uuid.UUID(int=0), None, None, {}, {}, {}, None, None, None, None, frozenset(), 0
)


def _logos(view: branding.BrandingView) -> Logos:
    if view.version == 0:
        return Logos()
    urls = {
        field: asset_url(view.tenant_id, name, view.assets_version)
        for name, field in ASSET_FIELDS.items()
        if name in view.assets
    }
    return Logos(**urls)


def _public_out(view: branding.BrandingView) -> PublicBrandingOut:
    colours = view.colours
    return PublicBrandingOut(
        customised=view.customised,
        primary_colour=colours.primary,
        gradient=list(colours.gradient),
        logos=_logos(view),
    )


def _out(view: branding.BrandingView) -> BrandingOut:
    colours = view.colours
    return BrandingOut(
        customised=view.customised,
        primary_colour=colours.primary,
        gradient=list(colours.gradient),
        product_name=view.product_name,
        portal_name=view.portal_name,
        welcome_text=view.welcome_text,
        logos=_logos(view),
        version=view.version,
    )


def _settings_out(view: branding.BrandingView) -> BrandingSettingsOut:
    return BrandingSettingsOut(
        **_out(view).model_dump(),
        chosen_primary_colour=view.primary_colour,
        chosen_gradient=list(view.gradient) if view.gradient else None,
        logo_file_id=view.logo_file_id,
        logo_dark_file_id=view.logo_dark_file_id,
        icon_file_id=view.icon_file_id,
    )


router = APIRouter(
    prefix="/organization/branding",
    tags=["organization"],
    dependencies=[Depends(rate_limit("organization"))],
    responses=RESPONSES,
)


@router.get("", summary="Your tenant's brand")
async def get_branding(
    response: Response, session: TenantSession, subject: SignedIn
) -> BrandingOut:
    """What the console and portal show: colours, texts and logo URLs (default where unset)."""
    view = await branding.get_branding(session, subject.tenant_id)
    set_etag(response, view.version)
    return _out(view)


@router.get("/settings", summary="Branding settings")
async def get_settings(
    response: Response, session: TenantSession, subject: Manage
) -> BrandingSettingsOut:
    """The branding screen's values (send the ETag back as If-Match to save; "0" creates)."""
    view = await branding.get_branding(session, subject.tenant_id)
    set_etag(response, view.version)
    return _settings_out(view)


@router.put(
    "/settings",
    summary="Save the branding",
    responses={
        409: {"model": ProblemDetail, "description": "Stale If-Match."},
        422: {
            "model": ProblemDetail,
            "description": "A colour fails WCAG AA (`brand_colour_contrast`, with the failing "
            "checks and the nearest passing colour), a text is too long, or an image is unusable.",
        },
    },
)
async def put_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: BrandingIn,
    response: Response,
    session: TenantSession,
    subject: Manage,
    files: Files,
    version: ExpectedVersion,
    note: Annotated[AuditNote, audited("branding.updated", object_type="branding")],
) -> BrandingSettingsOut:
    """Save the whole branding; every open console and portal shows it without a reload."""
    view, changed = await branding.save_branding(
        session,
        services=files,
        actor=subject,
        tenant_id=subject.tenant_id,
        changes=branding.BrandingChanges(
            primary_colour=body.primary_colour,
            gradient=(body.gradient[0], body.gradient[1]) if body.gradient else None,
            product_name=body.product_name,
            portal_name=body.portal_name,
            welcome_text=body.welcome_text,
            logo_file_id=body.logo_file_id,
            logo_dark_file_id=body.logo_dark_file_id,
            icon_file_id=body.icon_file_id,
        ),
        expected_version=version,
    )
    note.object_id = str(subject.tenant_id)
    note.details = {"changed_fields": changed, "version": view.version}
    set_etag(response, view.version)
    return _settings_out(view)


@router.post("/check", summary="Check brand colours")
async def check_colours(body: ColoursIn, subject: Manage) -> ColourReportOut:
    """WCAG AA checks for colours being chosen, with the nearest passing ones (no save)."""
    del subject
    primary = branding.normalise_or_none(body.primary_colour)
    gradient = branding.normalise_pair_or_none(
        (body.gradient[0], body.gradient[1]) if body.gradient else None
    )
    report = branding.colour_report(primary, gradient)
    return ColourReportOut(
        passes=report.passes,
        checks=[
            CheckOut(code=c.code, ratio=round(c.ratio, 2), required=c.required, passed=c.passed)
            for c in report.checks
        ],
        suggested_primary=report.suggested_primary,
        suggested_gradient=list(report.suggested_gradient) if report.suggested_gradient else None,
    )


# No rate limit here: the limiter keys on a tenant, and these reads are cached by browsers.
public_router = APIRouter(prefix="/public/branding", tags=["organization"])

DatabaseDep = Annotated[Database, Depends(get_database)]


async def _active_view(database: Database, tenant_ref: str) -> branding.BrandingView:
    """The brand of an active tenant by ID; the default for anything else (never an oracle)."""
    try:
        tenant_id = uuid.UUID(tenant_ref)
    except ValueError:
        return DEFAULT_VIEW
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        try:
            tenant = await get_current_tenant(session)
        except NotFound:
            return DEFAULT_VIEW
        if tenant.status != TenantStatus.ACTIVE:
            return DEFAULT_VIEW
        return await branding.get_branding(session, tenant_id)


@public_router.get("", summary="Brand of this address")
@entitlement_exempt
@public_route
async def public_branding(request: Request, database: DatabaseDep) -> PublicBrandingOut:
    """Logo and colours of the address used (subdomain or verified custom domain).

    Unknown addresses get the default. Only a hint for what to show before sign-in: it never
    decides access, and it says nothing else about the tenant.
    """
    tenant = await hosts.tenant_for_host(
        database, request.headers.get("host"), request.app.state.settings.tenant_base_domain
    )
    if tenant is None:
        return _public_out(DEFAULT_VIEW)
    return _public_out(await _active_view(database, str(tenant.tenant_id)))


@public_router.get(
    "/{tenant_ref}/login.css",
    summary="Sign-in page stylesheet",
    response_class=Response,
    responses={200: {"content": {"text/css": {}}}},
)
@entitlement_exempt
@public_route
async def login_stylesheet(tenant_ref: str, database: DatabaseDep) -> Response:
    """The tenant's colours and logos for the Keycloak sign-in page (REQ-SEC-003).

    An unknown ID gets the default stylesheet, byte for byte what an unbranded tenant gets.
    """
    view = await _active_view(database, tenant_ref)
    logos = None
    if "logo.png" in view.assets:
        dark = "logo-dark.png" if "logo-dark.png" in view.assets else "logo.png"
        contrast = (
            "logo-high-contrast.png" if "logo-high-contrast.png" in view.assets else "logo.png"
        )
        logos = LoginLogos(
            asset_url(view.tenant_id, "logo.png", view.assets_version),
            asset_url(view.tenant_id, dark, view.assets_version),
            asset_url(view.tenant_id, contrast, view.assets_version),
        )
    return Response(
        login_css(view.colours, logos),
        media_type="text/css",
        headers={"Cache-Control": SHORT_CACHE, "X-Content-Type-Options": "nosniff", **CROSS_ORIGIN},
    )


@public_router.get(
    "/{tenant_ref}/{name}",
    summary="A brand image",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}, "image/x-icon": {}}},
        404: {"model": ProblemDetail},
    },
)
@entitlement_exempt
@public_route
async def brand_image(
    tenant_ref: str, name: str, database: DatabaseDep, v: str | None = None
) -> Response:
    """One generated image. Cached for a year when `v` is the current version.

    The same 404 for an unknown tenant, a tenant without that image and an unknown name.
    """
    view = await _active_view(database, tenant_ref)
    if name not in branding.ASSET_NAMES or name not in view.assets:
        raise NotFound(code="branding_not_found")
    async with database.tenant_session(TenantContext(view.tenant_id)) as session:
        found = await branding.asset(session, name)
        if found is None:
            raise NotFound(code="branding_not_found")
        content, content_type = found.content, found.content_type
    current = v is not None and v == view.assets_version
    return Response(
        content,
        media_type=content_type,
        headers={
            "Cache-Control": LONG_CACHE if current else SHORT_CACHE,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
            **CROSS_ORIGIN,
        },
    )
