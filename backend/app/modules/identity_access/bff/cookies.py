"""The BFF's cookies (architecture.md §11.1): the session, and a sign-in's browser binding.

The session cookie is the only lasting thing the browser holds; the binding cookie lives only as
long as a pending sign-in.
"""

import hashlib

from fastapi import Response

from app.core.config import Settings

DEV_COOKIE_NAME = "supportx_session"
# __Host- makes the browser enforce Secure, Path=/ and no Domain: the cookie cannot be set or
# overwritten by a sibling subdomain.
PRODUCTION_COOKIE_NAME = "__Host-supportx_session"


def cookie_name(settings: Settings) -> str:
    """`__Host-` prefixed in production (always Secure there), plain name elsewhere."""
    return PRODUCTION_COOKIE_NAME if settings.profile == "production" else DEV_COOKIE_NAME


def set_session_cookie(response: Response, settings: Settings, session_id: str) -> None:
    """HttpOnly (no JavaScript access), SameSite=Lax, Secure unless plain-http dev, Path=/.

    No Max-Age: a browser-session cookie. The server enforces idle and absolute timeouts.
    """
    response.set_cookie(
        cookie_name(settings),
        session_id,
        httponly=True,
        secure=settings.effective_session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Remove the cookie (same attributes, so the browser matches and deletes it)."""
    response.delete_cookie(
        cookie_name(settings),
        httponly=True,
        secure=settings.effective_session_cookie_secure,
        samesite="lax",
        path="/",
    )


# The login-binding cookie (audit row 4, login CSRF): set when a browser starts a sign-in, needed
# by the callback. One cookie per pending login, named after a hash of its state, so two tabs
# signing in at once each keep their own (a single cookie would let the second start break the
# first). `__Host-` in production for the same reason as the session cookie: no sibling
# subdomain can plant one, which would defeat the binding. That prefix needs Path=/.
DEV_LOGIN_COOKIE_PREFIX = "supportx_login_"
PRODUCTION_LOGIN_COOKIE_PREFIX = "__Host-supportx_login_"


def login_cookie_name(settings: Settings, state: str) -> str:
    """The binding cookie of the login with this `state`: 16 hex digits of its SHA-256.

    A hash, not the state itself: the name stays short and cookie-safe whatever Keycloak sends
    back, and the state (a one-time secret) never sits in a cookie name.
    """
    prefix = (
        PRODUCTION_LOGIN_COOKIE_PREFIX
        if settings.profile == "production"
        else DEV_LOGIN_COOKIE_PREFIX
    )
    return prefix + hashlib.sha256(state.encode()).hexdigest()[:16]


def set_login_cookie(
    response: Response, settings: Settings, state: str, token: str, max_age: int
) -> None:
    """Set a login's binding cookie, gone when its login state expires (`max_age` seconds).

    HttpOnly, SameSite=Lax (Keycloak's redirect back is a top-level GET, so Lax sends it), Secure
    unless plain-http dev.
    """
    response.set_cookie(
        login_cookie_name(settings, state),
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.effective_session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_login_cookie(response: Response, settings: Settings, state: str) -> None:
    """Remove a login's binding cookie: the callback spends it, success or failure."""
    response.delete_cookie(
        login_cookie_name(settings, state),
        httponly=True,
        secure=settings.effective_session_cookie_secure,
        samesite="lax",
        path="/",
    )
