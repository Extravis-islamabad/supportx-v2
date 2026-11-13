"""Identity rules: pure Python, no I/O (WP-006).

- validating ID-token claims (OIDC Core 3.1.3.7) once the signature has been checked;
- turning Keycloak organization memberships into tenant memberships (ADR-006, D-010);
- deciding the user type from roles;
- accepting only safe `returnTo` paths (no open redirects).
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, get_args
from urllib.parse import unquote, urlsplit

ORGANIZATIONS_CLAIM = "supportx_organizations"
ROLES_CLAIM = "supportx_roles"
TENANT_ATTRIBUTE = "tenant_id"
CLOCK_SKEW_SECONDS = 60
KNOWN_ROLES = frozenset({"tenant_admin", "technician", "requester"})
SUPPORTED_LOCALES = ("en", "ar", "ur")


class UserType(StrEnum):
    """Which app a user works in. Stored as a code; the UI shows a label."""

    TECHNICIAN = "technician"
    REQUESTER = "requester"
    # A connector acting in its own name (WP-040, REQ-INT-012): never signs in, never takes a
    # seat, never in people lists or pickers; only the integrations module makes one.
    SERVICE = "service"


class PersonType(StrEnum):
    """The types a person can be given in the people screens and imports (never `service`)."""

    TECHNICIAN = UserType.TECHNICIAN.value
    REQUESTER = UserType.REQUESTER.value


PERSON_TYPES = frozenset({UserType.TECHNICIAN, UserType.REQUESTER})


class NavLayout(StrEnum):
    """Where the console's navigation sits, per user (WP-011; a ServiceDesk Plus parity choice).

    Stored server-side so the choice follows the user to every device.
    """

    TOP = "top"
    SIDE = "side"
    SIDE_COMPACT = "side_compact"


class FormDensity(StrEnum):
    """How record forms lay out, per user (WP-020c): one column with labels above, or compact.

    Compact puts two columns side by side with the labels on the left (the denser layout
    ServiceDesk Plus users are used to); stored server-side so it follows the user.
    """

    COMFORTABLE = "comfortable"
    COMPACT = "compact"


class ThemeMode(StrEnum):
    """The person's theme (WP-042, REQ-ADM-062); not set: the browser picks (system)."""

    LIGHT = "light"
    DARK = "dark"
    HIGH_CONTRAST = "high_contrast"
    SYSTEM = "system"


# Text size in percent, in steps of ten (REQ-ADM-062); not set: 100.
TEXT_SCALES = frozenset(range(90, 151, 10))
DEFAULT_TEXT_SCALE = 100
# The regional choices a person may make (REQ-ADM-059); the same codes as the tenant's instance
# settings (organization), which supply the default for anyone who has not chosen.
WeekStart = Literal["monday", "sunday", "saturday"]
DateFormat = Literal["dd/mm/yyyy", "mm/dd/yyyy", "yyyy-mm-dd", "dd.mm.yyyy"]
TimeFormat = Literal["24h", "12h"]
# D-135: Western digits by default in every language; Arabic-Indic per person.
Digits = Literal["western", "arabic_indic"]
DIGITS: frozenset[str] = frozenset(get_args(Digits))
# D-137: how Urdu is set; Naskh by default, Nastaliq per person.
UrduScript = Literal["naskh", "nastaliq"]
URDU_SCRIPTS: frozenset[str] = frozenset(get_args(UrduScript))
WEEK_STARTS: frozenset[str] = frozenset(get_args(WeekStart))
DATE_FORMATS: frozenset[str] = frozenset(get_args(DateFormat))
TIME_FORMATS: frozenset[str] = frozenset(get_args(TimeFormat))


class ClaimsError(ValueError):
    """The ID token's claims are not acceptable; the login must fail."""


@dataclass(frozen=True)
class Membership:
    """One Keycloak organization the user belongs to, mapped to a SupportX tenant."""

    tenant_id: uuid.UUID
    alias: str


@dataclass(frozen=True)
class Identity:
    """Who logged in, as stated by validated ID-token claims."""

    subject: str
    email: str
    display_name: str
    locale: str
    roles: tuple[str, ...]
    memberships: tuple[Membership, ...]
    keycloak_session_id: str | None
    # The identity provider alias this sign-in came through (the `sx_idp` claim of the verified
    # ID token, WP-057 S1b), or None: a password, LDAP or direct-grant sign-in.
    identity_provider: str | None = None

    @property
    def user_type(self) -> Literal[UserType.TECHNICIAN, UserType.REQUESTER]:
        """Technician if the user holds a staff role, requester otherwise (never a service)."""
        return (
            UserType.TECHNICIAN
            if {"technician", "tenant_admin"} & set(self.roles)
            else UserType.REQUESTER
        )


def validate_claims(
    claims: Mapping[str, Any],
    *,
    issuer: str,
    client_id: str,
    nonce: str | None,
    now: datetime,
) -> None:
    """Issuer, audience, authorized party, expiry, issued-at and nonce checks.

    `nonce=None` is for tokens from a refresh, which carry no fresh nonce to compare.
    """
    if claims.get("iss") != issuer:
        msg = "issuer mismatch"
        raise ClaimsError(msg)
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if client_id not in audiences:
        msg = "audience mismatch"
        raise ClaimsError(msg)
    if len(audiences) > 1 and claims.get("azp") != client_id:
        msg = "authorized party mismatch"
        raise ClaimsError(msg)
    timestamp = now.timestamp()
    if not isinstance(claims.get("exp"), int) or claims["exp"] < timestamp - CLOCK_SKEW_SECONDS:
        msg = "token expired"
        raise ClaimsError(msg)
    if not isinstance(claims.get("iat"), int) or claims["iat"] > timestamp + CLOCK_SKEW_SECONDS:
        msg = "token issued in the future"
        raise ClaimsError(msg)
    if nonce is not None and claims.get("nonce") != nonce:
        msg = "nonce mismatch (possible replay)"
        raise ClaimsError(msg)
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        msg = "missing subject"
        raise ClaimsError(msg)


def memberships_from(claims: Mapping[str, Any]) -> tuple[Membership, ...]:
    """Tenants from the organization claim, sorted by alias. Malformed entries are skipped."""
    organizations = claims.get(ORGANIZATIONS_CLAIM)
    if not isinstance(organizations, Mapping):
        return ()
    found: dict[uuid.UUID, Membership] = {}
    for alias, details in organizations.items():
        values = details.get(TENANT_ATTRIBUTE) if isinstance(details, Mapping) else None
        if not isinstance(values, Sequence) or isinstance(values, str) or len(values) != 1:
            continue
        try:
            tenant_id = uuid.UUID(str(values[0]))
        except ValueError:
            continue
        found.setdefault(tenant_id, Membership(tenant_id=tenant_id, alias=str(alias)))
    return tuple(sorted(found.values(), key=lambda m: m.alias))


def identity_from(claims: Mapping[str, Any]) -> Identity:
    """Build the identity from already validated claims."""
    roles = claims.get(ROLES_CLAIM)
    locale = claims.get("locale")
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    name = str(claims.get("name") or email).strip()
    sid = claims.get("sid")
    return Identity(
        subject=str(claims["sub"]),
        email=email,
        display_name=name[:200] or email,
        locale=locale if locale in SUPPORTED_LOCALES else "en",
        roles=tuple(sorted(r for r in roles if r in KNOWN_ROLES))
        if isinstance(roles, list)
        else (),
        memberships=memberships_from(claims),
        keycloak_session_id=sid if isinstance(sid, str) else None,
        identity_provider=_idp(claims.get(IDP_CLAIM)),
    )


IDP_CLAIM = "sx_idp"  # deploy/helm/supportx/files/keycloak: a user-session note, never userinfo
IDP_ALIAS_MAX = 80  # sign_in_events.identity_provider


def _idp(value: object) -> str | None:
    """A non-empty alias, or None (absent, empty or not a string: never trusted as SSO)."""
    if isinstance(value, str) and value.strip() and len(value) <= IDP_ALIAS_MAX:
        return value
    return None


_SAFE_PATH = re.compile(r"^/[A-Za-z0-9\-._~!$&'()*+,;=:@%/?#]*$")


def safe_return_to(value: str | None) -> str:
    r"""A same-origin relative path to land on after login, or `/`.

    Rejects anything a browser could resolve to another origin: absolute URLs, scheme-relative
    `//host`, backslash tricks (`/\\host`), encoded variants of those, and control characters.
    """
    if not value:
        return "/"
    decoded = unquote(value)
    if (
        not value.startswith("/")
        or value.startswith(("//", "/\\"))
        or decoded.startswith(("//", "/\\"))
        or "\\" in decoded
        or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in decoded)  # noqa: PLR2004 - ASCII controls
        or not _SAFE_PATH.fullmatch(value)
    ):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value
