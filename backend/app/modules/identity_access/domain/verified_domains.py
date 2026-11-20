"""Verified e-mail domains, pure rules (WP-057 S5d, REQ-SEC-010; lane B's conditions).

A tenant proves it owns a domain by publishing a TXT record SupportX gave it. Only then does the
domain count as the tenant's (AC1), and only one tenant can hold a domain verified (AC2).

- **Normalising:** IDNA (an Arabic or Urdu domain becomes its `xn--` form), lowercase, no
  leading "@", no trailing dot.
- **Refused** (lane B (4)): a single label, a free-mail domain everyone shares
  (`PUBLIC_MAIL_DOMAINS`), and a public suffix (a small built-in list; a public-suffix library
  would need asking).
- **The token** (lane B (1)): 32 random bytes, shown once; only its SHA-256 is stored. A re-add
  makes a new one. The record is `supportx-verification=<token>` at `_supportx.<domain>`.
- **Lapsing** (lane B (3)): a verified domain whose record is gone un-verifies only after 3
  failed checks spread over at least 72 hours, so a DNS hiccup never stops anyone's sign-in.
"""

import hashlib
import re
import secrets
from base64 import b32encode
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from app.modules.identity_access.domain.sso import PUBLIC_MAIL_DOMAINS

RECORD_HOST = "_supportx"
RECORD_PREFIX = "supportx-verification="
TOKEN_BYTES = 32
LAPSE_FAILURES = 3
LAPSE_SPAN = timedelta(hours=72)
RECHECK_EVERY = timedelta(days=30)
PENDING_RETRY_FOR = timedelta(days=7)
MAX_DOMAINS = 50
INVALID = "domain_invalid"
SINGLE_LABEL = "domain_single_label"
PUBLIC_MAIL = "domain_public_mail"
PUBLIC_SUFFIX = "domain_public_suffix"
DNS_MAX = 253
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

# Registries' own second levels: never a company's domain (a short built-in list, not a library).
PUBLIC_SUFFIXES = frozenset(
    {
        "ac.uk", "co.uk", "gov.uk", "ltd.uk", "me.uk", "net.uk", "org.uk", "plc.uk",
        "com.pk", "edu.pk", "gov.pk", "net.pk", "org.pk",
        "com.sa", "edu.sa", "gov.sa", "net.sa", "org.sa",
        "ac.ae", "co.ae", "gov.ae", "net.ae", "org.ae",
        "com.au", "net.au", "org.au", "co.in", "net.in", "org.in", "co.nz", "co.za", "com.br",
        "com.cn", "com.eg", "com.qa", "com.kw", "com.om", "com.bh", "co.jp", "com.tr",
        "github.io", "herokuapp.com", "azurewebsites.net", "cloudfront.net", "appspot.com",
        "blogspot.com", "netlify.app", "vercel.app", "pages.dev", "workers.dev",
    }
)  # fmt: skip


class DomainState(StrEnum):
    """Where a domain is in its proof."""

    PENDING = "pending"
    VERIFIED = "verified"
    LAPSED = "lapsed"


class DomainProblem(ValueError):
    """A domain that can't be added (`code` names why, for its label)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalise(raw: str) -> str:
    """The domain as SupportX keeps it, or DomainProblem (`domain_invalid`, `_public`, ...)."""
    text = raw.strip().lstrip("@").rstrip(".").lower()
    if not text:
        raise DomainProblem(INVALID)
    try:
        ascii_form = text.encode("idna").decode("ascii")
    except UnicodeError:
        raise DomainProblem(INVALID) from None
    labels = ascii_form.split(".")
    if len(ascii_form) > DNS_MAX or not all(_LABEL.match(label) for label in labels):
        raise DomainProblem(INVALID)
    if len(labels) < 2:  # noqa: PLR2004 - a domain has at least two labels
        raise DomainProblem(SINGLE_LABEL)
    if ascii_form in PUBLIC_MAIL_DOMAINS:
        raise DomainProblem(PUBLIC_MAIL)
    if ascii_form in PUBLIC_SUFFIXES:
        raise DomainProblem(PUBLIC_SUFFIX)
    return ascii_form


@dataclass(frozen=True)
class Token:
    """A new proof token: `value` is shown once, `digest` is what is stored."""

    value: str
    digest: bytes


def new_token() -> Token:
    """32 random bytes, as base32 without padding (safe in a TXT record)."""
    value = b32encode(secrets.token_bytes(TOKEN_BYTES)).decode("ascii").rstrip("=").lower()
    return Token(value=value, digest=digest_of(value))


def digest_of(value: str) -> bytes:
    """The stored form of a token."""
    return hashlib.sha256(value.encode("ascii")).digest()


def record_name(domain: str) -> str:
    """Where the TXT record goes."""
    return f"{RECORD_HOST}.{domain}"


def record_value(token: str) -> str:
    """What the TXT record says."""
    return f"{RECORD_PREFIX}{token}"


def proves(texts: list[str], digest: bytes) -> bool:
    """Whether any TXT string is the record for the token whose digest is stored."""
    for text in texts:
        value = text.strip().strip('"')
        if value.startswith(RECORD_PREFIX):
            given = value[len(RECORD_PREFIX) :].strip()
            if given.isascii() and secrets.compare_digest(digest_of(given), digest):
                return True
    return False


def lapses(failures: int, failing_since: datetime | None, now: datetime) -> bool:
    """A verified domain un-verifies after 3 failed checks over at least 72 hours (lane B (3))."""
    return (
        failures >= LAPSE_FAILURES
        and failing_since is not None
        and now - failing_since >= LAPSE_SPAN
    )


def due(state: DomainState, last_checked: datetime | None, added: datetime, now: datetime) -> bool:
    """Whether the daily schedule checks a domain now.

    Pending: daily for 7 days after it was added (then "Check now" only); verified: every 30
    days, and daily while a check is failing (the caller passes the failure's time); lapsed:
    never by itself.
    """
    if state is DomainState.PENDING:
        return now - added <= PENDING_RETRY_FOR and (
            last_checked is None or now - last_checked >= timedelta(days=1)
        )
    if state is DomainState.VERIFIED:
        return last_checked is None or now - last_checked >= RECHECK_EVERY
    return False


def kc_verified(domains: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """The organisation's Keycloak domains with `name` marked verified (added when missing).

    An SSO set-up's routing (`identityProviderAlias`, `autoRedirect`) on it is kept as it is.
    """
    out = [dict(d) for d in domains]
    for item in out:
        if item.get("name") == name:
            item["verified"] = True
            return out
    out.append({"name": name, "verified": True})
    return out


def kc_without(domains: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """The organisation's Keycloak domains without `name`.

    Lane B (2): a lapsed or deleted domain leaves the organisation, so it never blocks another
    tenant.
    """
    return [dict(d) for d in domains if d.get("name") != name]
