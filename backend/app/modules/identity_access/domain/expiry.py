"""When a sign-in certificate or secret is about to run out (REQ-SEC-011; WP-057 S2b-2).

Pure: no I/O (parsing a certificate is computation). Tenant admins hear at 30, 7 and 1 days
before, and once more when it has run out, each exactly once per certificate or secret (the
marks table remembers which went). A job that was down past several thresholds sends only the
most urgent one and marks the earlier ones as passed: nobody gets three alerts at once.

What expires:
- **a SAML provider's signing certificates:** Keycloak keeps up to two, comma-separated, so a
  rollover can overlap (`signingCertificate`). Each one is its own item;
- **an OIDC client secret:** its expiry is a date an admin enters (identity providers such as
  Entra ID show it; SupportX never reads the secret).
"""

import base64
import binascii
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes

THRESHOLDS_DAYS = (30, 7, 1)
EXPIRED = 0  # the mark of "it has run out"
MAX_CERTIFICATES = 2


@dataclass(frozen=True)
class Certificate:
    """One signing certificate: its fingerprint (which one) and when it runs out."""

    fingerprint: str  # SHA-256, hex: names the certificate in marks, never the certificate
    not_after: datetime


def _pem(text: str) -> str:
    body = text.strip()
    if "BEGIN CERTIFICATE" in body:
        return body
    return f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----"


def certificates(signing_certificate: str | None) -> tuple[Certificate, ...]:
    """The readable certificates of a comma-separated list (Keycloak's form), at most two.

    An unreadable entry is skipped here: saving a provider refuses one already
    (`sso_certificate_unreadable`), so only a certificate changed in Keycloak directly could be.
    """
    found: list[Certificate] = []
    for part in (p.strip() for p in (signing_certificate or "").split(",")):
        if not part:
            continue
        try:
            cert = x509.load_pem_x509_certificate(_pem(part).encode())
        except (ValueError, binascii.Error):
            continue
        digest = cert.fingerprint(hashes.SHA256())  # always SHA-256: never the signing hash
        found.append(
            Certificate(base64.b16encode(digest).decode().lower(), cert.not_valid_after_utc)
        )
        if len(found) == MAX_CERTIFICATES:
            break
    return tuple(found)


def due(not_after: datetime, now: datetime, sent: Iterable[int]) -> tuple[int | None, set[int]]:
    """Which alert to send now (days before, or EXPIRED), and every mark to record with it.

    None when nothing is due. The marks include the thresholds already passed and not yet
    sent, so a late run sends one alert, the most urgent.
    """
    done = set(sent)
    left = not_after - now
    passed = [days for days in THRESHOLDS_DAYS if left <= timedelta(days=days)]
    if left <= timedelta(0):
        passed.append(EXPIRED)
    waiting = [mark for mark in passed if mark not in done]
    if not waiting:
        return None, set()
    most_urgent = min(waiting)
    return most_urgent, set(waiting)
