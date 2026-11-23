"""Certificate and secret expiry alerts (REQ-SEC-011; WP-057 S2b-2): 30, 7, 1 days, then expired."""

from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.modules.identity_access.domain.expiry import EXPIRED, certificates, due

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _pem(not_after: datetime, name: str = "idp") -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_after - timedelta(days=365))
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _bare(pem: str) -> str:
    """Keycloak's form: the base64 body only, no PEM header."""
    return "".join(line for line in pem.splitlines() if "CERTIFICATE" not in line)


def test_each_threshold_alerts_once_in_order() -> None:
    expires = NOW + timedelta(days=60)
    assert due(expires, NOW, set()) == (None, set())
    assert due(expires, expires - timedelta(days=30), set()) == (30, {30})
    assert due(expires, expires - timedelta(days=20), {30}) == (None, set())
    assert due(expires, expires - timedelta(days=7), {30}) == (7, {7})
    assert due(expires, expires - timedelta(hours=23), {30, 7}) == (1, {1})
    assert due(expires, expires + timedelta(minutes=1), {30, 7, 1}) == (EXPIRED, {EXPIRED})
    assert due(expires, expires + timedelta(days=9), {30, 7, 1, EXPIRED}) == (None, set())


def test_a_late_run_sends_only_the_most_urgent_and_marks_the_rest() -> None:
    expires = NOW + timedelta(hours=12)
    assert due(expires, NOW, set()) == (1, {30, 7, 1})
    assert due(NOW - timedelta(days=2), NOW, set()) == (EXPIRED, {30, 7, 1, EXPIRED})


def test_up_to_two_certificates_are_read_in_either_form() -> None:
    soon, later = NOW + timedelta(days=5), NOW + timedelta(days=400)
    listed = f"{_bare(_pem(soon, 'old'))},{_pem(later, 'new')}"
    found = certificates(listed)
    assert [c.not_after for c in found] == [soon, later]
    assert len({c.fingerprint for c in found}) == 2  # each its own item
    assert all(len(c.fingerprint) == 64 for c in found)  # SHA-256, hex
    assert certificates(f"{listed},{_pem(later, 'third')}") == found  # at most two
    assert certificates("not a certificate,") == ()
    assert certificates(None) == ()
