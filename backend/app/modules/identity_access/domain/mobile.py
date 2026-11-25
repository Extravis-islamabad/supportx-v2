"""Mobile sign-in rules (ADR-044): pure functions, no I/O.

The phone runs the same browser sign-in as the web apps, in the system browser. At the end the
server hands the app a one-time code through the app's verified return link, and the app
exchanges it for its session ID. A code caught by another app on the phone is useless without
the verifier: the app sends the SHA-256 of a random verifier when it starts (as PKCE does,
RFC 7636) and the verifier itself when it exchanges.
"""

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

HANDOFF_TTL = timedelta(seconds=60)
# The header that carries a mobile session ID. Browsers never send it on their own, and the web
# apps never see the ID (it stays in an HttpOnly cookie there), so it adds no browser attack path.
SESSION_HEADER = "X-SupportX-Session"
# base64url without padding of 32 bytes: exactly 43 characters.
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
# RFC 7636 verifier alphabet and length.
_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
# The app's own version (app.json), shown in the person's session list (ADR-044 item 5).
_APP_VERSION = re.compile(r"^[0-9]{1,4}(\.[0-9]{1,4}){0,3}$")
PLATFORMS = frozenset({"ios", "android"})


@dataclass(frozen=True, slots=True)
class MobileStart:
    """What the app sends when a sign-in starts: its challenge, and what the session list shows."""

    challenge: str
    platform: str | None = None
    app_version: str | None = None

    def pending(self) -> dict[str, Any]:
        """The fields kept with the pending login."""
        return {
            "mobile_challenge": self.challenge,
            "mobile_platform": self.platform,
            "mobile_version": self.app_version,
        }

    def query(self) -> dict[str, str]:
        """The login query that starts the same mobile sign-in again (MFA, to the portal)."""
        found = {"mobile_challenge": self.challenge}
        if self.platform is not None:
            found["mobile_platform"] = self.platform
        if self.app_version is not None:
            found["mobile_version"] = self.app_version
        return found

    @classmethod
    def from_pending(cls, pending: dict[str, Any]) -> "MobileStart | None":
        """The mobile part of a pending login; None for a web sign-in."""
        challenge = pending.get("mobile_challenge")
        if challenge is None:
            return None
        return cls(str(challenge), pending.get("mobile_platform"), pending.get("mobile_version"))


def valid_challenge(value: str) -> bool:
    """A SHA-256 challenge in base64url without padding."""
    return bool(_CHALLENGE.fullmatch(value))


def valid_app_version(value: str) -> bool:
    """Digits and dots only (e.g. 1.4.2): what the session list may show, nothing else."""
    return bool(_APP_VERSION.fullmatch(value))


def challenge_for(verifier: str) -> str:
    """The S256 challenge of a verifier (base64url of its SHA-256, no padding)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verifier_matches(verifier: str, challenge: str) -> bool:
    """Whether `verifier` is the one the challenge was made from (constant-time compare)."""
    if not _VERIFIER.fullmatch(verifier):
        return False
    return hmac.compare_digest(challenge_for(verifier), challenge)


def app_return(redirect_uri: str, **params: str) -> str:
    """The app's return link with `handoff` or `auth_error` in its query."""
    separator = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{separator}{urlencode(params)}"


# --- the tenant's mobile app policy (WP-057 S6b; REQ-SEC-047) --------------------------------
#
# Server-enforced: whether the app may sign in (AC1, refused before any session exists, with the
# tenant's message), a second factor for mobile sign-ins, and the mobile session's length.
# Client-enforced, by the app: the device unlock after time in the background (AC2) and clearing
# local data at sign-out. The server cannot prove those happened; it only states the policy.

MOBILE_NOT_ALLOWED = "mobile_not_allowed"  # the app's sign-in refused: the tenant's message
UNLOCK_AFTER_MIN, UNLOCK_AFTER_MAX = 1, 60  # minutes in the background before a device unlock
REFUSAL_MESSAGE_MAX = 500  # characters, per language, after cleaning
MESSAGE_LANGUAGES = frozenset({"en", "ar", "ur"})  # the product's languages (lane B's condition 3)
_CONTROL = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069]")
_SPACES = re.compile(r"[ \t\r\n]+")


@dataclass(frozen=True)
class MobilePolicy:
    """A tenant's mobile app policy; the defaults when it has set none (Appendix A style)."""

    allowed: bool = True
    refusal_message: dict[str, str] | None = None  # per language; None: the built-in text
    mfa_required: bool = False
    device_unlock_required: bool = False
    unlock_after_minutes: int = 5
    clear_on_sign_out: bool = True


def _plain(text: str) -> str:
    return _SPACES.sub(" ", _CONTROL.sub("", text)).strip()


def clean_message(text: str) -> str:
    """Plain text the app shows as is: no control or direction characters, one line, capped.

    Admin-written, shown on a phone outside the web app's sanitiser, so it is cleaned on save and
    again on render (lane B): no markup is interpreted (the app renders text, never HTML), and
    whitespace runs become one space.
    """
    return _plain(text)[:REFUSAL_MESSAGE_MAX]


def refusal_message(policy: MobilePolicy, language: str, default_language: str) -> str | None:
    """The tenant's message in the person's language, else the tenant default; None: built-in."""
    messages = policy.refusal_message or {}
    for code in (language, default_language):
        text = clean_message(messages.get(code) or "")
        if text:
            return text
    return None


def policy_problems(values: dict[str, Any]) -> list[tuple[str, str]]:
    """Field problems of a policy as sent: (field, code); the server's rules, shown by the form."""
    problems: list[tuple[str, str]] = []
    minutes = values.get("unlock_after_minutes")
    if minutes is not None and (
        isinstance(minutes, bool)
        or not isinstance(minutes, int)
        or not UNLOCK_AFTER_MIN <= minutes <= UNLOCK_AFTER_MAX
    ):
        problems.append(("unlock_after_minutes", "out_of_range"))
    messages = values.get("refusal_message")
    if messages is not None:
        if not isinstance(messages, dict) or not all(
            k in MESSAGE_LANGUAGES and isinstance(v, str) for k, v in messages.items()
        ):
            problems.append(("refusal_message", "invalid"))
        elif any(len(_plain(v)) > REFUSAL_MESSAGE_MAX for v in messages.values()):
            problems.append(("refusal_message", "too_long"))
    return problems
