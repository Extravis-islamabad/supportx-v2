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
