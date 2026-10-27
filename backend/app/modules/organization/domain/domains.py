"""Custom domain rules (WP-017, REQ-PRT-016 AC3, REQ-SEC-004; D-090). No I/O.

A tenant proves a domain points at this installation by serving a token: SupportX fetches
`http://<host>/api/v1/public/domain-check/<token>` and expects the installation's HMAC of the token
back. Only this installation can compute it, so a correct answer means the address reaches us (the
same idea as ACME's HTTP-01 challenge); no DNS library is needed (D-090).

Certificates uploaded for on-prem single-node installations are checked before they are stored:
the key matches the first certificate, it names the host (or a wildcard covering it), and it is
valid now.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

if TYPE_CHECKING:
    from datetime import datetime

_LABEL = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"^{_LABEL}(\.{_LABEL})+$")
MAX_HOST = 253
CHECK_PATH = "/api/v1/public/domain-check/"


class DomainStatus(StrEnum):
    """Whether the address is proven to reach this installation."""

    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class TlsMode(StrEnum):
    """Who provides the certificate."""

    AUTOMATIC = "automatic"  # ACME through the platform (cert-manager)
    UPLOADED = "uploaded"  # the tenant's own certificate (on-prem single node)


class TlsStatus(StrEnum):
    """Where the certificate stands (labels: `domain.tls.<code>`)."""

    WAITING = "waiting"  # the domain is not verified yet
    PENDING = "pending"  # verified; the certificate is being issued
    ISSUED = "issued"
    FAILED = "failed"
    NOT_MANAGED = "not_managed"  # this installation does not manage certificates itself


class DomainProblem(ValueError):
    """A host or certificate that cannot be used (code for a translated message)."""

    def __init__(self, *, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalise_domain(value: str, base_domain: str | None) -> str:
    """A lower-case host name a tenant may add, or DomainProblem.

    IP addresses, single labels and the installation's own tenant subdomains are refused: those
    are not a tenant's to claim.
    """
    host = value.strip().lower().rstrip(".")
    if host.startswith(("http://", "https://")) or "/" in host or ":" in host:
        raise DomainProblem(code="domain_invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise DomainProblem(code="domain_invalid")
    if len(host) > MAX_HOST or not _HOST.fullmatch(host):
        raise DomainProblem(code="domain_invalid")
    if base_domain:
        base = base_domain.lower().strip(".")
        if host == base or host.endswith("." + base):
            raise DomainProblem(code="domain_reserved")
    return host


def proof(secret: bytes, token: str) -> str:
    """What this installation answers for `token` (hex HMAC-SHA256)."""
    return hmac.new(secret, f"supportx-domain:{token}".encode(), hashlib.sha256).hexdigest()


def proof_matches(secret: bytes, token: str, answer: str) -> bool:
    """Whether a fetched answer is this installation's proof for `token`."""
    return hmac.compare_digest(proof(secret, token), answer.strip())


def blocked_address(address: str) -> bool:
    """Addresses the domain check never contacts (the host itself, metadata services ...).

    Private networks are allowed: on-prem custom domains often resolve to them.
    """
    ip = ipaddress.ip_address(address)
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.is_reserved)
    )


@dataclass(frozen=True)
class CheckedCertificate:
    """An uploaded certificate that passed the checks."""

    chain_pem: str
    key_pem: bytes  # normalised PKCS#8, unencrypted (encrypted before it is stored)
    not_after: datetime


def _covers(name: str, host: str) -> bool:
    name = name.lower().rstrip(".")
    if name.startswith("*."):
        suffix = name[1:]
        return host.endswith(suffix) and "." not in host[: -len(suffix)]
    return name == host


def check_certificate(chain_pem: str, key_pem: str, host: str, now: datetime) -> CheckedCertificate:
    """The certificate and key for `host`, or DomainProblem saying what is wrong."""
    try:
        chain = x509.load_pem_x509_certificates(chain_pem.encode())
    except ValueError:
        raise DomainProblem(code="certificate_unreadable") from None
    try:
        key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    except (ValueError, TypeError):
        raise DomainProblem(code="private_key_unreadable") from None
    if not isinstance(
        key, rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey
    ):
        raise DomainProblem(code="private_key_unreadable")
    leaf = chain[0]
    public = serialization.PublicFormat.SubjectPublicKeyInfo
    encoding = serialization.Encoding.DER
    if key.public_key().public_bytes(encoding, public) != leaf.public_key().public_bytes(
        encoding, public
    ):
        raise DomainProblem(code="certificate_key_mismatch")
    try:
        names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns_names = names.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        dns_names = []
    if not any(_covers(name, host) for name in dns_names):
        raise DomainProblem(code="certificate_wrong_host")
    if not (leaf.not_valid_before_utc <= now < leaf.not_valid_after_utc):
        raise DomainProblem(code="certificate_not_valid_now")
    normalised = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return CheckedCertificate(
        chain_pem="".join(cert.public_bytes(serialization.Encoding.PEM).decode() for cert in chain),
        key_pem=normalised,
        not_after=leaf.not_valid_after_utc,
    )
