"""BFF authentication use cases (architecture.md §11.1, ADR-006, D-009, D-010; WP-006).

Login: GET /auth/login stores a one-time login state (PKCE verifier, nonce, returnTo) and sends
the browser to Keycloak. The callback exchanges the code on the back channel, verifies the ID
token (RS256 signature, issuer, audience, expiry, nonce), maps organization memberships to
tenants, provisions the user just-in-time, and creates a brand-new session (no fixation).

Every later request: the opaque cookie → encrypted session record in Valkey → idle/absolute
expiry checks → CSRF check on state-changing methods → silent token refresh when the access token
expires (if Keycloak refuses, the session ends) → TenantContext for the database.
"""

import hmac
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import (
    AppError,
    BadRequest,
    PermissionDenied,
    ServiceUnavailable,
    Unauthenticated,
)
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.identity import (
    ClaimsError,
    Identity,
    identity_from,
    safe_return_to,
    validate_claims,
)
from app.modules.identity_access.domain.session import Session, TenantChoice
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
from app.modules.identity_access.infra.store import SessionStore
from app.modules.identity_access.service import sso_test
from app.modules.identity_access.service.users import provision_user, record_logout, tenant_name
from app.shared.clock import Clock

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.modules.identity_access.infra.keycloak_admin import IdentityAdmin

log = get_logger(__name__)

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


def _user_key(tenant_id: str, user_id: str) -> str:
    return f"{tenant_id}:{user_id}"


@dataclass(frozen=True)
class LoginAddress:
    """A tenant's own address the login started on (WP-017): its host and organization alias."""

    host: str
    organization: str


class LoginFailure(Exception):
    """A login that could not complete: which app it was for, and the problem to report."""

    def __init__(self, app: AppName, problem: AppError, origin: str | None = None) -> None:
        super().__init__(problem.instance_code)  # the code is a stable identifier, not prose
        self.app = app
        self.problem = problem
        self.origin = origin  # a tenant's own address the login started on (WP-017), if any


class LoginResult:
    """A completed login: the new session and where to send the browser."""

    def __init__(self, session_id: str, session: Session, redirect_to: str) -> None:
        self.session_id = session_id
        self.session = session
        self.redirect_to = redirect_to


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
        self.idle = timedelta(seconds=settings.session_idle_timeout_seconds)
        self.absolute = timedelta(seconds=settings.session_absolute_timeout_seconds)
        # Set by the module startup once the policy service exists (WP-016).
        self.on_roles_mapped: Callable[[uuid.UUID], Awaitable[None]] | None = None
        # Set by the module startup: Keycloak's admin API as the identity service account.
        self.identity_admin: IdentityAdmin | None = None
        # Set by the module startup: closes a person's live connections in a tenant (WP-039).
        self.end_realtime: Callable[[uuid.UUID, uuid.UUID], Awaitable[None]] | None = None

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
        """Where the browser goes after login: its own path, else the UI's home."""
        base_origin = origin or self.origin(app)
        if return_to == "/":
            return base_origin + urlsplit(self.base_url(app)).path.rstrip("/") + "/"
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

    async def start_login(
        self,
        app: AppName,
        return_to: str | None,
        address: LoginAddress | None = None,
        *,
        reauthenticate: bool = False,
    ) -> str:
        """Remember a one-time login state and return Keycloak's authorization URL.

        On a tenant's own address (WP-017, REQ-SEC-004) the callback stays on that address and
        Keycloak is asked for that tenant's organization: its sign-in page shows the tenant's
        brand, and the token names only that organization. A hint, never access: someone who is
        not a member gets no organization and the usual `no_organization` refusal.

        `reauthenticate` (a session of this browser timed out, REQ-SEC-029): Keycloak asks for
        the password again instead of reusing its own, longer session.
        """
        origin = self.origin(app, address.host) if address is not None else None
        state, nonce, pkce = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
            PkcePair.generate(),
        )
        await self.store.put_login(
            state,
            {
                "app": app,
                "nonce": nonce,
                "verifier": pkce.verifier,
                "return_to": safe_return_to(return_to),
                "origin": origin,
                "organization": address.organization if address is not None else None,
            },
            LOGIN_STATE_TTL,
        )
        return await self.oidc.authorization_url(
            self.client(app, origin),
            state=state,
            nonce=nonce,
            pkce=pkce,
            organization=address.organization if address is not None else None,
            prompt="login" if reauthenticate else None,
        )

    async def complete_login(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
        previous_session_id: str | None,
        host: str | None = None,
    ) -> "LoginResult | sso_test.TestFinished":
        """Finish the OIDC callback and create a fresh session (or finish an SSO test).

        Any failure is raised as LoginFailure carrying the app it belongs to, so the BFF can send a
        browser back to the right app with a translatable error code.
        """
        pending = await self.store.take_login(state) if state else None
        if pending is None:
            raise LoginFailure("console", BadRequest(code="invalid_login_state"))  # noqa: EM101 - a code, not a message
        if pending.get("test"):  # an admin's test of a single sign-on set-up (WP-039)
            return await sso_test.finish(self, pending, code=code, error=error)
        app: AppName = "portal" if pending["app"] == "portal" else "console"
        origin = pending.get("origin")
        if origin is not None and urlsplit(origin).netloc != host:
            # Started on another address than it finished on: never move a session across.
            raise LoginFailure(app, BadRequest(code="login_failed"))
        if error or not code:
            raise LoginFailure(app, BadRequest(code="login_failed"), origin)
        try:
            session = await self._login(app, code, pending)
        except AppError as exc:
            raise LoginFailure(app, exc, origin) from exc
        if previous_session_id:  # rotation: the pre-login session (if any) dies here
            await self.store.delete_session(previous_session_id)
        session_id = await self._save_new(session)
        log.info("login", subject=session.subject, tenant_id=session.tenant_id, client=app)
        return LoginResult(session_id, session, self.landing(app, pending["return_to"], origin))

    async def _login(self, app: AppName, code: str, pending: dict[str, Any]) -> Session:
        client = self.client(app, pending.get("origin"))
        try:
            tokens = await self.oidc.exchange_code(client, code=code, verifier=pending["verifier"])
        except TokenRejectedError as exc:
            raise BadRequest(code="login_failed") from exc
        identity = await self._identity(tokens, client, nonce=pending["nonce"])
        if not identity.memberships:
            await self._end_keycloak_session(client, tokens.refresh_token)
            raise PermissionDenied(code="no_organization")
        return await self._new_session(identity, tokens, app, active=None)

    async def _identity(
        self, tokens: TokenSet, client: ClientCredentials, *, nonce: str | None
    ) -> Identity:
        try:
            claims = await self.oidc.verify_id_token(tokens.id_token)
            validate_claims(
                claims,
                issuer=self.oidc.issuer,
                client_id=client.client_id,
                nonce=nonce,
                now=self.clock.now(),
            )
        except (InvalidTokenError, ClaimsError) as exc:
            log.warning("id_token_rejected", reason=str(exc))
            raise BadRequest(code="login_failed") from exc
        return identity_from(claims)

    async def _new_session(
        self, identity: Identity, tokens: TokenSet, app: AppName, *, active: uuid.UUID | None
    ) -> Session:
        if self.database is None:
            raise ServiceUnavailable(code="database_not_configured")
        now = self.clock.now()
        choices: list[TenantChoice] = []
        for membership in identity.memberships:
            name = await tenant_name(self.database, membership.tenant_id)
            if name is not None:
                choices.append(TenantChoice(str(membership.tenant_id), name))
        if not choices:
            raise PermissionDenied(code="tenant_not_provisioned")
        target = next((c for c in choices if active and c.tenant_id == str(active)), choices[0])
        user = await provision_user(
            self.database,
            uuid.UUID(target.tenant_id),
            identity,
            now,
            client=app,
            reason="login",
            on_roles_mapped=self.on_roles_mapped,
        )
        return Session(
            subject=identity.subject,
            user_id=str(user.user_id),
            tenant_id=target.tenant_id,
            tenant_name=user.tenant_name,
            tenants=choices,
            email=identity.email,
            display_name=identity.display_name,
            locale=identity.locale,
            user_type=identity.user_type.value,
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
        )

    async def _save_new(self, session: Session) -> str:
        session_id = secrets.token_urlsafe(32)
        await self._save(session_id, session)
        return session_id

    async def _save(self, session_id: str, session: Session) -> None:
        ttl = session.ttl(self.clock.now(), idle=self.idle, absolute=self.absolute)
        await self.store.put_session(session_id, session.to_dict(), ttl)

    # --- every request -------------------------------------------------------------------------

    async def session_for(self, request: Request) -> tuple[str, Session] | None:
        """The request's valid session (refreshed if needed), None without a cookie or record."""
        session_id = request.cookies.get(self.cookie_name)
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
        ended = await self.store.user_sessions_ended(_user_key(session.tenant_id, session.user_id))
        if ended is not None and session.created_at <= ended:
            # Deactivated or sign-in turned off since (REQ-ADM-010 AC1): over at once.
            await self.store.delete_session(session_id)
            raise Unauthenticated(code="session_expired")
        if request.method not in SAFE_METHODS:
            self._check_csrf(request, session)
        if session.needs_refresh(now):
            session = await self._refresh(session_id, session)
        if session.needs_refresh(now) or now - session.last_seen_at >= TOUCH_INTERVAL:
            session = session.touched(now)
            await self._save(session_id, session)
        return session_id, session

    async def end_sessions(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """End every session of a person in a tenant, now (REQ-SEC-031).

        Their next request gets 401, and their live connections in the tenant close at once
        (AC1: within 5 seconds). The marker outlives the longest possible session (a tenant's
        limits can exceed the platform default). Their Keycloak sessions stay: Keycloak's user is
        shared by every tenant they belong to (D-094), and signing in again here is refused.
        """
        await self.store.end_user_sessions(
            _user_key(str(tenant_id), str(user_id)), self.clock.now(), MAX_SESSION
        )
        if self.end_realtime is not None:
            await self.end_realtime(tenant_id, user_id)

    async def resolve(self, request: Request) -> TenantContext | None:
        """`SessionResolver` for app.core.tenancy: the session's tenant and user."""
        found = await self.session_for(request)
        if found is None:
            return None
        _session_id, session = found
        return TenantContext(
            tenant_id=session.tenant_uuid, user_id=session.user_uuid, roles=frozenset(session.roles)
        )

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

    async def _refresh(self, session_id: str, session: Session) -> Session:
        """Silent refresh. Keycloak refusing ends the session; Keycloak being down does not."""
        if not await self.store.lock(session_id, REFRESH_LOCK_TTL):
            return session  # another request is refreshing this session right now
        client = self.client(_client_app(session))
        try:
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
            await self.store.unlock(session_id)
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
        await self._save(session_id, refreshed)
        return refreshed

    # --- logout and tenant switch ----------------------------------------------------------------

    async def logout(self, session_id: str, session: Session) -> None:
        """End the local session and the Keycloak SSO session (back channel)."""
        await self.store.delete_session(session_id)
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

    async def _end_keycloak_session(self, client: ClientCredentials, refresh_token: str) -> None:
        if not await self.oidc.end_session(client, refresh_token):
            log.warning("keycloak_logout_refused")

    async def switch_tenant(
        self, session_id: str, session: Session, tenant_id: uuid.UUID
    ) -> tuple[str, Session]:
        """Move to another of the user's tenants under a brand-new session ID."""
        if str(tenant_id) not in {c.tenant_id for c in session.tenants}:
            raise PermissionDenied(code="not_a_member")
        if self.database is None:
            raise ServiceUnavailable(code="database_not_configured")
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
        }
