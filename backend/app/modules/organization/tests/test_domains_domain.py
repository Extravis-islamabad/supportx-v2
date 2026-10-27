"""Custom domain rules and the proof fetcher's limits (WP-017; D-090)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.modules.organization.domain.domains import (
    DomainProblem,
    blocked_address,
    check_certificate,
    normalise_domain,
    proof,
    proof_matches,
)
from app.modules.organization.infra import domain_check


@pytest.mark.parametrize(
    ("given", "expected"),
    [("Help.Example.COM.", "help.example.com"), ("a-b.c.example", "a-b.c.example")],
)
def test_hosts_are_normalised(given: str, expected: str) -> None:
    assert normalise_domain(given, "support.example.net") == expected


@pytest.mark.parametrize(
    ("given", "code"),
    [
        ("192.168.1.10", "domain_invalid"),
        ("::1", "domain_invalid"),
        ("example", "domain_invalid"),
        ("help.example.com:8443", "domain_invalid"),
        ("help.example.com/x", "domain_invalid"),
        ("-bad.example.com", "domain_invalid"),
        ("acme.support.example.net", "domain_reserved"),
        ("support.example.net", "domain_reserved"),
    ],
)
def test_hosts_that_cannot_be_claimed(given: str, code: str) -> None:
    with pytest.raises(DomainProblem) as raised:
        normalise_domain(given, "support.example.net")
    assert raised.value.code == code


def test_the_proof_needs_the_installation_secret() -> None:
    answer = proof(b"ours", "tok")
    assert proof_matches(b"ours", "tok", answer + "\n")
    assert not proof_matches(b"theirs", "tok", answer)
    assert not proof_matches(b"ours", "other", answer)


@pytest.mark.parametrize(
    ("address", "blocked"),
    [
        ("127.0.0.1", True),
        ("169.254.169.254", True),  # cloud metadata
        ("::1", True),
        ("0.0.0.0", True),  # noqa: S104 - an address under test, nothing listens
        ("10.1.2.3", False),  # on-prem private networks are allowed
        ("203.0.113.7", False),
    ],
)
def test_addresses_the_check_never_contacts(address: str, blocked: bool) -> None:
    assert blocked_address(address) is blocked


def _cert(host: str, *, start: int = -1, end: int = 30) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + timedelta(days=start))
        .not_valid_after(now + timedelta(days=end))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode(), key_pem.decode()


def test_a_wildcard_covers_one_label_only() -> None:
    cert, key = _cert("*.example.com")
    now = datetime.now(UTC)
    assert check_certificate(cert, key, "help.example.com", now).not_after > now
    for host in ("a.b.example.com", "example.com"):
        with pytest.raises(DomainProblem) as raised:
            check_certificate(cert, key, host, now)
        assert raised.value.code == "certificate_wrong_host"


def test_an_expired_or_future_certificate_is_refused() -> None:
    now = datetime.now(UTC)
    for start, end in ((-30, -1), (2, 30)):
        cert, key = _cert("help.example.com", start=start, end=end)
        with pytest.raises(DomainProblem) as raised:
            check_certificate(cert, key, "help.example.com", now)
        assert raised.value.code == "certificate_not_valid_now"


async def test_the_fetcher_refuses_loopback_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def loopback(host: str) -> list[str]:
        del host
        return ["127.0.0.1"]

    monkeypatch.setattr(domain_check, "_addresses", loopback)
    with pytest.raises(domain_check.DomainCheckError) as raised:
        await domain_check.fetch_answer("help.example.com", "tok")
    assert raised.value.code == "domain_address_not_allowed"

    async def public(host: str) -> list[str]:
        del host
        return ["203.0.113.7"]

    monkeypatch.setattr(domain_check, "_addresses", public)
    redirect = httpx.MockTransport(
        lambda _request: httpx.Response(302, headers={"Location": "http://169.254.169.254/"})
    )
    with pytest.raises(domain_check.DomainCheckError) as raised:
        await domain_check.fetch_answer("help.example.com", "tok", transport=redirect)
    assert raised.value.code == "domain_check_failed"
    big = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 1000))
    with pytest.raises(domain_check.DomainCheckError) as raised:
        await domain_check.fetch_answer("help.example.com", "tok", transport=big)
    assert raised.value.code == "domain_check_failed"
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"proof")

    ok = httpx.MockTransport(answer)
    assert await domain_check.fetch_answer("help.example.com", "tok", transport=ok) == "proof"
    assert seen == ["http://help.example.com/api/v1/public/domain-check/tok"]
