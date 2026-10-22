"""The session cookie: the only thing the browser ever holds (architecture.md §11.1)."""

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
