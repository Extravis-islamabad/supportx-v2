"""The sign-in log's words (REQ-AUD-015; WP-057 S1a). Pure: no I/O.

- **Device:** a short "browser on system" from the User-Agent, never the raw header (it is long,
  fingerprint-like and personal data): at most DEVICE_MAX characters, codes the UI labels.
- **Reasons:** Keycloak's event error codes as SupportX's own reason codes, so a failure reads in
  plain words ("wrong password", "the identity provider refused") in every language. A code we do
  not know becomes `other`, never the raw text.
"""

import re
from enum import StrEnum

DEVICE_MAX = 120


class Outcome(StrEnum):
    """What happened (sign_in_events.outcome)."""

    SUCCESS = "success"
    FAILED = "failed"
    SIGNED_OUT = "signed_out"
    LOCKED = "locked"
    MFA_FAILED = "mfa_failed"


class Method(StrEnum):
    """How the person signed in (sign_in_events.method)."""

    PASSWORD = "password"  # noqa: S105 - a sign-in method code, not a secret
    SINGLE_SIGN_ON = "single_sign_on"
    DIRECTORY = "directory"
    MOBILE = "mobile"
    API_KEY = "api_key"
    UNKNOWN = "unknown"


class SignInApp(StrEnum):
    """Where (sign_in_events.app)."""

    CONSOLE = "console"
    PORTAL = "portal"
    API = "api"
    MOBILE = "mobile"


class Source(StrEnum):
    """Who decided: SupportX's sign-in layer or Keycloak (sign_in_events.source)."""

    BFF = "bff"
    KEYCLOAK = "keycloak"


# Keycloak's event errors (its EventType *_ERROR details) → our reason codes (labelled).
KEYCLOAK_REASONS: dict[str, str] = {
    "invalid_user_credentials": "wrong_password",
    "user_not_found": "unknown_person",
    "user_disabled": "account_disabled",
    "user_temporarily_disabled": "account_locked",
    "invalid_totp": "wrong_code",
    "invalid_authentication_session": "sign_in_expired",
    "expired_code": "sign_in_expired",
    "identity_provider_error": "identity_provider_refused",
    "identity_provider_login_failure": "identity_provider_refused",
    "invalid_saml_response": "identity_provider_bad_response",
    "invalid_signature": "identity_provider_bad_signature",
    "invalid_client_credentials": "wrong_client",
}
OTHER_REASON = "other"


def keycloak_reason(error: str | None) -> str | None:
    """Our reason code for a Keycloak event error (None for a success)."""
    if not error:
        return None
    return KEYCLOAK_REASONS.get(error, OTHER_REASON)


def keycloak_outcome(event_type: str, error: str | None) -> Outcome:
    """The outcome of a Keycloak login event."""
    if error == "user_temporarily_disabled":
        return Outcome.LOCKED
    if error == "invalid_totp":
        return Outcome.MFA_FAILED
    if event_type.endswith("_ERROR") or error:
        return Outcome.FAILED
    if event_type == "LOGOUT":
        return Outcome.SIGNED_OUT
    return Outcome.SUCCESS


_BROWSERS = (  # first match wins: Edge and Opera also say "Chrome", Chrome also says "Safari"
    ("Edg/", "edge"),
    ("OPR/", "opera"),
    ("Firefox/", "firefox"),
    ("Chrome/", "chrome"),
    ("Safari/", "safari"),
)
_SYSTEMS = (
    ("Windows", "windows"),
    ("iPhone", "ios"),
    ("iPad", "ios"),
    ("Android", "android"),
    ("Mac OS X", "macos"),
    ("CrOS", "chromeos"),
    ("Linux", "linux"),
)
_APP = re.compile(r"^SupportX(?:Mobile)?/[\w.]+")


def device(user_agent: str | None) -> str | None:
    """Browser and system codes from a User-Agent ("chrome:windows"), or None when unknown.

    The UI labels both parts ("Chrome on Windows"). The mobile app sends its own name.
    """
    if not user_agent:
        return None
    text = user_agent[:512]
    if _APP.match(text):
        return "supportx_app:" + _first(text, _SYSTEMS, "other")
    browser = _first(text, _BROWSERS, "other")
    system = _first(text, _SYSTEMS, "other")
    if (browser, system) == ("other", "other"):
        return None
    return f"{browser}:{system}"[:DEVICE_MAX]


def _first(text: str, table: tuple[tuple[str, str], ...], fallback: str) -> str:
    return next((code for marker, code in table if marker in text), fallback)
