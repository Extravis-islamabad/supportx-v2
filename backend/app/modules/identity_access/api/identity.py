"""Sign-in and security settings (WP-039; REQ-SEC-013, REQ-SEC-017, REQ-SEC-029; D-094).

Admin > Sign-in and security reads and saves these with `identity.manage`; every change is
audited (D-089 D7) and reaches other open settings pages live.

- `GET /identity/settings`, `PUT` (If-Match; "0" for the first save; fields left out are kept):
  session timeouts for the console and the portal, whether a first sign-in creates the person,
  how long invitations last, the password policy; `POST /identity/settings/password-policy/
  apply` after the worker could not apply it.
- `/identity/sso`: the tenant's SAML and OpenID Connect set-ups (REQ-SEC-007, 008): list, add
  (Idempotency-Key), change, remove (If-Match), a test sign-in, switch on and off. The client
  secret is accepted, never returned.
"""

import uuid
from dataclasses import replace
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
from app.modules.identity_access.service import (
    identity_settings,
    invitations,
    password_reset,
    sso,
    sso_test,
)
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
    """Sessions per app, people creation, invitations and the password policy.

    Every field is optional: a field left out keeps its saved value, so each part of the screen
    saves only its own fields. Absolute: at least the idle timeout; at most 7 days for the
    console, 30 for the portal.
    """

    model_config = ConfigDict(extra="forbid")

    console_idle_seconds: Annotated[int | None, IDLE] = None
    console_absolute_seconds: int | None = Field(
        default=None, description="Absolute session length in seconds."
    )
    portal_idle_seconds: Annotated[int | None, IDLE] = None
    portal_absolute_seconds: int | None = Field(
        default=None, description="Absolute session length in seconds."
    )
    create_people_on_sign_in: bool | None = Field(
        default=None, description="A first sign-in creates the person as requester (REQ-SEC-013)."
    )
    invitation_valid_days: int | None = Field(
        default=None, description="How long an invitation link works (1 to 30 days)."
    )
    # REQ-SEC-005: installation-wide; refused on multi-tenant installations.
    password_min_length: int | None = Field(default=None, description="8 to 64 characters.")
    password_upper: bool | None = Field(default=None, description="Needs an upper-case letter.")
    password_lower: bool | None = Field(default=None, description="Needs a lower-case letter.")
    password_digits: bool | None = Field(default=None, description="Needs a digit.")
    password_special: bool | None = Field(default=None, description="Needs a special character.")
    password_history: int | None = Field(
        default=None, description="The last N passwords are refused (0 to 24; 0 = none)."
    )
    password_expiry_days: int | None = Field(
        default=None, description="Days a password lasts (0 to 365; 0 = never expires)."
    )
    password_breached_check: bool | None = Field(
        default=None, description="Refuse passwords on the installation's breached list."
    )
    mfa_grace_days: int | None = Field(
        default=None, description="Days to set up MFA once it is required (0 to 30)."
    )


class IdentitySettingsOut(BaseModel):
    """The settings and their version (0: never saved, the Appendix A defaults)."""

    console_idle_seconds: int
    console_absolute_seconds: int
    portal_idle_seconds: int
    portal_absolute_seconds: int
    create_people_on_sign_in: bool
    invitation_valid_days: int
    password_min_length: int
    password_upper: bool
    password_lower: bool
    password_digits: bool
    password_special: bool
    password_history: int
    password_expiry_days: int
    password_breached_check: bool
    mfa_grace_days: int
    password_policy_editable: bool = Field(
        description="False on multi-tenant installations: the platform's policy applies."
    )
    password_policy_state: Literal["default", "applying", "applied", "failed"] = Field(
        description="default: never edited here; applying until written into Keycloak."
    )
    password_policy_error: str | None = Field(
        description="Why the policy was not applied (a code the screen explains)."
    )
    version: int = Field(description="Send back as If-Match.")


def _out(view: identity_settings.IdentitySettingsView, request: Request) -> IdentitySettingsOut:
    return IdentitySettingsOut(
        **view.__dict__, password_policy_editable=not _require_domain_proof(request)
    )


@router.get("/settings", summary="Sign-in settings")
async def get_settings(
    request: Request, session: TenantSession, subject: Manage
) -> IdentitySettingsOut:
    """The tenant's sign-in settings, or the defaults (version 0)."""
    del subject
    return _out(await identity_settings.get_identity_settings(session), request)


@router.put("/settings", summary="Save sign-in settings")
async def put_settings(  # noqa: PLR0913, PLR0917 - FastAPI parameters: body, version, request, response, session, subject, audit note
    body: IdentitySettingsBody,
    version: ExpectedVersion,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote, audited("identity.settings_changed", object_type="identity_settings")
    ],
) -> IdentitySettingsOut:
    """Save the fields sent; the others keep their values.

    Session limits apply to sessions begun from now on; people creation at once; the password
    policy once the worker has written it into Keycloak (`password_policy_state`).
    """
    current = await identity_settings.get_identity_settings(session)
    saved, details = await identity_settings.save_identity_settings(
        session,
        replace(current, **body.model_dump(exclude_none=True)),
        expected_version=version,
        multi_tenant=_require_domain_proof(request),
    )
    note.object_id = str(subject.tenant_id)
    note.details = details
    note.skip = not details
    set_etag(response, saved.version)
    return _out(saved, request)


@router.post("/settings/password-policy/apply", summary="Apply the password policy again")
async def apply_password_policy(
    request: Request,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote,
        audited("identity.password_policy_reapplied", object_type="identity_settings"),
    ],
) -> IdentitySettingsOut:
    """After `failed`: the worker writes the saved policy into Keycloak again."""
    saved = await identity_settings.apply_password_policy_again(
        session, multi_tenant=_require_domain_proof(request)
    )
    note.object_id = str(subject.tenant_id)
    return _out(saved, request)


# --- single sign-on (REQ-SEC-007, REQ-SEC-008) ----------------------------------------------------


def _admin(request: Request) -> IdentityAdmin | None:
    return getattr(request.app.state, "identity_admin", None)


def _allow_loopback(request: Request) -> bool:
    return bool(request.app.state.settings.sso_fetch_allow_loopback)


def _require_domain_proof(request: Request) -> bool:
    return bool(request.app.state.settings.multi_tenant)


Admin = Annotated[IdentityAdmin | None, Depends(_admin)]
AllowLoopback = Annotated[bool, Depends(_allow_loopback)]
RequireDomainProof = Annotated[bool, Depends(_require_domain_proof)]


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
    require_domain_proof: RequireDomainProof,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("sso.added", object_type="sso_provider")],
) -> Response:
    """Checked and saved in draft: test it, then switch it on."""
    del subject
    note.skip = True

    async def operation() -> Created:
        view = await sso.create_provider(
            session,
            admin,
            body.values(),
            allow_loopback=allow_loopback,
            require_domain_proof=require_domain_proof,
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
    require_domain_proof: RequireDomainProof,
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
        require_domain_proof=require_domain_proof,
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


# --- invitations and password resets (REQ-SEC-006, REQ-SEC-018..020; D-099) ---------------------

ManagePeople = Annotated[Subject, Depends(require_permission("users.manage"))]


class InvitationIn(BaseModel):
    """Who to invite: a person the tenant knows who has not signed in yet (WP-021)."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID


class InvitationOut(BaseModel):
    """An invitation (`expired`: pending past its expiry; ask for a new one)."""

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    status: Literal["pending", "accepted", "expired", "revoked"]
    delivery: Literal["email", "existing_account"] = Field(
        description="existing_account: they already have a password and can sign in now."
    )
    sent_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    sends: int
    version: int


class InvitationListOut(BaseModel):
    """The tenant's invitations, newest first."""

    items: list[InvitationOut]


def _invitation_out(view: invitations.InvitationView) -> InvitationOut:
    return InvitationOut(**view.__dict__)


@router.get("/invitations", summary="Invitations")
async def list_invitations(
    session: TenantSession, subject: ManagePeople, user_id: uuid.UUID | None = None
) -> InvitationListOut:
    """Who was invited, when, until when, and what became of it: the newest 200, or one's."""
    del subject
    found = await invitations.list_invitations(session, user_id=user_id)
    return InvitationListOut(items=[_invitation_out(v) for v in found])


@router.post(
    "/invitations",
    summary="Invite a person",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationOut,
    responses={201: {"model": InvitationOut, "description": "Sent (or replayed)."}},
)
async def create_invitation(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    body: InvitationIn,
    request: Request,
    session: TenantSession,
    subject: ManagePeople,
    admin: Admin,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("invitation.sent", object_type="invitation")],
) -> Response:
    """Keycloak sends the set-password e-mail from the tenant's sender, in the person's language."""
    del subject
    note.skip = True

    async def operation() -> Created:
        view = await invitations.invite(session, request.app.state.settings, admin, body.user_id)
        note.skip = False
        note.object_id = str(view.id)
        note.details = {"user_id": str(view.user_id), "delivery": view.delivery}
        return Created(_invitation_out(view), {"ETag": f'"{view.version}"'})

    return await idempotency.run(body, operation)


@router.post(
    "/invitations/{invitation_id}/resend",
    summary="Send an invitation again",
    dependencies=[
        audited("invitation.resent", object_type="invitation", object_param="invitation_id")
    ],
)
async def resend_invitation(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    invitation_id: uuid.UUID,
    version: ExpectedVersion,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: ManagePeople,
    admin: Admin,
) -> InvitationOut:
    """A new e-mail and a new expiry."""
    del subject
    view = await invitations.resend(
        session, request.app.state.settings, admin, invitation_id, expected_version=version
    )
    set_etag(response, view.version)
    return _invitation_out(view)


@router.post(
    "/invitations/{invitation_id}/revoke",
    summary="Revoke an invitation",
    dependencies=[
        audited("invitation.revoked", object_type="invitation", object_param="invitation_id")
    ],
)
async def revoke_invitation(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    invitation_id: uuid.UUID,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: ManagePeople,
    admin: Admin,
) -> InvitationOut:
    """Its link stops working at once (REQ-SEC-020 AC2)."""
    del subject
    view = await invitations.revoke(session, admin, invitation_id, expected_version=version)
    set_etag(response, view.version)
    return _invitation_out(view)


@router.post(
    "/people/{user_id}/require-new-password",
    summary="Require a new password at the next sign-in",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited("user.password_reset_forced", object_type="user", object_param="user_id")
    ],
)
async def require_new_password(
    user_id: uuid.UUID,
    request: Request,
    session: TenantSession,
    subject: ManagePeople,
    admin: Admin,
) -> Response:
    """The person sets a new password at their next sign-in; their sessions end now (SEC-006)."""
    person = await password_reset.signed_in_subject(session, user_id)
    await password_reset.force_reset(admin, person)
    auth = getattr(request.app.state, "auth", None)
    if auth is not None:
        await auth.end_sessions(subject.tenant_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
