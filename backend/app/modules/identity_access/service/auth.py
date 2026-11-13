"""BFF authentication use cases (architecture.md §11.1, ADR-006, D-009, D-010; WP-006).

Login: GET /auth/login stores a one-time login state (PKCE verifier, nonce, returnTo) and sends
the browser to Keycloak. The callback exchanges the code on the back channel, verifies the ID
token (RS256 signature, issuer, audience, expiry, nonce), maps organization memberships to
tenants, provisions the user just-in-time, and creates a brand-new session (no fixation).

Every later request: the opaque cookie → encrypted session record in Valkey → idle/absolute
expiry checks → CSRF check on state-changing methods → silent token refresh when the access token
expires (if Keycloak refuses, the session ends) → TenantContext for the database.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode, urlsplit

import valkey.exceptions
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import (
    AppError,
    BadRequest,
    Conflict,
    PermissionDenied,
    RateLimited,
    ServiceUnavailable,
    Unauthenticated,
)
from app.core.logging import get_logger
from app.core.recent_auth import RECENT_AUTH_WINDOW, SignInFreshness, record_freshness
from app.core.tenancy import TenantContext
from app.modules.audit import RequestFacts
from app.modules.identity_access.domain import quick_sign_in as quick
from app.modules.identity_access.domain.identity import (
    ClaimsError,
    Identity,
    identity_from,
    safe_return_to,
    validate_claims,
)
from app.modules.identity_access.domain.mobile import (
    HANDOFF_TTL,
    SESSION_HEADER,
    MobileStart,
    app_return,
    verifier_matches,
)
from app.modules.identity_access.domain.network import NetworkApp, address_of
from app.modules.identity_access.domain.place import place_of
from app.modules.identity_access.domain.session import Session, TenantChoice
from app.modules.identity_access.domain.sign_in import (
    SignInApp,
    SignInMethod,
    SignInOutcome,
    device,
)
from app.modules.identity_access.domain.sign_in_policy import (
    BREAK_GLASS_NEEDS_MFA,
    SSO_REQUIRED,
    judge,
    requires_supportx_mfa,
)
from app.modules.identity_access.domain.sso import DEPARTMENT_ATTRIBUTE, SITE_ATTRIBUTE
from app.modules.identity_access.events import BreakGlassSignedIn
from app.modules.identity_access.infra.geoip import GeoIp
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminNotConfigured,
    IdentityAdminUnavailable,
)
from app.modules.identity_access.infra.models import SESSION_LIMITS
from app.modules.identity_access.infra.oidc import (
    ClientCredentials,
    IdentityProviderUnavailable,
    InvalidTokenError,
    OidcClient,
    PkcePair,
    TokenRejectedError,
    TokenSet,
)
from app.modules.identity_access.infra.store import SessionStore, public_id
from app.modules.identity_access.service import (
    api_keys,
    break_glass,
    confirm,
    sign_in_log,
    site_networks,
    sso_test,
)
from app.modules.identity_access.service import mfa as mfa_service
from app.modules.identity_access.service import sso as sso_service
from app.modules.identity_access.service.network_rules import admitted, tenant_network_rules
from app.modules.identity_access.service.users import (
    known_user_id,
    provision_user,
    record_logout,
    requester_only,
    tenant_name,
)
from app.shared.api.ratelimit import client_address
from app.shared.clock import Clock
from app.shared.events import record_event

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.modules.identity_access.infra.keycloak_admin import IdentityAdmin

log = get_logger(__name__)
# REQ-SEC-034: the address is outside the tenant's allow-list for this app.
IP_NOT_ALLOWED = "ip_not_allowed"
# Refusals that end Keycloak's own session too: the person is not let in here at all.
SIGN_IN_REFUSALS = frozenset({IP_NOT_ALLOWED, SSO_REQUIRED, BREAK_GLASS_NEEDS_MFA})


def _identity_of(session: Session) -> Identity:
    """The person a session stands for, as the policy reads them (no token on a switch)."""
    return Identity(
        subject=session.subject,
        email=session.email,
        display_name=session.display_name,
        locale=session.locale,
        roles=tuple(session.roles),
        memberships=(),
        keycloak_session_id=session.keycloak_session_id,
        identity_provider=session.identity_provider,
    )


def _iso_seconds(epoch: int | None) -> str | None:
    """Seconds since the epoch as an ISO time (UTC), or None."""
    return None if epoch is None else datetime.fromtimestamp(epoch, UTC).isoformat()


def _stored_method(session: Session) -> SignInMethod | None:
    """The method a session began with (None for sessions from before S1b)."""
    return SignInMethod(session.sign_in_method) if session.sign_in_method else None


def sign_in_method(identity: Identity) -> SignInMethod:
    """Single sign-on when the verified token names an identity provider (`sx_idp`).

    Else the password: a directory sign-in is a password one here (LDAP checks it in Keycloak).
    """
    return SignInMethod.SINGLE_SIGN_ON if identity.identity_provider else SignInMethod.PASSWORD


@dataclass(frozen=True)
class Attempt:
    """Where a sign-in comes from, for the allow-list and the sign-in log (WP-057 S1a)."""

    app: "AppName"
    ip: str | None
    user_agent: str | None
    mobile: bool = False
    # The organization alias of the tenant address the sign-in started on (its pending login).
    organization: str | None = None

    def facts(
        self,
        outcome: SignInOutcome,
        user_id: uuid.UUID | None,
        *,
        reason: str | None = None,
        method: SignInMethod | None = None,
        identity_provider: str | None = None,
    ) -> sign_in_log.SignInFacts:
        """The log's facts for this attempt; the method from the verified token where known."""
        return sign_in_log.SignInFacts(
            outcome=outcome,
            app=SignInApp.MOBILE if self.mobile else SignInApp(self.app),
            method=method or (SignInMethod.MOBILE if self.mobile else SignInMethod.UNKNOWN),
            identity_provider=identity_provider,
            user_id=user_id,
            reason=reason,
            ip=self.ip,
            user_agent=self.user_agent,
        )


AppName = Literal["console", "portal"]
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"
CALLBACK_PATH = "/api/v1/auth/callback"
LOGIN_STATE_TTL = timedelta(minutes=10)
REFRESH_LOCK_TTL = timedelta(seconds=15)
TOUCH_INTERVAL = timedelta(seconds=60)
MAX_SESSION = timedelta(seconds=max(limit["max_absolute"] for limit in SESSION_LIMITS.values()))


def _client_app(session: Session) -> AppName:
    return "portal" if session.client == "portal" else "console"


_EPOCH = datetime.fromtimestamp(0, UTC)


def _moment(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None


# On the person's own channel when their session list changed (ADR-044 item 5).
SESSIONS_CHANGED = "identity_access.sessions_changed"


@dataclass(frozen=True, slots=True)
class ListedSession:
    """One of a person's sessions, as My account and admins see it (never its secret id)."""

    id: str
    client: str
    platform: str | None
    app_version: str | None
    started_at: datetime | None
    last_used_at: datetime | None
    current: bool
    ip: str | None = None
    device: str | None = None
    place: dict[str, Any] | None = None  # domain/place.py's stored form


def user_key(tenant_id: str, user_id: str) -> str:
    """The session store's key for a person in a tenant."""
    return f"{tenant_id}:{user_id}"


@dataclass(frozen=True)
class LoginAddress:
    """A tenant's own address the login started on (WP-017): its host and organization alias."""

    host: str
    organization: str


class LoginFailure(Exception):
    """A login that could not complete: which app it was for, and the problem to report."""

    def __init__(
        self,
        app: AppName,
        problem: AppError,
        origin: str | None = None,
        *,
        mobile_return: str | None = None,
    ) -> None:
        super().__init__(problem.instance_code)  # the code is a stable identifier, not prose
        self.app = app
        self.problem = problem
        self.origin = origin  # a tenant's own address the login started on (WP-017), if any
        # A mobile sign-in (ADR-044): the browser goes back to the app with the error code.
        self.mobile_return = mobile_return


# My account's changes, as Keycloak's application-initiated actions (proved on 26.8.1).
ACCOUNT_ACTIONS = {
    "password": "UPDATE_PASSWORD",
    "mfa": "CONFIGURE_TOTP",
    "recovery_codes": "CONFIGURE_RECOVERY_AUTHN_CODES",
}
AccountAction = Literal["password", "mfa", "recovery_codes"]
ACTION_STATUSES = frozenset({"success", "cancelled", "error"})


class MfaEnrolmentDue(Exception):
    """The person is past their MFA grace period here: they enrol before they get a session."""


@dataclass(frozen=True)
class EnrolFirst:
    """No session yet: the browser signs in again and Keycloak makes the person enrol MFA."""

    redirect_to: str


@dataclass(frozen=True)
class LoginStarted:
    """Where the browser goes to sign in, and what binds the sign-in to that browser.

    `binding` is a fresh random token for the login-binding cookie (audit row 4): the pending
    login keeps only its SHA-256, and the callback is refused unless the browser presents it.
    None for the mobile app's sign-in, which its S256 challenge binds instead (ADR-044).
    """

    url: str
    state: str
    binding: str | None


def binding_digest(token: str) -> str:
    """The SHA-256 of a login-binding token: what the pending login stores, never the token."""
    return hashlib.sha256(token.encode()).hexdigest()


def _bound_to_this_browser(pending: dict[str, Any], binding: str | None) -> bool:
    """True when the callback's browser holds the token its login started with.

    Login CSRF (audit row 4): without this, anyone could start a sign-in to their own account,
    stop at Keycloak's redirect and send the callback link to someone else, whose browser would
    then be signed in as them. Constant-time compare: the digest is a secret's stand-in.
    """
    expected = pending.get("binding")
    if not isinstance(expected, str) or binding is None:
        return False
    return hmac.compare_digest(expected, binding_digest(binding))


def _check_same_browser(  # noqa: PLR0913 - the callback's facts, keyword-only
    pending: dict[str, Any],
    app: AppName,
    *,
    mobile: bool,
    mobile_return: str | None,
    binding: str | None,
    host: str | None,
) -> None:
    """Refuse a callback that is not finishing where its sign-in started (LoginFailure)."""
    origin = pending.get("origin")
    if not mobile and not _bound_to_this_browser(pending, binding):
        raise LoginFailure(app, BadRequest(code="login_not_this_browser"), origin)
    if origin is not None and urlsplit(origin).netloc != host:
        # Started on another address than it finished on: never move a session across.
        raise LoginFailure(app, BadRequest(code="login_failed"), mobile_return=mobile_return)


@dataclass(frozen=True)
class PortalInstead:
    """A requester signed in on the console: no console session; the portal signs them in.

    REQ-PRT-001 AC1 (WP-028, lane B's review): a requester never lands on the console. Their
    Keycloak session stands, so the portal's own sign-in completes without a second prompt.
    """

    redirect_to: str


class LoginResult:
    """A completed login: the new session and where to send the browser.

    `mobile`: the browser goes back to the app with a one-time hand-off code instead of a
    session cookie (ADR-044); the app exchanges the code for the session ID.
    """

    def __init__(
        self, session_id: str, session: Session, redirect_to: str, *, mobile: bool = False
    ) -> None:
        self.session_id = session_id
        self.session = session
        self.redirect_to = redirect_to
        self.mobile = mobile


class AuthService:
    """Owns login, sessions, logout and tenant switching for one process."""

    def __init__(  # noqa: PLR0913 - collaborators injected for testability
        self,
        *,
        settings: Settings,
        store: SessionStore,
        oidc: OidcClient,
        database: Database | None,
        clock: Clock,
        cookie_name: str,
    ) -> None:
        self.settings = settings
        self.store = store
        self.oidc = oidc
        self.database = database
        self.clock = clock
        self.cookie_name = cookie_name
        # The approximate sign-in place (WP-057 S2b, D-170): the mounted GeoIP file, if any.
        self.geo = GeoIp(settings.geoip_db)
        self.idle = timedelta(seconds=settings.session_idle_timeout_seconds)
        self.absolute = timedelta(seconds=settings.session_absolute_timeout_seconds)
        # Set by the module startup once the policy service exists (WP-016).
        self.on_roles_mapped: Callable[[uuid.UUID], Awaitable[None]] | None = None
        # Set by the module startup: Keycloak's admin API as the identity service account.
        self.identity_admin: IdentityAdmin | None = None
        # Set by the module startup: closes a person's live connections in a tenant (WP-039).
        self.end_realtime: Callable[[uuid.UUID, uuid.UUID], Awaitable[None]] | None = None
        # Set by the module startup: tells the person's open screens their session list changed
        # (ADR-044 item 5), best effort.
        self.sessions_changed: Callable[[uuid.UUID, uuid.UUID], Awaitable[None]] | None = None

    # --- clients and origins -------------------------------------------------------------------

    def base_url(self, app: AppName) -> str:
        """Public base URL of the console or portal, path included (`https://host/portal`)."""
        return (self.settings.console_url if app == "console" else self.settings.portal_url).rstrip(
            "/"
        )

    def origin(self, app: AppName, host: str | None = None) -> str:
        """Scheme and host of the console or portal: where the BFF and its callback live.

        Both UIs may share one host (the portal under /portal, WP-014); the API is always at the
        host's /api, so the callback and the Origin check use the origin, not the base path. A
        tenant's own address (`host`, WP-017) keeps the configured scheme.
        """
        parts = urlsplit(self.base_url(app))
        return f"{parts.scheme}://{host or parts.netloc}"

    def landing(self, app: AppName, return_to: str, origin: str | None = None) -> str:
        """Where the browser goes after login: its own path, else the UI's home.

        `/` (with or without a query or fragment, as the console's hand-off to the portal sends
        `/?from=console`) is the UI's home: under its base path when both UIs share one host
        (`https://host/portal/?from=console`), never the host's root, which is the console's.
        """
        base_origin = origin or self.origin(app)
        parts = urlsplit(return_to)
        if parts.path == "/" and not parts.netloc:
            home = base_origin + urlsplit(self.base_url(app)).path.rstrip("/") + "/"
            query = f"?{parts.query}" if parts.query else ""
            fragment = f"#{parts.fragment}" if parts.fragment else ""
            return home + query + fragment
        return base_origin + return_to

    def client(self, app: AppName, origin: str | None = None) -> ClientCredentials:
        """The confidential OIDC client of the console or portal."""
        if app == "console":
            client_id, secret = (
                self.settings.oidc_console_client_id,
                self.settings.oidc_console_client_secret,
            )
        else:
            client_id, secret = (
                self.settings.oidc_portal_client_id,
                self.settings.oidc_portal_client_secret,
            )
        if secret is None:
            raise ServiceUnavailable(code="auth_not_configured")
        return ClientCredentials(
            client_id, secret.get_secret_value(), (origin or self.origin(app)) + CALLBACK_PATH
        )

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Origins allowed to send state-changing requests with the session cookie."""
        return frozenset({self.origin("console"), self.origin("portal")})

    # --- login ---------------------------------------------------------------------------------

    async def start_login(  # noqa: PLR0913 - the keyword-only options of one login
        self,
        app: AppName,
        return_to: str | None,
        address: LoginAddress | None = None,
        *,
        reauthenticate: bool = False,
        account_action: str | None = None,
        mobile: MobileStart | None = None,
    ) -> LoginStarted:
        """Remember a one-time login state; Keycloak's authorization URL and the browser binding.

        On a tenant's own address (WP-017, REQ-SEC-004) the callback stays on that address and
        Keycloak is asked for that tenant's organization: its sign-in page shows the tenant's
        brand, and the token names only that organization. A hint, never access: someone who is
        not a member gets no organization and the usual `no_organization` refusal.

        `reauthenticate` (a session of this browser timed out, REQ-SEC-029): Keycloak asks for
        the password again instead of reusing its own, longer session.

        `mobile` (ADR-044): the mobile app's S256 challenge, platform and version. The login ends
        with a hand-off code for the app instead of a session cookie, and no browser binding: the
        app's challenge binds it (only the app holds the verifier), and the system browser that
        finishes it may not be the one that started it.
        """
        origin = self.origin(app, address.host) if address is not None else None
        state, nonce, pkce = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
            PkcePair.generate(),
        )
        binding = secrets.token_urlsafe(32) if mobile is None else None
        await self.store.put_login(
            state,
            {
                "app": app,
                "nonce": nonce,
                "verifier": pkce.verifier,
                "return_to": safe_return_to(return_to),
                "origin": origin,
                "organization": address.organization if address is not None else None,
                "account_action": account_action,
                "binding": binding_digest(binding) if binding is not None else None,
                **(mobile.pending() if mobile is not None else {}),
            },
            LOGIN_STATE_TTL,
        )
        url = await self.oidc.authorization_url(
            self.client(app, origin),
            state=state,
            nonce=nonce,
            pkce=pkce,
            organization=address.organization if address is not None else None,
            # A password change asks for the current password first (REQ-SEC-028 AC2); setting
            # MFA up too (D-104): only the person may add an authenticator to their account.
            prompt="login" if reauthenticate or account_action is not None else None,
            action=None if account_action is None else ACCOUNT_ACTIONS[account_action],
        )
        return LoginStarted(url, state, binding)

    async def refused_callback(self, state: str | None, refusal: AppError) -> LoginFailure:
        """A callback the address limit refused, sent back to the app its sign-in started in.

        The pending login is read, never spent: a retry within its 10 minutes still works. Only
        for the rate limit (429), when Valkey has just answered; with Valkey down (503
        `sign_in_unavailable`) the state cannot be read, so the browser goes to the console as
        before, and an unknown state (a scripted flood) does too.
        """
        if not isinstance(refusal, RateLimited) or not state:
            return LoginFailure("console", refusal)
        try:
            pending = await self.store.peek_login(state)
        except (valkey.exceptions.ValkeyError, OSError):
            pending = None
        if pending is None or pending.get("test"):
            return LoginFailure("console", refusal)
        app: AppName = "portal" if pending.get("app") == "portal" else "console"
        mobile = MobileStart.from_pending(pending) is not None
        mobile_return = self.settings.mobile_redirect_uri if mobile else None
        return LoginFailure(app, refusal, pending.get("origin"), mobile_return=mobile_return)

    async def complete_login(  # noqa: PLR0913 - keyword-only parts of the callback
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
        previous_session_id: str | None,
        binding: str | None = None,
        host: str | None = None,
        action_status: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> (
        "LoginResult | EnrolFirst | PortalInstead | sso_test.TestFinished | confirm.ConfirmFinished"
    ):
        """Finish the OIDC callback and create a fresh session (or finish an SSO test).

        Any failure is raised as LoginFailure carrying the app it belongs to, so the BFF can send a
        browser back to the right app with a translatable error code.

        `binding` is the token from the browser's login-binding cookie. A browser sign-in is
        refused with `login_not_this_browser` unless it matches the one its login started with.
        Two sign-ins are not bound: the mobile app's (its S256 challenge binds it, ADR-044) and an
        admin's SSO test, which is opened in a private window by design (WP-039) and creates no
        session.
        """
        pending = await self.store.take_login(state) if state else None
        if pending is None:
            raise LoginFailure("console", BadRequest(code="invalid_login_state"))  # noqa: EM101 - a code, not a message
        if pending.get("test") or pending.get("confirm"):
            return await self._finish_side_flow(
                pending,
                code=code,
                error=error,
                binding=binding,
                host=host,
                current_session_id=previous_session_id,
                client_ip=client_ip,
                user_agent=user_agent,
            )
        app: AppName = "portal" if pending["app"] == "portal" else "console"
        origin = pending.get("origin")
        mobile = MobileStart.from_pending(pending)
        mobile_return = self.settings.mobile_redirect_uri if mobile is not None else None
        _check_same_browser(
            pending,
            app,
            mobile=mobile is not None,
            mobile_return=mobile_return,
            binding=binding,
            host=host,
        )
        if error or not code:
            raise LoginFailure(
                app, BadRequest(code="login_failed"), origin, mobile_return=mobile_return
            )
        try:
            attempt = Attempt(
                app,
                client_ip,
                user_agent,
                mobile=mobile is not None,
                organization=pending.get("organization"),
            )
            session = await self._login(app, code, pending, attempt)
        except MfaEnrolmentDue:
            # Keycloak now holds the enrol actions on the account; signing in again (its own
            # session still stands) runs them before anything else (REQ-SEC-024 AC2).
            return EnrolFirst(self._login_again(app, origin, pending["return_to"], mobile))
        except AppError as exc:
            raise LoginFailure(app, exc, origin, mobile_return=mobile_return) from exc
        if previous_session_id and mobile is None:
            # Rotation: the browser's pre-login session (if any) dies here. Never on the app's
            # sign-in: the system browser's session is not the app's, and an unbound callback
            # link must not be able to end someone's browser session.
            await self.store.delete_session(previous_session_id)
        if app == "console" and await self._requester_only(session):
            # The console's paths mean nothing in the portal: its home, never return_to.
            log.info("login_sent_to_portal", subject=session.subject, tenant_id=session.tenant_id)
            if mobile is not None:
                # The mobile app serves both (D-160): it signs in again for a portal session.
                # Keycloak's own session stands, so there is no second prompt.
                return PortalInstead(self._login_again("portal", origin, "/", mobile))
            return PortalInstead(self.landing("portal", "/", origin))
        finished = await self._finish_login(session, app, pending, action_status)
        if session.break_glass and self.database is not None:
            # REQ-SEC-009 AC3: the other tenant admins are told, through the outbox.
            async with self.database.tenant_session(
                TenantContext(session.tenant_uuid, session.user_uuid)
            ) as tx:
                await record_event(
                    tx,
                    BreakGlassSignedIn(user_id=session.user_uuid),
                    aggregate_id=session.user_uuid,
                    aggregate_version=1,
                )
        facts = attempt.facts(
            SignInOutcome.SUCCESS,
            session.user_uuid,
            method=_stored_method(session),
            identity_provider=session.identity_provider,
        )
        await sign_in_log.record(self.database, session.tenant_uuid, facts)
        return finished

    async def _finish_side_flow(  # noqa: PLR0913 - the callback's parts, keyword-only
        self,
        pending: dict[str, Any],
        *,
        code: str | None,
        error: str | None,
        binding: str | None,
        host: str | None,
        current_session_id: str | None,
        client_ip: str | None,
        user_agent: str | None,
    ) -> "sso_test.TestFinished | confirm.ConfirmFinished":
        """A callback that creates no session: an admin's SSO test, or a confirmation.

        The SSO test runs in a private window by design (WP-039), so it has no binding. A
        confirmation (REQ-SEC-027) must come from the browser that started it (lane B A3).
        """
        if pending.get("test"):  # an admin's test of a single sign-on set-up (WP-039)
            return await sso_test.finish(self, pending, code=code, error=error)
        app: AppName = "portal" if pending.get("app") == "portal" else "console"
        _check_same_browser(
            pending, app, mobile=False, mobile_return=None, binding=binding, host=host
        )
        return await confirm.finish(
            self,
            pending,
            code=code,
            error=error,
            current_session_id=current_session_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )

    async def _finish_login(
        self, session: Session, app: AppName, pending: dict[str, Any], action_status: str | None
    ) -> LoginResult:
        """Save the new session; say where the browser goes: the app (mobile) or the UI."""
        mobile = MobileStart.from_pending(pending)
        if mobile is not None:  # the person's session list names the phone (ADR-044 item 5)
            session = replace(
                session, device_platform=mobile.platform, app_version=mobile.app_version
            )
        session_id = await self._save_new(session)
        log.info(
            "login",
            subject=session.subject,
            tenant_id=session.tenant_id,
            client=app,
            via_app=mobile is not None,  # not mobile=: SENSITIVE_KEY_PARTS redacts it
        )
        if mobile is not None:
            handoff = secrets.token_urlsafe(32)
            await self.store.put_handoff(
                handoff, {"session_id": session_id, "challenge": mobile.challenge}, HANDOFF_TTL
            )
            redirect = app_return(self.settings.mobile_redirect_uri, handoff=handoff)
            return LoginResult(session_id, session, redirect, mobile=True)
        origin = pending.get("origin")
        landing = self.landing(app, pending["return_to"], origin)
        if pending.get("account_action"):  # back to My account with Keycloak's result
            outcome = action_status if action_status in ACTION_STATUSES else "error"
            query = urlencode({"account_action": pending["account_action"], "status": outcome})
            landing += ("&" if "?" in landing else "?") + query
        return LoginResult(session_id, session, landing)

    def _login_again(
        self, app: AppName, origin: str | None, return_to: str, mobile: MobileStart | None
    ) -> str:
        """The BFF's own login address for another round (MFA enrolment, console to portal)."""
        params = {"app": app, "returnTo": return_to}
        if mobile is not None:
            params |= mobile.query()
        return f"{origin or self.origin(app)}/api/v1/auth/login?{urlencode(params)}"

    async def exchange_handoff(self, handoff: str, verifier: str) -> tuple[str, Session]:
        """The session a mobile hand-off code stands for (ADR-044), or 401 `handoff_invalid`.

        The code is spent on the first try, right or wrong: a guessed or replayed code never
        gets a second chance. Unknown, expired, used and mismatched codes look the same.
        """
        record = await self.store.take_handoff(handoff)
        if record is None or not verifier_matches(verifier, str(record["challenge"])):
            raise Unauthenticated(code="handoff_invalid")
        session_id = str(record["session_id"])
        data = await self.store.get_session(session_id)
        if data is None:  # ended in the minute between sign-in and exchange
            raise Unauthenticated(code="handoff_invalid")
        return session_id, Session.from_dict(data)

    def presented_session_id(self, request: Request) -> str | None:
        """The session ID a request carries: the browser's cookie, else the mobile header."""
        return request.cookies.get(self.cookie_name) or request.headers.get(SESSION_HEADER)

    async def quick_sign_in(self, who: quick.Persona, tenant_id: uuid.UUID) -> "LoginResult":
        """Dev-only quick sign-in (D-151): a showcase persona, through Keycloak, then a session.

        The caller has checked the dev-only setting, the local address and the showcase tenant.
        The password grant gives real Keycloak tokens; the TOTP code comes from the persona's
        dev-only authenticator secret (never logged). From there the normal path: the ID token
        is checked, the person provisioned, the MFA policy applied, and a session saved.
        Keycloak's refusal is a 403 naming the reason, never a 500 (the page shows it).
        """
        password = self.settings.showcase_password
        key = self.settings.showcase_totp_key
        if password is None or key is None:
            raise ServiceUnavailable(code="quick_sign_in_not_configured")
        client = self.client(who.app)
        code: str | None = None
        if who.enrolled:
            step = await self._claim_step(who.email)
            code = quick.totp(quick.totp_value(key.get_secret_value().encode(), who.email), step)
        try:
            tokens = await self.oidc.password_grant(
                client, username=who.email, password=password.get_secret_value(), totp=code
            )
        except TokenRejectedError as exc:
            reason = quick.refusal(exc.error, exc.description)
            log.warning("quick_sign_in_refused", persona=who.code, reason=reason)
            raise PermissionDenied(code="quick_sign_in_refused", params={"reason": reason}) from exc
        identity = await self._identity(tokens, client, nonce=None)
        if not any(m.tenant_id == tenant_id for m in identity.memberships):
            await self._end_keycloak_session(client, tokens.refresh_token)
            raise PermissionDenied(code="quick_sign_in_refused", params={"reason": "not_showcase"})
        try:
            session = await self._new_session(identity, tokens, who.app, active=tenant_id)
        except MfaEnrolmentDue as exc:
            await self._end_keycloak_session(client, tokens.refresh_token)
            raise PermissionDenied(
                code="quick_sign_in_refused", params={"reason": "mfa_setup_required"}
            ) from exc
        if session.tenant_id != str(tenant_id):
            await self._end_keycloak_session(client, tokens.refresh_token)
            raise PermissionDenied(code="quick_sign_in_refused", params={"reason": "not_showcase"})
        session_id = await self._save_new(session)
        log.info("quick_sign_in", persona=who.code, tenant_id=session.tenant_id, client=who.app)
        return LoginResult(session_id, session, self.landing(who.app, "/", None))

    async def _claim_step(self, email: str) -> int:
        """A TOTP time step no earlier quick sign-in used, or a 409 to wait a moment."""
        ttl = timedelta(seconds=quick.TOTP_PERIOD * 3)
        for step in quick.candidate_steps(quick.time_step(self.clock.now())):
            if await self.store.claim_totp_step(email, step, ttl):
                return step
        # Both codes of this window are used: a wrong code would count toward the lock.
        raise Conflict(code="quick_sign_in_wait", params={"seconds": quick.TOTP_PERIOD})

    async def _requester_only(self, session: Session) -> bool:
        if self.database is None:  # pragma: no cover - a login needs the database
            return False
        return await requester_only(self.database, session.tenant_uuid, session.user_uuid)

    async def _login(
        self, app: AppName, code: str, pending: dict[str, Any], attempt: "Attempt"
    ) -> Session:
        client = self.client(app, pending.get("origin"))
        try:
            tokens = await self.oidc.exchange_code(client, code=code, verifier=pending["verifier"])
        except TokenRejectedError as exc:
            raise BadRequest(code="login_failed") from exc
        identity = await self._identity(tokens, client, nonce=pending["nonce"])
        if not identity.memberships:
            await self._end_keycloak_session(client, tokens.refresh_token)
            raise PermissionDenied(code="no_organization")
        try:
            return await self._new_session(identity, tokens, app, active=None, attempt=attempt)
        except PermissionDenied as exc:
            if exc.instance_code in SIGN_IN_REFUSALS:  # as no_organization: Keycloak's ends too
                await self._end_keycloak_session(client, tokens.refresh_token)
            raise

    async def _identity(
        self, tokens: TokenSet, client: ClientCredentials, *, nonce: str | None
    ) -> Identity:
        try:
            identity, _claims = await self._verified(tokens, client, nonce=nonce)
        except (InvalidTokenError, ClaimsError) as exc:
            log.warning("id_token_rejected", reason=str(exc))
            raise BadRequest(code="login_failed") from exc
        return identity

    async def _verified(
        self, tokens: TokenSet, client: ClientCredentials, *, nonce: str | None
    ) -> tuple[Identity, dict[str, Any]]:
        claims = await self.oidc.verify_id_token(tokens.id_token)
        validate_claims(
            claims, issuer=self.oidc.issuer, client_id=client.client_id, nonce=nonce,
            now=self.clock.now(),
        )  # fmt: skip
        return identity_from(claims), dict(claims)

    async def verified_identity(
        self, tokens: TokenSet, client: ClientCredentials, *, nonce: str
    ) -> tuple[Identity, dict[str, Any]]:
        """The verified, nonce-bound identity and its claims (a confirmation, REQ-SEC-027).

        A token that fails any check is refused (PermissionDenied), never trusted.
        """
        try:
            return await self._verified(tokens, client, nonce=nonce)
        except (InvalidTokenError, ClaimsError) as exc:
            log.warning("id_token_rejected", reason=str(exc))
            raise PermissionDenied(code="reauth_failed") from exc

    async def session_for_confirmed(self, request: Request) -> Session | None:
        """The browser's session as stored now (after a confirmation), or None."""
        session_id = request.cookies.get(self.cookie_name)
        record = await self.store.get_session(session_id) if session_id else None
        return Session.from_dict(record) if record else None

    async def save_existing(self, session_id: str, session: Session) -> bool:
        """Replace a session only if it still exists (never bring back a signed-out one)."""
        return await self._save(session_id, session, only_if_present=True)

    async def end_keycloak_session_quietly(self, app: AppName, session: Session) -> None:
        """End a session's Keycloak session through its refresh token; a failure is logged."""
        try:
            await self._end_keycloak_session(self.client(app), session.refresh_token)
        except IdentityProviderUnavailable:
            log.warning("keycloak_logout_failed", subject=session.subject)

    async def provider_reauthenticates(self, session: Session) -> bool:
        """Whether this session's identity provider re-authenticates on request (REQ-SEC-027).

        OIDC providers SupportX creates pass `prompt` and `max_age` on (sso.py); a SAML provider
        is not proven to, so its people cannot confirm (fail closed, lane B A4). No provider
        (a password sign-in): Keycloak asks for the password itself.
        """
        if session.identity_provider is None:
            return True
        if self.database is None:
            return False
        return (
            await sso_service.provider_protocol(
                self.database, session.tenant_uuid, session.identity_provider
            )
            == "oidc"
        )

    async def _admit(self, tenant_id: uuid.UUID, app: AppName, address: str | None) -> bool:
        """Whether the tenant's allow-list for `app` admits `address` (REQ-SEC-034)."""
        if self.database is None:  # pragma: no cover - a sign-in needs the database
            return True
        rules = await tenant_network_rules(self.database, tenant_id)
        return admitted(rules, NetworkApp(app), address_of(address))

    async def _log_refusal(
        self, identity: Identity, active: uuid.UUID | None, attempt: "Attempt | None"
    ) -> None:
        """An IP refusal, logged ONLY in the tenant the attempt was aimed at (lane B's #455 review).

        The tenant whose own address (organization) the sign-in started on, else the one asked
        for (a tenant switch or a quick sign-in), else none: never every tenant the person is in,
        which would tell one tenant about attempts on another. The person is named only where
        they exist.
        """
        if attempt is None or self.database is None:
            return
        aimed = next(
            (
                m.tenant_id
                for m in identity.memberships
                if attempt.organization is not None and m.alias == attempt.organization
            ),
            active,
        )
        if aimed is None:
            return
        known = await known_user_id(self.database, aimed, identity.subject)
        facts = attempt.facts(SignInOutcome.FAILED, known, reason=IP_NOT_ALLOWED)
        await sign_in_log.record(self.database, aimed, facts)

    async def _choose_tenant(
        self,
        identity: Identity,
        app: AppName,
        active: uuid.UUID | None,
        attempt: "Attempt | None",
    ) -> tuple[list[TenantChoice], TenantChoice]:
        """The person's tenants and the one this session opens (REQ-SEC-034's address check)."""
        assert self.database is not None  # noqa: S101 - _new_session checked it
        client_ip = attempt.ip if attempt is not None else None
        choices: list[TenantChoice] = []
        for membership in identity.memberships:
            name = await tenant_name(self.database, membership.tenant_id)
            if name is not None:
                choices.append(TenantChoice(str(membership.tenant_id), name))
        if not choices:
            raise PermissionDenied(code="tenant_not_provisioned")
        # REQ-SEC-034: only a tenant whose allow-list admits this address, checked BEFORE the
        # person is looked up or created, so a refused attempt changes nothing (lane B).
        admitted_choices = [
            c for c in choices if await self._admit(uuid.UUID(c.tenant_id), app, client_ip)
        ]
        if not admitted_choices:
            await self._log_refusal(identity, active, attempt)
            raise PermissionDenied(code=IP_NOT_ALLOWED)
        target = next((c for c in admitted_choices if active and c.tenant_id == str(active)), None)
        if target is None:
            if active is not None:  # asked for one tenant, and that one refuses the address
                await self._log_refusal(identity, active, attempt)
                raise PermissionDenied(code=IP_NOT_ALLOWED)
            target = admitted_choices[0]
        return choices, target

    async def _new_session(
        self,
        identity: Identity,
        tokens: TokenSet,
        app: AppName,
        *,
        active: uuid.UUID | None,
        attempt: "Attempt | None" = None,
    ) -> Session:
        if self.database is None:
            raise ServiceUnavailable(code="database_not_configured")
        now = self.clock.now()
        choices, target = await self._choose_tenant(identity, app, active, attempt)
        # REQ-SEC-009/026 (WP-057 S1b): how this person may sign in here, judged from the verified
        # token before anyone is created; a refusal ends Keycloak's session too (_login).
        method = sign_in_method(identity)
        rule, person, also_mfa = await break_glass.policy_facts(
            self.database, uuid.UUID(target.tenant_id), identity
        )
        verdict = judge(rule, person, method)
        if verdict.refusal is not None:
            await self._log_policy_refusal(
                uuid.UUID(target.tenant_id), identity, attempt, verdict.refusal
            )
            raise PermissionDenied(code=verdict.refusal)
        user = await provision_user(
            self.database,
            uuid.UUID(target.tenant_id),
            identity,
            now,
            client=app,
            reason="login",
            on_roles_mapped=self.on_roles_mapped,
            directory=self._directory,
        )
        synced = await mfa_service.on_sign_in(
            self.database, self.identity_admin, uuid.UUID(target.tenant_id), user.user_id
        )
        mfa = synced.status
        # The identity provider's MFA is trusted after a single sign-on, unless the tenant also
        # requires SupportX's (REQ-SEC-026); then an SSO user must enrol before any session.
        if requires_supportx_mfa(method, also_require_mfa=also_mfa) and mfa.must_enrol(now):
            if not synced.enforced:
                # Keycloak could not be told: never loop through sign-in, say so instead.
                raise PermissionDenied(code="mfa_enrolment_unavailable")
            raise MfaEnrolmentDue
        return Session(
            mfa_due_at=None if mfa.due_at is None else mfa.due_at.isoformat(),
            subject=identity.subject,
            user_id=str(user.user_id),
            tenant_id=target.tenant_id,
            tenant_name=user.tenant_name,
            tenants=choices,
            email=identity.email,
            display_name=identity.display_name,
            locale=identity.locale,
            user_type=user.user_type,  # the stored type, not the token's (D-029)
            roles=list(identity.roles),
            client=app,
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            last_seen_at=now,
            access_expires_at=now + timedelta(seconds=tokens.expires_in),
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            id_token=tokens.id_token,
            keycloak_session_id=identity.keycloak_session_id,
            idle_seconds=user.session_idle_seconds,
            absolute_seconds=user.session_absolute_seconds,
            sign_in_method=method.value,
            identity_provider=identity.identity_provider,
            break_glass=verdict.break_glass,
            # Where and on what it signed in (REQ-SEC-030), and when the person last proved who
            # they are (REQ-SEC-027): the verified ID token's auth_time, at login only.
            sign_in_ip=attempt.ip if attempt is not None else None,
            device=device(attempt.user_agent) if attempt is not None else None,
            auth_time=_iso_seconds(identity.auth_time),
            place=await self.place_at(
                uuid.UUID(target.tenant_id), attempt.ip if attempt is not None else None
            ),
        )

    async def place_at(self, tenant_id: uuid.UUID, ip: str | None) -> dict[str, Any] | None:
        """The approximate place of `ip` in `tenant_id` (its site map, then GeoIP), stored form.

        Help for the person reading their sessions or sign-ins, never a reason to fail one: no
        address, no database or no match is simply no place.
        """
        if ip is None or self.database is None:
            return None
        networks = await site_networks.tenant_site_networks(self.database, tenant_id)
        found = place_of(ip, networks, self.geo.lookup)
        return None if found is None else found.to_dict()

    async def _log_policy_refusal(
        self,
        tenant_id: uuid.UUID,
        identity: Identity,
        attempt: "Attempt | None",
        reason: str,
    ) -> None:
        """A single sign-on refusal in the tenant being entered, naming the person if known."""
        if attempt is None or self.database is None:
            return
        known = await known_user_id(self.database, tenant_id, identity.subject)
        facts = attempt.facts(
            SignInOutcome.FAILED,
            known,
            reason=reason,
            method=sign_in_method(identity),
            identity_provider=identity.identity_provider,
        )
        await sign_in_log.record(self.database, tenant_id, facts)

    async def _directory(self, subject: str) -> dict[str, str | None]:
        """Department and site the person's identity provider sent (best effort, WP-039)."""
        if self.identity_admin is None:
            return {}
        try:
            attributes = await self.identity_admin.user_attributes(subject)
        except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
            log.warning("directory_attributes_unavailable")
            return {}
        found: dict[str, str | None] = {}
        for key, name in (("department", DEPARTMENT_ATTRIBUTE), ("site", SITE_ATTRIBUTE)):
            values = attributes.get(name) or []
            found[key] = values[0] if values else None
        return found

    async def _save_new(self, session: Session) -> str:
        session_id = secrets.token_urlsafe(32)
        await self._save(session_id, session)
        await self._sessions_changed(session.tenant_uuid, session.user_uuid)
        return session_id

    async def _sessions_changed(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        if self.sessions_changed is not None:
            await self.sessions_changed(tenant_id, user_id)

    async def _save(
        self, session_id: str, session: Session, *, only_if_present: bool = False
    ) -> bool:
        """Store the session; with `only_if_present`, False (nothing written) if it is gone."""
        ttl = session.ttl(self.clock.now(), idle=self.idle, absolute=self.absolute)
        return await self.store.put_session(
            session_id, session.to_dict(), ttl, only_if_present=only_if_present
        )

    # --- every request -------------------------------------------------------------------------

    async def _admit_or_end(self, session_id: str, session: Session, request: Request) -> None:
        """The allow-list again at every refresh (REQ-SEC-034).

        A changed list, or a session carried to another network, ends within one access
        token's life. It is checked even when another request holds the refresh, because this
        request's own address counts too.
        """
        if not await self._admit(
            session.tenant_uuid, _client_app(session), client_address(request)
        ):
            await self.store.delete_session(session_id)
            raise PermissionDenied(code=IP_NOT_ALLOWED)

    async def session_for(self, request: Request) -> tuple[str, Session] | None:
        """The request's valid session (refreshed if needed), None without a cookie or record.

        The mobile app sends its session ID in a header instead of a cookie (ADR-044); the rest
        (expiry, CSRF on writes, refresh) is the same.
        """
        session_id = self.presented_session_id(request)
        if not session_id:
            return None
        data = await self.store.get_session(session_id)
        if data is None:
            return None
        session = Session.from_dict(data)
        now = self.clock.now()
        if session.expiry(now, idle=self.idle, absolute=self.absolute) is not None:
            await self.store.delete_session(session_id)
            raise Unauthenticated(code="session_expired")
        ended = await self.store.user_sessions_ended(user_key(session.tenant_id, session.user_id))
        if ended is not None and session.created_at <= ended:
            # Deactivated or sign-in turned off since (REQ-ADM-010 AC1): over at once.
            await self.store.delete_session(session_id)
            raise Unauthenticated(code="session_expired")
        if request.method not in SAFE_METHODS:
            self._check_csrf(request, session)
        if session.needs_refresh(now):
            # The allow-list first: an address about to be refused never costs a token rotation.
            await self._admit_or_end(session_id, session, request)
            refreshed = await self._refresh(session_id, session)
            if refreshed is None:
                # Another request holds the refresh: answer with what we read, but never save it.
                # With refresh-token rotation (the realm's revokeRefreshToken, audit row 26) a
                # save here could put back the token the other request has just spent.
                return session_id, session
            session = refreshed
        if session.needs_refresh(now) or now - session.last_seen_at >= TOUCH_INTERVAL:
            session = session.touched(now)
            if not await self._save(session_id, session, only_if_present=True):
                raise Unauthenticated(code="session_expired")  # signed out meanwhile
        return session_id, session

    async def listed_sessions(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, current: str | None = None
    ) -> list["ListedSession"]:
        """A person's live sessions, newest use first (ADR-044 item 5); `current`: this one."""
        mine = public_id(current) if current else None
        rows = await self.store.user_sessions(user_key(str(tenant_id), str(user_id)))
        found = [
            ListedSession(
                id=sid,
                client=str(meta.get("client") or ""),
                platform=meta.get("platform"),
                app_version=meta.get("app_version"),
                started_at=_moment(meta.get("created_at")),
                last_used_at=_moment(meta.get("last_seen_at")),
                current=sid == mine,
                ip=meta.get("ip"),
                device=meta.get("device"),
                place=meta.get("place") if isinstance(meta.get("place"), dict) else None,
            )
            for sid, meta in rows
        ]
        return sorted(found, key=lambda s: s.last_used_at or s.started_at or _EPOCH, reverse=True)

    async def end_listed_session(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        session: str,
        *,
        keep_keycloak_session: str | None = None,
    ) -> bool:
        """End one of a person's sessions by its listed id; its next call answers 401.

        Its Keycloak session ends too (WP-057 S2a, the coordinator's rule), so its refresh token
        is spent, unless it is `keep_keycloak_session`: the caller's own, shared by the console and
        portal of one browser, which only ends locally. Their live connections in the tenant are
        cut too, so the ended one can't keep listening; the others reconnect with their own
        sessions (as after a sign-out).
        """
        ended = await self._take_and_end(
            user_key(str(tenant_id), str(user_id)), session, keep_keycloak_session
        )
        if ended:
            await self._sessions_changed(tenant_id, user_id)
            if self.end_realtime is not None:
                await self.end_realtime(tenant_id, user_id)
        return ended

    async def end_other_sessions(self, session_id: str, session: Session) -> int:
        """Sign out everywhere else (REQ-SEC-030 AC2): every other session in this tenant ends.

        This one stays working. Each ended session's Keycloak session ends too, except a twin
        sharing this one's Keycloak session (the console and portal of this browser), which ends
        here only, so signing out the others never signs this browser out. How many ended.
        """
        mine = public_id(session_id)
        key = user_key(session.tenant_id, session.user_id)
        ended = 0
        for listed, _meta in await self.store.user_sessions(key):
            if listed == mine:
                continue
            if await self._take_and_end(key, listed, session.keycloak_session_id):
                ended += 1
        if ended:
            await self._sessions_changed(session.tenant_uuid, session.user_uuid)
            if self.end_realtime is not None:
                await self.end_realtime(session.tenant_uuid, session.user_uuid)
        return ended

    async def _take_and_end(self, key: str, listed: str, keep_keycloak_session: str | None) -> bool:
        """End one listed session here and, unless it shares the kept one, at Keycloak."""
        record = await self.store.take_listed_session(key, listed)
        if record is None:
            return False
        try:
            ended = Session.from_dict(record) if record else None
        except (KeyError, TypeError, ValueError):
            ended = None  # unreadable: it is gone here, and its token expires on its own
        if ended is None or not ended.refresh_token:
            return True
        if keep_keycloak_session is not None and ended.keycloak_session_id == keep_keycloak_session:
            return True  # this browser's own Keycloak session: ended here only
        try:
            await self._end_keycloak_session(self.client(_client_app(ended)), ended.refresh_token)
        except IdentityProviderUnavailable:
            log.warning("keycloak_logout_failed", subject=ended.subject)
        return True

    async def end_sessions(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """End every session of a person in a tenant, now (REQ-SEC-031).

        Their next request gets 401, and their live connections in the tenant close at once
        (AC1: within 5 seconds). The marker outlives the longest possible session (a tenant's
        limits can exceed the platform default). Their Keycloak sessions stay: Keycloak's user is
        shared by every tenant they belong to (D-094), and signing in again here is refused.
        """
        await self.store.end_user_sessions(
            user_key(str(tenant_id), str(user_id)), self.clock.now(), MAX_SESSION
        )
        if self.end_realtime is not None:
            await self.end_realtime(tenant_id, user_id)

    async def check_address(self, request: Request) -> None:
        """Refuse a signed-in request from outside its tenant's list for its app (REQ-SEC-034).

        For what turns a session into more access between refreshes: the realtime tokens
        (lane B's condition 3). An API key's call was checked when the key was (api_keys.py).
        """
        session_id = self.presented_session_id(request)
        data = await self.store.get_session(session_id) if session_id else None
        if data is None:
            return
        session = Session.from_dict(data)
        address = client_address(request)
        if not await self._admit(session.tenant_uuid, _client_app(session), address):
            raise PermissionDenied(code=IP_NOT_ALLOWED)

    async def resolve(self, request: Request) -> TenantContext | None:
        """`SessionResolver` for app.core.tenancy: an API key's call, or the session's user.

        A key in `Authorization: Bearer sxk_…` is checked first and alone: no cookie, so no CSRF
        either (D-128). A request carrying both is the key's call.
        """
        key = api_keys.bearer(request.headers.get("authorization"))
        if key is not None:
            if self.database is None:
                raise ServiceUnavailable(code="api_keys_unavailable")
            # A key can never confirm who holds it (REQ-SEC-027): sensitive routes refuse it.
            record_freshness(
                request, SignInFreshness(interactive=False, recent=False, api_key=True)
            )
            return await api_keys.authenticate(
                self.database, self.settings, key, RequestFacts.of(request), self.clock.now()
            )
        found = await self.session_for(request)
        if found is None:
            return None
        _session_id, session = found
        record_freshness(request, self._freshness(session))
        return TenantContext(
            tenant_id=session.tenant_uuid, user_id=session.user_uuid, roles=frozenset(session.roles)
        )

    def _freshness(self, session: Session) -> SignInFreshness:
        """For RecentAuth (REQ-SEC-027): a browser session, and whether it confirmed recently.

        The mobile app cannot confirm in a pop-up, so it is not interactive for these routes.
        """
        interactive = session.device_platform is None
        confirmed = _moment(session.auth_time)
        recent = confirmed is not None and self.clock.now() - confirmed <= RECENT_AUTH_WINDOW
        return SignInFreshness(interactive=interactive, recent=interactive and recent)

    def _check_csrf(self, request: Request, session: Session) -> None:
        """Synchronizer token: the header must equal the token stored in the server-side session."""
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(sent, session.csrf_token):
            raise PermissionDenied(code="csrf_failed")
        origin = request.headers.get("origin")
        if origin is not None and not self._origin_allowed(origin.rstrip("/"), request):
            raise PermissionDenied(code="csrf_failed")

    def _origin_allowed(self, origin: str, request: Request) -> bool:
        """The UIs' configured origins, or the request's own host (a tenant address, WP-017).

        A same-origin request cannot be forged by another site (browsers set Origin), and the
        session cookie is bound to the host it was set on, so the host's own origin is safe.
        """
        if origin in self.allowed_origins:
            return True
        schemes = {urlsplit(self.base_url(app)).scheme for app in ("console", "portal")}
        parts = urlsplit(origin)
        return parts.scheme in schemes and parts.netloc == request.headers.get("host")

    async def _refresh(self, session_id: str, session: Session) -> Session | None:
        """Silent refresh. Keycloak refusing ends the session; Keycloak being down does not.

        None while another request is refreshing this session. Keycloak rotates refresh tokens
        (revokeRefreshToken, refreshTokenMaxReuse 0; audit row 26): every refresh stores the new
        token, and a spent one is never sent again.
        """
        held = await self.store.lock(session_id, REFRESH_LOCK_TTL)
        if held is None:
            return None
        client = self.client(_client_app(session))
        try:
            stored = await self.store.get_session(session_id)
            if stored is None:
                # Signed out (or ended) since this request read it: never bring it back.
                raise Unauthenticated(code="session_expired")
            latest = Session.from_dict(stored)
            if latest.refresh_token != session.refresh_token:
                # Another request refreshed between our read and the lock: ours is spent.
                return latest
            tokens = await self.oidc.refresh(client, session.refresh_token)
            identity = await self._identity(tokens, client, nonce=None)
        except (TokenRejectedError, BadRequest) as exc:
            await self.store.delete_session(session_id)
            log.info("session_ended_by_refresh", subject=session.subject)
            raise Unauthenticated(code="session_expired") from exc
        except IdentityProviderUnavailable:
            log.warning("token_refresh_deferred", reason="identity_provider_unavailable")
            return session
        finally:
            await self.store.unlock(session_id, held)
        if session.tenant_uuid not in {m.tenant_id for m in identity.memberships}:
            # Removed from the organization in Keycloak: access to this tenant ends now.
            await self.store.delete_session(session_id)
            raise Unauthenticated(code="session_expired")
        refreshed = replace(
            session,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            id_token=tokens.id_token,
            access_expires_at=self.clock.now() + timedelta(seconds=tokens.expires_in),
            roles=list(identity.roles),
        )
        # Conditional (SET XX): a sign-out during the in-flight refresh deleted the record after
        # the lock was released; writing it back would revive the session with fresh tokens.
        if not await self._save(session_id, refreshed, only_if_present=True):
            raise Unauthenticated(code="session_expired")
        return refreshed

    # --- logout and tenant switch ----------------------------------------------------------------

    async def logout(
        self, session_id: str, session: Session, *, attempt: Attempt | None = None
    ) -> None:
        """End the local session and the Keycloak SSO session (back channel)."""
        if attempt is not None:  # the sign-in log (REQ-AUD-015): a sign-out
            facts = attempt.facts(
                SignInOutcome.SIGNED_OUT, session.user_uuid, method=_stored_method(session)
            )
            await sign_in_log.record(self.database, session.tenant_uuid, facts)
        await self.store.delete_session(session_id)
        await self._sessions_changed(session.tenant_uuid, session.user_uuid)
        client = self.client(_client_app(session))
        try:
            await self._end_keycloak_session(client, session.refresh_token)
        except IdentityProviderUnavailable:
            log.warning("keycloak_logout_failed", subject=session.subject)
        # Last, and never fatal: the session is already gone, which is what the user asked for.
        # The session lives in Valkey, so this event cannot share a transaction with it.
        if self.database is not None:
            try:
                await record_logout(
                    self.database, session.tenant_uuid, session.user_uuid, _client_app(session)
                )
            except (SQLAlchemyError, OSError):
                log.exception("logout_event_not_recorded", subject=session.subject)

    async def end_session(self, session_id: str, session: Session) -> None:
        """End only this SupportX session, recorded as a logout; Keycloak's own session stays.

        For a console session that may not exist (D-129): the person keeps their portal sign-in.
        """
        await self.store.delete_session(session_id)
        await self._sessions_changed(session.tenant_uuid, session.user_uuid)
        if self.database is not None:
            try:
                await record_logout(
                    self.database, session.tenant_uuid, session.user_uuid, _client_app(session)
                )
            except (SQLAlchemyError, OSError):
                log.exception("logout_event_not_recorded", subject=session.subject)

    async def withdraw_sign_in(self, session_id: str, session: Session) -> None:
        """Undo a sign-in refused after its session was made: ours and Keycloak's both end.

        As the other refusals (SIGN_IN_REFUSALS), so the person is asked again next time rather
        than walked straight back in by Keycloak's still-open session (lane B, #459).
        """
        await self.store.delete_session(session_id)
        try:
            await self._end_keycloak_session(
                self.client(_client_app(session)), session.refresh_token
            )
        except IdentityProviderUnavailable:
            log.warning("keycloak_logout_failed", subject=session.subject)

    async def _end_keycloak_session(self, client: ClientCredentials, refresh_token: str) -> None:
        if not await self.oidc.end_session(client, refresh_token):
            log.warning("keycloak_logout_refused")

    async def switch_tenant(
        self,
        session_id: str,
        session: Session,
        tenant_id: uuid.UUID,
        *,
        client_ip: str | None = None,
    ) -> tuple[str, Session]:
        """Move to another of the user's tenants under a brand-new session ID."""
        if str(tenant_id) not in {c.tenant_id for c in session.tenants}:
            raise PermissionDenied(code="not_a_member")
        if self.database is None:
            raise ServiceUnavailable(code="database_not_configured")
        if not await self._admit(tenant_id, _client_app(session), client_ip):
            attempt = Attempt(_client_app(session), client_ip, None)
            facts = attempt.facts(SignInOutcome.FAILED, None, reason=IP_NOT_ALLOWED)
            known = await known_user_id(self.database, tenant_id, session.subject)
            await sign_in_log.record(self.database, tenant_id, replace(facts, user_id=known))
            raise PermissionDenied(code=IP_NOT_ALLOWED)  # before the person is looked up
        # REQ-SEC-009 there too, judged by how this session began (lane B's condition 2: a switch
        # has no new token). A session from before S1b counts as a password one.
        method = _stored_method(session) or SignInMethod.PASSWORD
        rule, person, _also_mfa = await break_glass.policy_facts(
            self.database, tenant_id, _identity_of(session)
        )
        verdict = judge(rule, person, method)
        if verdict.refusal is not None:
            raise PermissionDenied(code=verdict.refusal)
        identity = Identity(
            subject=session.subject,
            email=session.email,
            display_name=session.display_name,
            locale=session.locale,
            roles=tuple(session.roles),
            memberships=(),
            keycloak_session_id=session.keycloak_session_id,
        )
        user = await provision_user(
            self.database,
            tenant_id,
            identity,
            self.clock.now(),
            client=_client_app(session),
            reason="tenant_switch",
            on_roles_mapped=self.on_roles_mapped,
        )
        switched = replace(
            session,
            tenant_id=str(tenant_id),
            tenant_name=user.tenant_name,
            user_id=str(user.user_id),
            csrf_token=secrets.token_urlsafe(32),
            # The new tenant's limits, counted from now: a new session in all but its tokens.
            created_at=self.clock.now(),
            idle_seconds=user.session_idle_seconds,
            absolute_seconds=user.session_absolute_seconds,
            # The new tenant maps its own address ranges to its own sites.
            place=await self.place_at(tenant_id, session.sign_in_ip),
        )
        await self.store.delete_session(session_id)
        return await self._save_new(switched), switched

    @staticmethod
    def describe(session: Session) -> dict[str, Any]:
        """What the browser may know about its session (never tokens)."""
        return {
            "user": {
                "id": session.user_id,
                "email": session.email,
                "display_name": session.display_name,
                "locale": session.locale,
                "user_type": session.user_type,
                "roles": session.roles,
            },
            "tenant": {"id": session.tenant_id, "name": session.tenant_name},
            "tenants": [{"id": c.tenant_id, "name": c.name} for c in session.tenants],
            "csrf_token": session.csrf_token,
            "mfa_due_at": session.mfa_due_at,
        }
