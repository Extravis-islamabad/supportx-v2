"""Dev-only quick sign-in (D-151): the showcase personas and the rules around them. Pure, no I/O.

One button per persona on the local console and portal (`/dev/sign-in`), so a browser-driving QA
run signs in without typing a password. The BFF still signs the persona in through Keycloak (the
password grant, then the normal session path), so sessions, MFA policy, revocation and logout
behave as usual. Every persona but one has a TOTP authenticator pre-enrolled by the showcase seed
from a dev-only key, so the server can complete the second step; the "new starter" has none, so
QA can test the real two-step setup in the browser.
"""

import hashlib
import hmac
import ipaddress
import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SHOWCASE_SLUG = "showcase"
TOTP_PERIOD = 30  # seconds; the realm's OTP policy (deploy/helm/supportx/files/keycloak)
TOTP_DIGITS = 6
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True, slots=True)
class Persona:
    """A showcase sign-in a QA run may use."""

    code: str  # labels: dev_persona.<code>
    email: str
    app: Literal["console", "portal"]
    enrolled: bool  # a pre-enrolled TOTP authenticator (the server completes the second step)


PERSONAS: tuple[Persona, ...] = (
    Persona("admin", "admin@showcase.test", "console", enrolled=True),
    Persona("technician", "tech@showcase.test", "console", enrolled=True),
    Persona("lead", "lead@showcase.test", "console", enrolled=True),
    Persona("approver", "approver@showcase.test", "portal", enrolled=True),
    Persona("requester", "requester@showcase.test", "portal", enrolled=True),
    # Never pre-enrolled: signs in the normal way and sets up two-step sign-in (Haider, D-151).
    Persona("new_starter", "newstarter@showcase.test", "portal", enrolled=False),
)


def persona_by_email(email: str) -> Persona | None:
    """The persona with this sign-in, or None."""
    return next((p for p in PERSONAS if p.email == email.lower()), None)


def persona(code: str) -> Persona | None:
    """The persona with this code, or None."""
    return next((p for p in PERSONAS if p.code == code), None)


def totp_value(key: bytes, email: str) -> str:
    """The persona's authenticator secret, derived from the dev-only key (never stored in git).

    Keycloak keeps an OTP credential's secret as a string and keys its HMAC with that string's
    bytes, so the value is a hex string, the same on both sides.
    """
    return hmac.new(key, f"supportx-dev-totp:{email.lower()}".encode(), hashlib.sha256).hexdigest()[
        :40
    ]


def time_step(at: datetime) -> int:
    """The TOTP time step of an instant (RFC 6238)."""
    return int(at.timestamp()) // TOTP_PERIOD


def totp(value: str, step: int) -> str:
    """The six-digit code of a time step (RFC 6238 with HMAC-SHA1, as the realm's policy)."""
    mac = hmac.new(value.encode(), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 10**TOTP_DIGITS:0{TOTP_DIGITS}d}"


def candidate_steps(now_step: int) -> tuple[int, int]:
    """The steps a code may be sent for, now and next.

    Keycloak refuses a code used before and looks one step ahead, so a second sign-in inside the
    same 30 s takes the next step's code.
    """
    return (now_step, now_step + 1)


def refusal(error: str, description: str | None) -> str:
    """Keycloak's refusal of the password grant as a reason code the page names (labelled)."""
    text = (description or "").lower()
    if "not fully set up" in text:
        return "mfa_setup_required"
    if "disabled" in text:
        return "account_locked"  # the realm's brute-force lock, or a disabled account
    if error in {"unauthorized_client", "invalid_client"}:
        return "grant_not_allowed"  # not the dev realm: the password grant is off
    if "invalid user credentials" in text:
        return "credentials_refused"  # the .env password or authenticator key is not the seed's
    return "keycloak_refused"


def _loopback(address: str | None) -> bool:
    if not address:
        return False
    try:
        return ipaddress.ip_address(address.strip("[]")).is_loopback
    except ValueError:
        return False


def _host_name(host: str | None) -> str:
    if not host:
        return ""
    if host.startswith("["):  # [::1]:5173
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


# Headers a proxy or tunnel adds to say where a request really came from, or for which host.
# Any of them naming something not local means the request is not local (fail closed).
FORWARDED_ADDRESS_HEADERS = (
    "x-forwarded-for",
    "forwarded",
    "x-real-ip",
    "cf-connecting-ip",
    "true-client-ip",
    "x-original-forwarded-for",
)
FORWARDED_HOST_HEADERS = ("x-forwarded-host", "x-original-host")


def is_local(
    client_address: str | None,
    host: str | None,
    forwarded: list[str],
    forwarded_hosts: list[str] | None = None,
) -> bool:
    """Loopback client AND a localhost Host header, and nothing forwarded from elsewhere."""
    if not _loopback(client_address) or _host_name(host).lower() not in LOCAL_HOSTS:
        return False
    for value in forwarded_hosts or []:
        for item in value.split(","):
            if _host_name(item.strip()).lower() not in LOCAL_HOSTS:
                return False
    for value in forwarded:  # X-Forwarded-For / Forwarded from a proxy: every hop local
        for part in value.replace(";", ",").split(","):
            item = part.strip()
            if item.lower().startswith("for="):
                item = item[4:].strip('"')
            if (
                item
                and "=" not in item
                and not _loopback(item.rsplit(":", 1)[0] if item.count(":") == 1 else item)
            ):
                return False
    return True
