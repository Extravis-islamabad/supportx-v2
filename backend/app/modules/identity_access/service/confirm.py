"""Confirm who you are before a sensitive action (REQ-SEC-027; WP-057 S2a).

`start` sends the browser to Keycloak with `prompt=login` and `max_age=0` (and, for a person who
signs in through an identity provider, `kc_idp_hint`, so they confirm there). `finish` handles the
callback. It never creates a session: it refreshes the one already in the browser. Lane B's
conditions, each checked here:

- The pending state is single use (taken on the first callback) and lives 5 minutes.
- The callback comes from the browser that started it (the login binding, checked by the caller),
  carrying the very session it was started for (its public id).
- The ID token is verified and nonce-bound (`_identity`); its `azp` is our client, its `sub` the
  session's person, and its `auth_time` no older than the start (2 s of clock skew, no more).
- The session gets the confirmation's tokens. When Keycloak gave a new session (`sid`), the old
  one is ended through its refresh token, so no orphaned chain stays alive.
- A refusal (cancelled, another person, a stale `auth_time`) changes nothing and is logged in the
  sign-in log as `reauth_failed` (AC2).

A brokered sign-in only re-authenticates at the identity provider if Keycloak passes the request
on: OIDC providers pass `prompt` (unless a fixed one is set) and `max_age` (`passMaxAge`, set on
every provider SupportX creates, sso.py). SAML providers are not proven to, so their people get
`reauth_unavailable` rather than a confirmation that never reached their provider (fail closed).
"""

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode

from app.core.errors import PermissionDenied
from app.core.logging import get_logger
from app.modules.identity_access.domain.identity import safe_return_to
from app.modules.identity_access.domain.session import Session
from app.modules.identity_access.domain.sign_in import SignInApp, SignInMethod, SignInOutcome
from app.modules.identity_access.infra.oidc import PkcePair, TokenRejectedError
from app.modules.identity_access.infra.store import public_id
from app.modules.identity_access.service import sign_in_log

if TYPE_CHECKING:
    from app.modules.identity_access.service.auth import AuthService, LoginStarted

log = get_logger(__name__)

CONFIRM_TTL = timedelta(minutes=5)
CLOCK_SKEW = timedelta(seconds=2)
REAUTH_FAILED = "reauth_failed"
REAUTH_UNAVAILABLE = "reauth_unavailable"
CONFIRMED_PATH = "/confirmed"  # the UI's page that tells the opener and closes (REQ-SEC-027)
# The opener's id for one confirmation, echoed to /confirmed so the opener knows the answer is its
# own. Not a secret (the server decides; the answer only triggers a retry the server checks).
ATTEMPT = re.compile(r"[A-Za-z0-9_-]{16,64}")


@dataclass(frozen=True)
class ConfirmFinished:
    """Where the browser goes after a confirmation, and whether it confirmed."""

    redirect_to: str
    confirmed: bool


async def start(  # noqa: PLR0913 - the session, where back to, and the keyword-only flags
    auth: "AuthService",
    session_id: str,
    session: Session,
    return_to: str | None,
    *,
    can_reauthenticate_at_provider: bool,
    attempt: str | None = None,
) -> "LoginStarted":
    """Remember a one-time confirmation for this session; Keycloak's URL and the binding."""
    from app.modules.identity_access.service.auth import (  # noqa: PLC0415 - avoids a cycle
        LoginStarted,
        binding_digest,
    )

    if session.device_platform is not None:
        raise PermissionDenied(code="interactive_session_required")  # the app cannot confirm
    hint = session.identity_provider
    if hint is not None and not can_reauthenticate_at_provider:
        raise PermissionDenied(code=REAUTH_UNAVAILABLE)  # fail closed (lane B A4)
    app: Literal["console", "portal"] = "portal" if session.client == "portal" else "console"
    state, nonce, pkce = secrets.token_urlsafe(32), secrets.token_urlsafe(32), PkcePair.generate()
    binding = secrets.token_urlsafe(32)
    await auth.store.put_login(
        state,
        {
            "app": app,
            "nonce": nonce,
            "verifier": pkce.verifier,
            "return_to": safe_return_to(return_to),
            "origin": None,
            "binding": binding_digest(binding),
            "confirm": public_id(session_id),
            "started_at": auth.clock.now().isoformat(),
            "attempt": safe_attempt(attempt),
        },
        CONFIRM_TTL,
    )
    url = await auth.oidc.authorization_url(
        auth.client(app),
        state=state,
        nonce=nonce,
        pkce=pkce,
        prompt="login",
        max_age=0,
        idp_hint=hint,
    )
    return LoginStarted(url, state, binding)


async def finish(  # noqa: PLR0913 - the callback's parts, keyword-only
    auth: "AuthService",
    pending: dict[str, Any],
    *,
    code: str | None,
    error: str | None,
    current_session_id: str | None,
    client_ip: str | None,
    user_agent: str | None,
) -> ConfirmFinished:
    """Check the confirmation and refresh this browser's session with it, or refuse."""
    app: Literal["console", "portal"] = "portal" if pending.get("app") == "portal" else "console"
    landing = _landing(auth, app, pending)
    record = await auth.store.get_session(current_session_id) if current_session_id else None
    session = _session(record)
    if (
        session is None
        or current_session_id is None
        or public_id(current_session_id) != pending.get("confirm")
    ):
        return ConfirmFinished(landing(confirmed=False), confirmed=False)  # not this session
    refusal = await _confirmed_tokens(auth, app, pending, session, code=code, error=error)
    if isinstance(refusal, str):
        await _log_refusal(
            auth, session, app=app, detail=refusal, client_ip=client_ip, user_agent=user_agent
        )
        return ConfirmFinished(landing(confirmed=False), confirmed=False)
    tokens, identity = refusal
    confirmed = replace(
        session,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        id_token=tokens.id_token,
        access_expires_at=auth.clock.now() + timedelta(seconds=tokens.expires_in),
        keycloak_session_id=identity.keycloak_session_id or session.keycloak_session_id,
        auth_time=datetime.fromtimestamp(identity.auth_time or 0, UTC).isoformat(),
    )
    if not await auth.save_existing(current_session_id, confirmed):
        return ConfirmFinished(landing(confirmed=False), confirmed=False)  # signed out meanwhile
    if (
        identity.keycloak_session_id is not None
        and identity.keycloak_session_id != session.keycloak_session_id
    ):
        # Keycloak started a new session for the confirmation: the old one ends, so its refresh
        # token can never be used again (lane B A5).
        await auth.end_keycloak_session_quietly(app, session)
    return ConfirmFinished(landing(confirmed=True), confirmed=True)


async def _confirmed_tokens(  # noqa: PLR0913, PLR0911 - one return per named refusal
    auth: "AuthService",
    app: Literal["console", "portal"],
    pending: dict[str, Any],
    session: Session,
    *,
    code: str | None,
    error: str | None,
) -> Any:  # noqa: ANN401 - (TokenSet, Identity) on success, else the refusal reason (str)
    if error or not code:
        return "cancelled"
    client = auth.client(app)
    try:
        tokens = await auth.oidc.exchange_code(client, code=code, verifier=pending["verifier"])
    except TokenRejectedError:
        return "token_rejected"
    try:
        identity, claims = await auth.verified_identity(tokens, client, nonce=pending["nonce"])
    except PermissionDenied:
        return "token_rejected"
    if claims.get("azp", client.client_id) != client.client_id:
        return "wrong_client"
    if identity.subject != session.subject:
        return "another_person"
    started = datetime.fromisoformat(str(pending["started_at"]))
    when = identity.auth_time
    if when is None or datetime.fromtimestamp(when, UTC) < started - CLOCK_SKEW:
        return "not_fresh"  # Keycloak did not authenticate the person again
    return tokens, identity


def _session(record: dict[str, Any] | None) -> Session | None:
    if not record:
        return None
    try:
        return Session.from_dict(record)
    except (KeyError, TypeError, ValueError):
        return None


def safe_attempt(value: str | None) -> str | None:
    """The opener's attempt id when well formed, else None (it is echoed into a URL)."""
    return value if value is not None and ATTEMPT.fullmatch(value) else None


def confirmed_landing(
    auth: "AuthService",
    app: Literal["console", "portal"],
    status: Literal["ok", "failed", "unavailable"],
    *,
    return_to: str | None,
    attempt: str | None,
) -> str:
    """The UI's /confirmed page: the result, where to go back to, and the opener's attempt id."""
    query = {"status": status, "returnTo": safe_return_to(return_to)}
    if (checked := safe_attempt(attempt)) is not None:
        query["attempt"] = checked
    return auth.landing(app, f"{CONFIRMED_PATH}?{urlencode(query)}")


def _landing(
    auth: "AuthService", app: Literal["console", "portal"], pending: dict[str, Any]
) -> Callable[..., str]:
    def build(*, confirmed: bool) -> str:
        return confirmed_landing(
            auth,
            app,
            "ok" if confirmed else "failed",
            return_to=pending.get("return_to"),
            attempt=pending.get("attempt"),
        )

    return build


async def _log_refusal(  # noqa: PLR0913 - the attempt's parts, keyword-only
    auth: "AuthService",
    session: Session,
    *,
    app: str,
    detail: str,
    client_ip: str | None,
    user_agent: str | None,
) -> None:
    """AC2: a refused confirmation is in the sign-in log (the reason in words; never a token)."""
    log.info("reauth_refused", detail=detail, subject=session.subject)
    facts = sign_in_log.SignInFacts(
        outcome=SignInOutcome.FAILED,
        app=SignInApp(app),
        method=SignInMethod(session.sign_in_method or SignInMethod.UNKNOWN.value),
        user_id=session.user_uuid,
        reason=REAUTH_FAILED,
        ip=client_ip,
        user_agent=user_agent,
        identity_provider=session.identity_provider,
    )
    await sign_in_log.record(auth.database, session.tenant_uuid, facts)
