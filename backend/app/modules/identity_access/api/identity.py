"""Sign-in and security settings (WP-039; REQ-SEC-013, REQ-SEC-017, REQ-SEC-029; D-094).

Admin > Sign-in and security reads and saves these with `identity.manage`; every change is
audited (D-089 D7) and reaches other open settings pages live.

- `GET /identity/settings`, `PUT` (If-Match; "0" for the first save): session timeouts for the
  console and the portal, and whether a first sign-in creates the person.
- `/identity/sso`: the tenant's SAML and OpenID Connect set-ups (REQ-SEC-007, 008): list, add
  (Idempotency-Key), change, remove (If-Match), a test sign-in, switch on and off. The client
  secret is accepted, never returned.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.identity_access.domain import sso as sso_rules
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
)
from app.modules.identity_access.infra.models import MAX_IDLE_SECONDS, MIN_IDLE_SECONDS
from app.modules.identity_access.service import identity_settings, sso, sso_test
from app.modules.organization import get_current_tenant
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing `identity.manage`."},
    404: {"model": ProblemDetail, "description": "No such set-up or test."},
    409: {"model": ProblemDetail, "description": "Stale If-Match."},
    422: {"model": ProblemDetail, "description": "Problems by field, with the limits."},
}
Manage = Annotated[Subject, Depends(require_permission("identity.manage"))]

router = APIRouter(
    prefix="/identity",
    tags=["identity"],
    dependencies=[Depends(rate_limit("identity"))],
    responses=RESPONSES,
)

# The limits are checked by the service, which names them at the field (D-091).
IDLE = Field(description=f"Idle timeout in seconds ({MIN_IDLE_SECONDS} to {MAX_IDLE_SECONDS}).")


class IdentitySettingsBody(BaseModel):
    """Sessions per app and people creation on first sign-in.

    Absolute: at least the idle timeout; at most 7 days for the console, 30 for the portal.
    """

    model_config = ConfigDict(extra="forbid")

    console_idle_seconds: Annotated[int, IDLE]
    console_absolute_seconds: int = Field(description="Absolute session length in seconds.")
    portal_idle_seconds: Annotated[int, IDLE]
    portal_absolute_seconds: int = Field(description="Absolute session length in seconds.")
    create_people_on_sign_in: bool = Field(
        description="A first sign-in creates the person as requester (REQ-SEC-013)."
    )


class IdentitySettingsOut(IdentitySettingsBody):
    """The settings and their version (0: never saved, the Appendix A defaults)."""

    model_config = ConfigDict(extra="ignore")

    version: int = Field(description="Send back as If-Match.")


def _out(view: identity_settings.IdentitySettingsView) -> IdentitySettingsOut:
    return IdentitySettingsOut(**view.__dict__)


@router.get("/settings", summary="Sign-in settings")
async def get_settings(session: TenantSession, subject: Manage) -> IdentitySettingsOut:
    """The tenant's sign-in settings, or the defaults (version 0)."""
    del subject
    return _out(await identity_settings.get_identity_settings(session))


@router.put("/settings", summary="Save sign-in settings")
async def put_settings(  # noqa: PLR0913, PLR0917 - FastAPI parameters: body, version, response, session, subject, audit note
    body: IdentitySettingsBody,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote, audited("identity.settings_changed", object_type="identity_settings")
    ],
) -> IdentitySettingsOut:
    """Session limits apply to sessions begun from now on; people creation at once."""
    saved, details = await identity_settings.save_identity_settings(
        session,
        identity_settings.IdentitySettingsView(**body.model_dump(), version=version),
        expected_version=version,
    )
    note.object_id = str(subject.tenant_id)
    note.details = details
    note.skip = not details
    set_etag(response, saved.version)
    return _out(saved)


# --- single sign-on (REQ-SEC-007, REQ-SEC-008) ----------------------------------------------------


def _admin(request: Request) -> IdentityAdmin | None:
    return getattr(request.app.state, "identity_admin", None)


def _allow_loopback(request: Request) -> bool:
    return bool(request.app.state.settings.sso_fetch_allow_loopback)


Admin = Annotated[IdentityAdmin | None, Depends(_admin)]
AllowLoopback = Annotated[bool, Depends(_allow_loopback)]


class SsoMappingBody(BaseModel):
    """Which claim (OpenID Connect) or attribute (SAML) carries each field; empty = not used."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=300)
    first_name: str = Field(min_length=1, max_length=300)
    last_name: str = Field(min_length=1, max_length=300)
    department: str | None = Field(default=None, max_length=300)
    site: str | None = Field(default=None, max_length=300)


class SsoBody(BaseModel):
    """A set-up.

    OpenID Connect: issuer, client ID and secret (write-only), scopes. SAML: the provider's
    metadata (text or URL), or its sign-in address and certificate.
    """

    model_config = ConfigDict(extra="forbid")

    preset: Literal["entra", "okta", "google", "oidc", "saml"]
    display_name: str = Field(description="Shown on the sign-in button.")
    domains: list[str] = Field(description="The email domains of the people who use it.")
    email_redirect: bool = Field(
        default=False, description="Once on, send people of these domains straight to it."
    )
    mapping: SsoMappingBody | None = None
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = Field(
        default=None, description="Write-only; leave out to keep the saved one."
    )
    scopes: str = sso_rules.DEFAULT_SCOPES
    metadata: str | None = Field(default=None, description="SAML metadata XML (write-only).")
    metadata_url: str | None = None
    sso_url: str | None = None
    slo_url: str | None = None
    certificate: str | None = None
    entity_id: str | None = None

    def values(self) -> sso.SsoInput:
        """The service's input."""
        data = self.model_dump(exclude={"mapping"})
        mapping = None if self.mapping is None else sso_rules.Mapping(**self.mapping.model_dump())
        return sso.SsoInput(**data, mapping=mapping)


class SsoCheckOut(BaseModel):
    """The last connection check."""

    ok: bool
    problems: list[str] = Field(description="Codes: labels `sso_check.<code>`.")
    checked_at: datetime
    certificate_not_after: datetime | None = None


class SsoOut(BaseModel):
    """A set-up as saved (never the secret)."""

    id: uuid.UUID
    protocol: Literal["oidc", "saml"]
    preset: Literal["entra", "okta", "google", "oidc", "saml"]
    display_name: str
    state: Literal["draft", "tested", "on", "off"]
    domains: list[str]
    email_redirect: bool
    settings: dict[str, Any] = Field(description="Connection settings shown again, and mapping.")
    last_check: SsoCheckOut | None
    tested_at: datetime | None
    switched_on_at: datetime | None
    service_provider_metadata_url: str = Field(
        description="SupportX's SAML metadata for this set-up (give it to the provider)."
    )
    redirect_uri: str = Field(description="Where the provider sends people back (OIDC).")
    version: int


class SsoListOut(BaseModel):
    """The tenant's set-ups."""

    items: list[SsoOut]


def _sso_out(request: Request, view: sso.SsoView) -> SsoOut:
    issuer = (request.app.state.settings.oidc_issuer or "").rstrip("/")
    return SsoOut(
        id=view.id,
        protocol=view.protocol,  # type: ignore[arg-type]  # the column holds only these codes
        preset=view.preset,  # type: ignore[arg-type]  # idem
        display_name=view.display_name,
        state=view.state,  # type: ignore[arg-type]  # idem
        domains=view.domains,
        email_redirect=view.email_redirect,
        settings=view.settings,
        last_check=None if view.last_check is None else SsoCheckOut(**view.last_check),
        tested_at=view.tested_at,
        switched_on_at=view.switched_on_at,
        service_provider_metadata_url=issuer + view.service_provider_metadata_path,
        redirect_uri=f"{issuer}/broker/{view.alias}/endpoint",
        version=view.version,
    )


@router.get("/sso", summary="Single sign-on set-ups")
async def list_sso(request: Request, session: TenantSession, subject: Manage) -> SsoListOut:
    """Every set-up of the tenant, oldest first."""
    del subject
    return SsoListOut(items=[_sso_out(request, v) for v in await sso.list_providers(session)])


@router.post(
    "/sso",
    summary="Add a single sign-on set-up",
    status_code=status.HTTP_201_CREATED,
    response_model=SsoOut,
    responses={201: {"model": SsoOut, "description": "Created in draft (or replayed)."}},
)
async def create_sso(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    body: SsoBody,
    request: Request,
    session: TenantSession,
    subject: Manage,
    admin: Admin,
    allow_loopback: AllowLoopback,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("sso.added", object_type="sso_provider")],
) -> Response:
    """Checked and saved in draft: test it, then switch it on."""
    del subject
    note.skip = True

    async def operation() -> Created:
        view = await sso.create_provider(
            session, admin, body.values(), allow_loopback=allow_loopback
        )
        note.skip = False
        note.object_id = str(view.id)
        note.details = {"preset": view.preset, "domains": view.domains}
        return Created(_sso_out(request, view), {"ETag": f'"{view.version}"'})

    return await idempotency.run(body, operation)


@router.get("/sso/{provider_id}", summary="One single sign-on set-up")
async def get_sso(
    provider_id: uuid.UUID,
    request: Request,
    session: TenantSession,
    subject: Manage,
    response: Response,
) -> SsoOut:
    """The set-up, with its last check."""
    del subject
    view = await sso.get_provider(session, provider_id)
    set_etag(response, view.version)
    return _sso_out(request, view)


@router.put(
    "/sso/{provider_id}",
    summary="Change a single sign-on set-up",
    dependencies=[audited("sso.updated", object_type="sso_provider", object_param="provider_id")],
)
async def update_sso(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    provider_id: uuid.UUID,
    body: SsoBody,
    version: ExpectedVersion,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Manage,
    admin: Admin,
    allow_loopback: AllowLoopback,
) -> SsoOut:
    """A connection change sends it back to draft (an "on" set-up: switch it off first)."""
    del subject
    view = await sso.update_provider(
        session,
        admin,
        provider_id,
        body.values(),
        expected_version=version,
        allow_loopback=allow_loopback,
    )
    set_etag(response, view.version)
    return _sso_out(request, view)


@router.post(
    "/sso/{provider_id}/switch-on",
    summary="Switch a single sign-on set-up on",
    dependencies=[
        audited("sso.switched_on", object_type="sso_provider", object_param="provider_id")
    ],
)
async def switch_on(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    provider_id: uuid.UUID,
    version: ExpectedVersion,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Manage,
    admin: Admin,
) -> SsoOut:
    """Shown on the tenant's sign-in page (needs a passed test since the last change)."""
    del subject
    view = await sso.switch_provider(session, admin, provider_id, on=True, expected_version=version)
    set_etag(response, view.version)
    return _sso_out(request, view)


@router.post(
    "/sso/{provider_id}/switch-off",
    summary="Switch a single sign-on set-up off",
    dependencies=[
        audited("sso.switched_off", object_type="sso_provider", object_param="provider_id")
    ],
)
async def switch_off(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    provider_id: uuid.UUID,
    version: ExpectedVersion,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Manage,
    admin: Admin,
) -> SsoOut:
    """Nobody signs in through it until it is switched on again."""
    del subject
    view = await sso.switch_provider(
        session, admin, provider_id, on=False, expected_version=version
    )
    set_etag(response, view.version)
    return _sso_out(request, view)


@router.delete(
    "/sso/{provider_id}",
    summary="Remove a single sign-on set-up",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[audited("sso.removed", object_type="sso_provider", object_param="provider_id")],
)
async def remove_sso(
    provider_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    admin: Admin,
) -> Response:
    """Deletes it in Keycloak; the email domains only it claimed are given back."""
    del subject
    await sso.remove_provider(session, admin, provider_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SsoTestStartedOut(BaseModel):
    """Open `url` in a pop-up; poll the result with `test_id`."""

    test_id: str
    url: str


class SsoTestIdentityOut(BaseModel):
    """What the provider sent for the person who signed in."""

    email: str | None
    name: str | None
    department: str | None = None
    site: str | None = None


class SsoTestResultOut(BaseModel):
    """pending, passed or failed (`reason`: labels `sso_test.<reason>`)."""

    status: Literal["pending", "passed", "failed"]
    reason: str | None
    identity: SsoTestIdentityOut | None


@router.post("/sso/{provider_id}/tests", summary="Start a test sign-in")
async def start_test(
    provider_id: uuid.UUID, request: Request, session: TenantSession, subject: Manage
) -> SsoTestStartedOut:
    """No session and no person are created by the test; the tested sign-in ends at once."""
    auth = getattr(request.app.state, "auth", None)
    if auth is None or _admin(request) is None:
        raise IdentityAdminNotConfigured
    view = await sso.test_target(session, provider_id)
    tenant = await get_current_tenant(session)
    started = await sso_test.start(
        auth,
        tenant_id=subject.tenant_id,
        slug=tenant.slug,
        admin_user_id=subject.user_id,
        provider_id=view.id,
        alias=view.alias,
    )
    return SsoTestStartedOut(test_id=started.test_id, url=started.url)


@router.get("/sso/{provider_id}/tests/{test_id}", summary="Result of a test sign-in")
async def test_result(
    provider_id: uuid.UUID, test_id: str, request: Request, subject: Manage
) -> SsoTestResultOut:
    """Pending until the pop-up comes back (or the provider's answer is refused)."""
    auth = getattr(request.app.state, "auth", None)
    if auth is None:
        raise IdentityAdminNotConfigured
    found = await sso_test.result(
        auth, test_id, tenant_id=subject.tenant_id, provider_id=provider_id
    )
    return SsoTestResultOut.model_validate(found)
