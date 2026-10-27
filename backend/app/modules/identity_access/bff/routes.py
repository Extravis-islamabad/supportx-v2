"""BFF endpoints under /api/v1/auth (D-009). Tokens never leave the server."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.authorization import Scope, public_route
from app.core.entitlements import entitlement_exempt
from app.core.errors import ServiceUnavailable, Unauthenticated
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import RequestFacts, record, record_alone
from app.modules.identity_access.bff.cookies import clear_session_cookie, set_session_cookie
from app.modules.identity_access.domain.identity import FormDensity, NavLayout, UserType
from app.modules.identity_access.domain.session import Session
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service import password_reset as password_reset_service
from app.modules.identity_access.service import sso
from app.modules.identity_access.service.auth import (
    AccountAction,
    AuthService,
    EnrolFirst,
    LoginAddress,
    LoginFailure,
)
from app.modules.identity_access.service.sso_test import TestFinished
from app.modules.organization import tenant_for_host
from app.shared.realtime import (
    CENTRIFUGO_STATE,
    SESSION_ENDED,
    CentrifugoClient,
    CentrifugoError,
    realtime_user,
)

if TYPE_CHECKING:
    from app.core.database import Database
    from app.modules.identity_access.service.policy import PolicyService

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def get_auth(request: Request) -> AuthService:
    """The process AuthService; 503 `auth_not_configured` when login is not set up."""
    service: AuthService | None = getattr(request.app.state, "auth", None)
    if service is None:
        raise ServiceUnavailable(code="auth_not_configured")
    return service


Auth = Annotated[AuthService, Depends(get_auth)]


async def current_session(request: Request, auth: Auth) -> tuple[str, Session]:
    """The request's valid session (CSRF-checked for state-changing methods) or 401."""
    found = await auth.session_for(request)
    if found is None:
        raise Unauthenticated
    return found


CurrentSession = Annotated[tuple[str, Session], Depends(current_session)]


class UserOut(BaseModel):
    """The logged-in user (in the active tenant). `roles`: SupportX role keys."""

    id: uuid.UUID
    email: str
    display_name: str
    locale: Literal["en", "ar", "ur"] = Field(
        description="UI language: the one picked in the app, else the identity provider's."
    )
    user_type: UserType
    roles: list[str]
    nav_layout: NavLayout = Field(
        default=NavLayout.TOP, description="The user's navigation layout preference."
    )
    form_density: FormDensity = Field(
        default=FormDensity.COMFORTABLE, description="The user's record form layout preference."
    )
    time_zone: str | None = Field(
        default=None,
        description="The user's time zone preference (IANA); null: use the browser's.",
    )


class TenantOut(BaseModel):
    """A tenant the user belongs to."""

    id: uuid.UUID
    name: str


class EffectivePermission(BaseModel):
    """A permission the user holds (WP-016), for showing and hiding UI. The server enforces it."""

    key: str
    scope: Scope = Field(description="The broadest scope held.")
    scopes: list[Scope]
    conditional: bool = Field(description="Some grants only apply to records matching a rule.")


class MeResponse(BaseModel):
    """Session summary for the UI.

    `csrf_token` must be sent as X-CSRF-Token on every POST/PUT/PATCH/DELETE; it is tied to this
    session and changes when the session does. `user.roles` are the user's SupportX role keys
    (D-029: SupportX, not Keycloak, decides access); `permissions` their effective permissions.
    """

    user: UserOut
    tenant: TenantOut
    tenants: list[TenantOut]
    csrf_token: str
    permissions: list[EffectivePermission] = Field(default_factory=list)
    mfa_due_at: datetime | None = Field(
        default=None,
        description="MFA is required here and not set up yet: set it up by then (a reminder).",
    )


class SwitchTenantRequest(BaseModel):
    """Which of the user's tenants to make active."""

    tenant_id: uuid.UUID


@router.get(
    "/login",
    summary="Start login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
)
@entitlement_exempt
@public_route
async def login(
    request: Request,
    auth: Auth,
    app: Annotated[Literal["console", "portal"], Query()] = "console",
    return_to: Annotated[str | None, Query(alias="returnTo", max_length=2048)] = None,
) -> RedirectResponse:
    """Redirect the browser to Keycloak (authorization code + PKCE, state, nonce).

    `returnTo` must be a same-origin relative path; anything else lands on `/`. On a tenant's
    own address (subdomain or verified custom domain) the sign-in is for that tenant (WP-017).
    """
    # This browser still holds a session cookie whose session is gone (timed out or ended):
    # Keycloak's own session must not sign it back in without the password (REQ-SEC-029).
    previous = request.cookies.get(auth.cookie_name)
    timed_out = previous is not None and await auth.store.get_session(previous) is None
    url = await auth.start_login(app, return_to, await _address(request), reauthenticate=timed_out)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/callback",
    summary="Finish login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
)
@entitlement_exempt
@public_route
async def callback(  # noqa: PLR0913, PLR0917 - FastAPI parameters: the callback's query
    request: Request,
    auth: Auth,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    kc_action_status: str | None = None,
) -> RedirectResponse:
    """Keycloak sends the browser here. Creates a new session and sets the session cookie.

    Failures are RFC 9457 problems for API clients. A browser navigation (Accept: text/html) is
    sent back to its app with `?auth_error=<code>` instead, which the app shows as a translated
    message (CLAUDE.md rule d: no raw codes or JSON on screen).
    """
    try:
        result = await auth.complete_login(
            code=code,
            state=state,
            error=error,
            previous_session_id=request.cookies.get(auth.cookie_name),
            host=request.headers.get("host"),
            action_status=kc_action_status,
        )
    except LoginFailure as failure:
        if "text/html" not in request.headers.get("accept", ""):
            raise failure.problem from failure
        query = urlencode({"auth_error": failure.problem.instance_code})
        base = auth.base_url(failure.app)
        if failure.origin is not None:  # back to the tenant's own address (WP-017)
            base = failure.origin + urlsplit(base).path.rstrip("/")
        target = f"{base}/?{query}"
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    if isinstance(result, EnrolFirst):  # past the MFA grace period: Keycloak makes them enrol
        return RedirectResponse(result.redirect_to, status_code=status.HTTP_303_SEE_OTHER)
    if isinstance(result, TestFinished):  # an admin's SSO test: no session, back to the pop-up
        await _record_sso_test(request, result)
        return RedirectResponse(result.redirect_to, status_code=status.HTTP_303_SEE_OTHER)
    await _audit_session(request, result.session, "session.signed_in")
    response = RedirectResponse(result.redirect_to, status_code=status.HTTP_302_FOUND)
    set_session_cookie(response, auth.settings, result.session_id)
    return response


class PasswordResetIn(BaseModel):
    """The address of the account whose password was forgotten."""

    email: str = Field(max_length=320)


@router.post(
    "/password-reset",
    summary="Forgot password: send a reset e-mail",
    status_code=status.HTTP_202_ACCEPTED,
)
@entitlement_exempt
@public_route
async def password_reset(body: PasswordResetIn, request: Request, auth: Auth) -> Response:
    """Always 202, whatever the address: nothing can be learned about accounts.

    Within the limits (5 per address and 20 per network address per hour) Keycloak sends its
    set-password e-mail in the tenant's brand, valid 60 minutes, once (REQ-SEC-006, 035; D-099).
    """
    database: Database | None = getattr(request.app.state, "db", None)
    if database is not None:
        address = await _address(request)
        tenant = await _address_tenant(request, address)
        await password_reset_service.request_reset(
            database,
            request.app.state.settings,
            auth.store,
            auth.identity_admin,
            password_reset_service.ResetRequest(
                email=body.email,
                network=request.client.host if request.client else None,
                tenant_id=tenant,
            ),
        )
    return Response(status_code=status.HTTP_202_ACCEPTED)


async def _address_tenant(request: Request, address: LoginAddress | None) -> uuid.UUID | None:
    """The tenant whose own address this is (its brand for the reset e-mail), else None."""
    if address is None:
        return None
    database: Database | None = getattr(request.app.state, "db", None)
    host = request.headers.get("host")
    if database is None or host is None:
        return None
    found = await tenant_for_host(database, host, request.app.state.settings.tenant_base_domain)
    return None if found is None else found.tenant_id


async def _record_sso_test(request: Request, finished: TestFinished) -> None:
    """A passed test marks the set-up tested; every test is audited, in the tenant, as the admin."""
    database: Database | None = getattr(request.app.state, "db", None)
    if database is None:
        return
    context = TenantContext(finished.tenant_id, finished.admin_user_id)
    async with database.tenant_session(context) as session:
        if finished.passed:
            await sso.mark_tested(session, finished.provider_id, finished.admin_user_id)
        await record(
            session,
            action_code="sso.tested",
            facts=RequestFacts.of(request, client="console"),
            object_type="sso_provider",
            object_id=finished.provider_id,
            details={"passed": finished.passed},
        )


async def _address(request: Request) -> LoginAddress | None:
    """The tenant whose own address this is (REQ-SEC-004), as a sign-in hint; else None."""
    database: Database | None = getattr(request.app.state, "db", None)
    host = request.headers.get("host")
    if database is None or host is None:
        return None
    try:
        found = await tenant_for_host(database, host, request.app.state.settings.tenant_base_domain)
    except SQLAlchemyError:
        log.warning("tenant_for_host_failed")  # the sign-in still works, unbranded
        return None
    return LoginAddress(host, found.slug) if found is not None else None


async def _audit_session(request: Request, session: Session, action_code: str) -> None:
    """Audit a sign-in, sign-out or tenant switch (REQ-AUD-002) in its own transaction.

    A failure to write the entry is logged as an error but does not lock people out.
    """
    database: Database | None = getattr(request.app.state, "db", None)
    if database is None:
        return
    context = TenantContext(uuid.UUID(session.tenant_id), uuid.UUID(session.user_id))
    try:
        await record_alone(
            database,
            context,
            action_code=action_code,
            facts=RequestFacts.of(request, client=session.client),
            object_type="user",
            object_id=session.user_id,
        )
    except Exception:
        log.exception("audit_session_entry_failed", action=action_code)


@router.get("/me", summary="Current session")
@entitlement_exempt
@public_route
async def me(found: CurrentSession, request: Request) -> MeResponse:
    """The logged-in user, active tenant, switchable tenants, CSRF token and permissions."""
    _session_id, session = found
    return await _describe(request, session)


async def _describe(request: Request, session: Session) -> MeResponse:
    """Session summary plus the user's SupportX roles and effective permissions."""
    described = AuthService.describe(session)
    # Preferences live in the users row (they change after login, on any device).
    database: Database | None = getattr(request.app.state, "db", None)
    if database is not None:
        context = TenantContext(session.tenant_uuid, session.user_uuid)
        async with database.tenant_session(context) as db:
            row = (
                await db.execute(
                    select(
                        User.nav_layout, User.form_density, User.time_zone, User.ui_locale
                    ).where(User.id == session.user_uuid)
                )
            ).first()
        described["user"]["nav_layout"] = (row.nav_layout if row else None) or NavLayout.TOP
        described["user"]["form_density"] = (
            row.form_density if row else None
        ) or FormDensity.COMFORTABLE
        described["user"]["time_zone"] = row.time_zone if row else None
        # The language picked in the app wins over Keycloak's (QA BUG-04): it follows the user.
        if row is not None and row.ui_locale is not None:
            described["user"]["locale"] = row.ui_locale
    policy: PolicyService | None = getattr(request.app.state, "policy", None)
    if policy is None:
        described["user"]["roles"] = []
        return MeResponse.model_validate(described)
    subject = await policy.subject(session.tenant_uuid, session.user_uuid)
    described["user"]["roles"] = sorted(subject.role_keys)
    described["permissions"] = [
        {
            "key": key,
            "scope": subject.broadest_scope(key),
            "scopes": sorted({g.scope for g in grants}),
            "conditional": all(g.condition is not None for g in grants),
        }
        for key, grants in subject.grants.items()
    ]
    return MeResponse.model_validate(described)


async def _end_realtime(request: Request, session: Session) -> None:
    """Cut the user's realtime connections in the session's tenant (best effort, WP-011).

    Their tokens would otherwise keep a socket open until they expire. Other browsers of the same
    user in that tenant reconnect on their own, with tokens from their own sessions.
    """
    client: CentrifugoClient | None = getattr(request.app.state, CENTRIFUGO_STATE, None)
    if client is None:
        return
    try:
        await client.disconnect(
            realtime_user(session.tenant_uuid, session.user_uuid), SESSION_ENDED, "session ended"
        )
    except CentrifugoError:
        log.warning("realtime_disconnect_failed", exc_info=True)


@router.get(
    "/account-action",
    summary="Change password or MFA on the sign-in service's pages",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
)
@entitlement_exempt
@public_route
async def account_action(
    found: CurrentSession,
    request: Request,
    auth: Auth,
    action: Annotated[AccountAction, Query()],
    return_to: Annotated[str | None, Query(alias="returnTo", max_length=2048)] = None,
) -> RedirectResponse:
    """From My account (REQ-SEC-028): Keycloak asks for the password, then shows its page.

    `password` changes the password, `mfa` sets up an authenticator app, `recovery_codes` makes
    new recovery codes. The browser comes back to `returnTo` with `account_action` and `status`
    (success, cancelled, error) and a fresh session; the password never passes through SupportX.
    """
    _session_id, session = found
    address = await _address(request)
    app: Literal["console", "portal"] = "portal" if session.client == "portal" else "console"
    url = await auth.start_login(app, return_to, address, account_action=action)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.post("/logout", summary="Log out", status_code=status.HTTP_204_NO_CONTENT)
@entitlement_exempt
@public_route
async def logout(found: CurrentSession, auth: Auth, request: Request) -> Response:
    """End this session and the Keycloak session; clears the cookie."""
    session_id, session = found
    await auth.logout(session_id, session)
    await _audit_session(request, session, "session.signed_out")
    await _end_realtime(request, session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, auth.settings)
    return response


@router.post("/switch-tenant", summary="Switch active tenant")
@entitlement_exempt
@public_route
async def switch_tenant(
    body: SwitchTenantRequest,
    found: CurrentSession,
    auth: Auth,
    response: Response,
    request: Request,
) -> MeResponse:
    """Make another of the user's tenants active. Issues a new session ID and CSRF token."""
    session_id, session = found
    new_id, switched = await auth.switch_tenant(session_id, session, body.tenant_id)
    await _audit_session(request, switched, "session.tenant_switched")
    set_session_cookie(response, auth.settings, new_id)
    await _end_realtime(request, session)  # the old tenant's connection
    return await _describe(request, switched)
