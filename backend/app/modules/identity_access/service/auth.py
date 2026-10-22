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
from dataclasses import replace
from datetime import timedelta
from typing import Any, Literal

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
from app.modules.identity_access.service.users import provision_user, record_logout, tenant_name
from app.shared.clock import Clock

log = get_logger(__name__)

AppName = Literal["console", "portal"]
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"
CALLBACK_PATH = "/api/v1/auth/callback"
LOGIN_STATE_TTL = timedelta(minutes=10)
REFRESH_LOCK_TTL = timedelta(seconds=15)
TOUCH_INTERVAL = timedelta(seconds=60)


def _client_app(session: Session) -> AppName:
    return "portal" if session.client == "portal" else "console"


class LoginFailure(Exception):
    """A login that could not complete: which app it was for, and the problem to report."""

    def __init__(self, app: AppName, problem: AppError) -> None:
        super().__init__(problem.instance_code)  # the code is a stable identifier, not prose
        self.app = app
        self.problem = problem


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

    # --- clients and origins -------------------------------------------------------------------

    def base_url(self, app: AppName) -> str:
        """Public origin of the console or portal (where the browser lands after login)."""
        return (self.settings.console_url if app == "console" else self.settings.portal_url).rstrip(
            "/"
        )

    def client(self, app: AppName) -> ClientCredentials:
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
            client_id, secret.get_secret_value(), self.base_url(app) + CALLBACK_PATH
        )

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Origins allowed to send state-changing requests with the session cookie."""
        return frozenset({self.base_url("console"), self.base_url("portal")})

    # --- login ---------------------------------------------------------------------------------

    async def start_login(self, app: AppName, return_to: str | None) -> str:
        """Remember a one-time login state and return Keycloak's authorization URL."""
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
            },
            LOGIN_STATE_TTL,
        )
        return await self.oidc.authorization_url(
            self.client(app), state=state, nonce=nonce, pkce=pkce
        )

    async def complete_login(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
        previous_session_id: str | None,
    ) -> LoginResult:
        """Finish the OIDC callback and create a fresh session.

        Any failure is raised as LoginFailure carrying the app it belongs to, so the BFF can send a
        browser back to the right app with a translatable error code.
        """
        pending = await self.store.take_login(state) if state else None
        if pending is None:
            raise LoginFailure("console", BadRequest(code="invalid_login_state"))  # noqa: EM101 - a code, not a message
        app: AppName = "portal" if pending["app"] == "portal" else "console"
        if error or not code:
            raise LoginFailure(app, BadRequest(code="login_failed"))
        try:
            session = await self._login(app, code, pending)
        except AppError as exc:
            raise LoginFailure(app, exc) from exc
        if previous_session_id:  # rotation: the pre-login session (if any) dies here
            await self.store.delete_session(previous_session_id)
        session_id = await self._save_new(session)
        log.info("login", subject=session.subject, tenant_id=session.tenant_id, client=app)
        return LoginResult(session_id, session, self.base_url(app) + pending["return_to"])

    async def _login(self, app: AppName, code: str, pending: dict[str, Any]) -> Session:
        client = self.client(app)
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
        if request.method not in SAFE_METHODS:
            self._check_csrf(request, session)
        if session.needs_refresh(now):
            session = await self._refresh(session_id, session)
        if session.needs_refresh(now) or now - session.last_seen_at >= TOUCH_INTERVAL:
            session = session.touched(now)
            await self._save(session_id, session)
        return session_id, session

    async def resolve(self, request: Request) -> TenantContext | None:
        """`SessionResolver` for app.core.tenancy: the session's tenant and user."""
        found = await self.session_for(request)
        if found is None:
            return None
        _session_id, session = found
        return TenantContext(tenant_id=session.tenant_uuid, user_id=session.user_uuid)

    def _check_csrf(self, request: Request, session: Session) -> None:
        """Synchronizer token: the header must equal the token stored in the server-side session."""
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(sent, session.csrf_token):
            raise PermissionDenied(code="csrf_failed")
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") not in self.allowed_origins:
            raise PermissionDenied(code="csrf_failed")

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
        )
        switched = replace(
            session,
            tenant_id=str(tenant_id),
            tenant_name=user.tenant_name,
            user_id=str(user.user_id),
            csrf_token=secrets.token_urlsafe(32),
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
