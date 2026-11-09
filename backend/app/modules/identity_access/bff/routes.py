"""BFF endpoints under /api/v1/auth (D-009). Tokens never leave the server."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.authorization import Scope, public_route
from app.core.entitlements import entitlement_exempt
from app.core.errors import NotFound, ServiceUnavailable, Unauthenticated
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import RequestFacts, record, record_alone
from app.modules.identity_access.api.sessions import ListedSessionOut, listed_out
from app.modules.identity_access.bff.cookies import clear_session_cookie, set_session_cookie
from app.modules.identity_access.domain.identity import (
    DEFAULT_TEXT_SCALE,
    Digits,
    FormDensity,
    NavLayout,
    ThemeMode,
    TimeFormat,
    UrduScript,
    UserType,
    WeekStart,
)
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
    PortalInstead,
)
from app.modules.identity_access.service.sso_test import TestFinished
from app.modules.identity_access.service.users import requester_only
from app.modules.organization import (
    RegionalDefaults,
    offered_languages,
    regional_defaults,
    tenant_for_host,
)
from app.shared.history import CLIENT_HEADER
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
        default=NavLayout.SIDE, description="The user's navigation layout preference."
    )
    form_density: FormDensity = Field(
        default=FormDensity.COMFORTABLE, description="The user's record form layout preference."
    )
    time_zone: str | None = Field(
        default=None,
        description="Time zone (IANA): the person's own, else their site's, else the tenant's.",
    )
    # WP-042 (REQ-ADM-058, 059, 062): what to apply, the person's choice or else the default
    # read now; `chosen` lists the ones the person set themselves (the rest follow the default).
    theme_mode: ThemeMode | None = Field(
        default=None, description="Null: not chosen, the browser decides."
    )
    text_scale: int = Field(default=DEFAULT_TEXT_SCALE, description="Text size in percent.")
    week_start: WeekStart = Field(default="monday", description="First day of the week.")
    # A pattern shown as written (dd/mm/yyyy), not a code with a label: a plain string.
    date_format: str = Field(default="dd/mm/yyyy", description="How dates are written.")
    time_format: TimeFormat = Field(default="24h", description="12 or 24 hours.")
    digits: Digits = Field(default="western", description="Digits on screen (D-135).")
    urdu_script: UrduScript = Field(default="naskh", description="How Urdu is set (D-137).")
    chosen: list[str] = Field(
        default_factory=list, description="The preferences the person set (not defaults)."
    )


# Preferences a person may leave to the default (WP-042): applied at read time, never copied.
_PERSONAL = (
    "theme_mode",
    "text_scale",
    "week_start",
    "date_format",
    "time_format",
    "digits",
    "urdu_script",
)
# Their `chosen` entries too: NULL since 0071 means the default (side bar, comfortable).
_LAYOUT = ("nav_layout", "form_density")


def _personal(row: Any, regional: RegionalDefaults) -> dict[str, Any]:  # noqa: ANN401 - a Row
    """The time zone, theme, text size and formats to apply, and which the person chose."""
    own: dict[str, Any] = {} if row is None else {n: getattr(row, n) for n in _PERSONAL}
    own["time_zone"] = row.time_zone if row is not None else None
    defaults = {
        "theme_mode": None,
        "text_scale": DEFAULT_TEXT_SCALE,
        "week_start": regional.week_start,
        "date_format": regional.date_format,
        "time_format": regional.time_format,
        "digits": "western",
        "urdu_script": "naskh",
        "time_zone": regional.time_zone,
    }
    applied = {n: own[n] if own.get(n) is not None else d for n, d in defaults.items()}
    layout = {} if row is None else {n: getattr(row, n) for n in _LAYOUT}
    applied["chosen"] = sorted(n for n, v in {**own, **layout}.items() if v is not None)
    return applied


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
    idle_timeout_seconds: int | None = Field(
        default=None,
        description="Signed out after this long without activity (warned 2 minutes ahead).",
    )
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
    if isinstance(result, PortalInstead):  # a requester on the console: no session, the portal
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


async def _audit_session(
    request: Request, session: Session, action_code: str, reason: str | None = None
) -> None:
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
            **({} if reason is None else {"details": {"reason": reason}}),
        )
    except Exception:
        log.exception("audit_session_entry_failed", action=action_code)


@router.get("/me", summary="Current session")
@entitlement_exempt
@public_route
async def me(found: CurrentSession, request: Request) -> MeResponse:
    """The logged-in user, active tenant, switchable tenants, CSRF token and permissions."""
    session_id, session = found
    described = await _describe(request, session)
    console = session.client == "console"
    if console or request.headers.get(CLIENT_HEADER, "").lower() == "console":
        await _refuse_requester_only(request, session_id, session, end=console)
    return described


async def _refuse_requester_only(
    request: Request, session_id: str, session: Session, *, end: bool
) -> None:
    """D-129: requester-only people never use the console (the same rule as at sign-in).

    A console session of theirs (made before the rule, or before their last staff role went)
    ends here, recorded and audited. Where both apps share a host the portal's cookie reaches
    the console too: the console's calls are refused and the portal session stays. Fails closed:
    with no database to ask, the console is refused.
    """
    database: Database | None = getattr(request.app.state, "db", None)
    if database is not None and not await requester_only(
        database, session.tenant_uuid, session.user_uuid
    ):
        return
    if end:
        auth: AuthService = request.app.state.auth
        await auth.end_session(session_id, session)
        await _audit_session(
            request, session, "session.signed_out", reason="console_requester_only"
        )
        # The cookie goes with the session. Left behind, the portal's sign-in would take the
        # ended session for a timed-out one and make Keycloak ask for the password again
        # (REQ-SEC-029's rule), although their Keycloak session stands (PortalInstead).
        cleared = Response()
        clear_session_cookie(cleared, auth.settings)
        raise Unauthenticated(
            code="console_requester_only", headers={"set-cookie": cleared.headers["set-cookie"]}
        )
    raise Unauthenticated(code="console_requester_only")


async def _describe(request: Request, session: Session) -> MeResponse:
    """Session summary plus the user's SupportX roles and effective permissions."""
    described = AuthService.describe(session)
    auth: AuthService | None = getattr(request.app.state, "auth", None)
    if auth is not None:  # this session's own limit (its tenant's, when it began; REQ-SEC-029)
        idle, _ = session.limits(idle=auth.idle, absolute=auth.absolute)
        described["idle_timeout_seconds"] = int(idle.total_seconds())
    # Preferences live in the users row (they change after login, on any device).
    database: Database | None = getattr(request.app.state, "db", None)
    if database is not None:
        context = TenantContext(session.tenant_uuid, session.user_uuid)
        async with database.tenant_session(context) as db:
            row = (
                await db.execute(
                    select(
                        User.nav_layout,
                        User.form_density,
                        User.time_zone,
                        User.ui_locale,
                        User.site_id,
                        *(getattr(User, name) for name in _PERSONAL),
                    ).where(User.id == session.user_uuid)
                )
            ).first()
            offered, default = await offered_languages(db)
            regional = await regional_defaults(db, row.site_id if row else None)
        described["user"]["nav_layout"] = (row.nav_layout if row else None) or NavLayout.SIDE
        described["user"]["form_density"] = (
            row.form_density if row else None
        ) or FormDensity.COMFORTABLE
        described["user"].update(_personal(row, regional))
        # The language picked in the app wins over Keycloak's (QA BUG-04): it follows the user.
        if row is not None and row.ui_locale is not None:
            described["user"]["locale"] = row.ui_locale
        # A language the tenant switched off falls back to its default (WP-042, REQ-ADM-052).
        if described["user"].get("locale") not in offered:
            described["user"]["locale"] = default
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


@router.get("/sessions", summary="Your signed-in browsers and devices")
@entitlement_exempt
@public_route  # like /me: the BFF's own session check (CurrentSession) answers 401 without one
async def my_sessions(found: CurrentSession, auth: Auth) -> list[ListedSessionOut]:
    """Every session you have open in this organisation, the one you use now marked."""
    session_id, session = found
    rows = await auth.listed_sessions(
        uuid.UUID(session.tenant_id), uuid.UUID(session.user_id), current=session_id
    )
    return listed_out(rows)


@router.delete(
    "/sessions/{listed_id}",
    summary="Sign out one of your browsers or devices",
    status_code=status.HTTP_204_NO_CONTENT,
)
@entitlement_exempt
@public_route  # CurrentSession: a valid session (CSRF-checked, a DELETE) or 401
async def end_my_session(
    listed_id: str, found: CurrentSession, auth: Auth, request: Request
) -> Response:
    """That session ends at once: its next request answers 401. 404 if it isn't yours or live."""
    _session_id, session = found
    ended = await auth.end_listed_session(
        uuid.UUID(session.tenant_id), uuid.UUID(session.user_id), listed_id
    )
    if not ended:
        raise NotFound(code="session_not_found")
    await _audit_session(request, session, "session.ended", reason="by_you")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
