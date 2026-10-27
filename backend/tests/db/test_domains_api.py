"""Custom domains over HTTP (WP-017; REQ-PRT-016 AC3, REQ-SEC-004 AC1-AC2; D-090).

The domain check's HTTP fetch is replaced by a fake that answers like a host pointing here (or
elsewhere); the fetcher's own limits are tested in app/modules/organization/tests.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pydantic import SecretStr

from app.modules.organization import tenant_for_host
from app.modules.organization.api import domains as domain_routes
from app.modules.organization.domain.domains import proof
from app.modules.organization.infra.domain_check import DomainCheckError
from app.shared.files.service.core import FileServices
from tests.db.test_files_api import audit_actions, files, storage
from tests.db.test_incidents_api import World, problem, world

__all__ = ["files", "storage", "world"]  # fixtures, re-used

pytestmark = [pytest.mark.db]

BASE = "/organization/domains"


@pytest.fixture(autouse=True)
def installation_secret(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The proof key is the installation's session secret (every deployment has one)."""
    settings_ = world.app.state.settings.model_copy(update={"session_secret": SecretStr("s" * 40)})
    monkeypatch.setattr(world.app.state, "settings", settings_)


def secret(world: World) -> bytes:
    return bytes(world.app.state.settings.session_secret.get_secret_value(), "utf-8")


@pytest.fixture
def pointing_here(world: World, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every host answers like this installation, except those listed (they point elsewhere)."""
    elsewhere: list[str] = []

    async def fetch(host: str, token: str) -> str:
        if host in elsewhere:
            return "not ours"
        if host.startswith("nowhere."):
            raise DomainCheckError(code="domain_not_resolving")
        return proof(secret(world), token)

    monkeypatch.setattr(domain_routes, "fetch_answer", fetch)
    return elsewhere


async def add(world: World, org: Any, host: str) -> httpx.Response:  # noqa: ANN401 - Org
    return await world.call(
        "POST",
        BASE,
        org,
        org.admin,
        json={"host": host},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


async def public_slug(world: World, host: str) -> str | None:
    """The tenant `host` resolves to, asked of the resolver (the public brand never says)."""
    found = await tenant_for_host(world.app.state.db, host, None)
    return found.slug if found is not None else None


def certificate(host: str, *, days: int = 30) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return pem, key_pem


async def test_a_checked_domain_resolves_to_its_tenant_only(
    world: World, pointing_here: list[str]
) -> None:
    del pointing_here
    a, b = world.a, world.b
    created = await add(world, a, "Help.Acme-Example.test")
    assert created.status_code == 201, created.text
    domain = created.json()
    assert (domain["host"], domain["status"], domain["tls_status"]) == (
        "help.acme-example.test",
        "pending",
        "waiting",
    )
    assert domain["check_url"].startswith(
        "http://help.acme-example.test/api/v1/public/domain-check/"
    )
    assert await public_slug(world, "help.acme-example.test") is None  # not before the check
    checked = await world.call("POST", f"{BASE}/{domain['id']}/verify", a, a.admin)
    assert checked.status_code == 200, checked.text
    assert (checked.json()["status"], checked.json()["tls_status"]) == ("verified", "not_managed")
    slug = (await world.sql("SELECT slug FROM tenants WHERE id = $1", a.tenant))[0]["slug"]
    assert await public_slug(world, "help.acme-example.test") == slug  # AC3: that tenant only
    # Another tenant cannot take the same host, nor see or check A's.
    assert problem(await add(world, b, "help.acme-example.test")) == (409, "domain_taken")
    assert (await world.call("GET", BASE, b, b.admin)).json()["items"] == []
    assert (
        await world.call("POST", f"{BASE}/{domain['id']}/verify", b, b.admin)
    ).status_code == 404
    assert "domain.added" in await audit_actions(world, a)
    assert "domain.verified" in await audit_actions(world, a)


async def test_a_domain_pointing_elsewhere_or_nowhere_fails_with_the_reason(
    world: World, pointing_here: list[str]
) -> None:
    a = world.a
    pointing_here.append("elsewhere.example.test")
    for host, code in (
        ("elsewhere.example.test", "domain_wrong_answer"),
        ("nowhere.example.test", "domain_not_resolving"),
    ):
        created = (await add(world, a, host)).json()
        checked = await world.call("POST", f"{BASE}/{created['id']}/verify", a, a.admin)
        assert (checked.json()["status"], checked.json()["failure_code"]) == ("failed", code)
        assert await public_slug(world, host) is None


async def test_hosts_that_are_not_a_tenants_to_claim_are_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    settings_ = world.app.state.settings.model_copy(update={"tenant_base_domain": "brand.test"})
    monkeypatch.setattr(world.app.state, "settings", settings_)
    for host, code in (
        ("10.0.0.1", "domain_invalid"),
        ("https://help.acme.test", "domain_invalid"),
        ("localhost", "domain_invalid"),
        ("other.brand.test", "domain_reserved"),
    ):
        refused = await add(world, a, host)
        assert refused.status_code == 422, (host, refused.text)
        assert refused.json()["errors"][0]["code"] == code, host


async def test_an_uploaded_certificate_is_checked_and_its_key_encrypted(
    world: World, files: FileServices, pointing_here: list[str]
) -> None:
    del files, pointing_here
    a = world.a
    domain = (await add(world, a, "support.acme-cert.test")).json()
    cert, key = certificate("support.acme-cert.test")
    _, other_key = certificate("support.acme-cert.test")
    wrong_host, wrong_host_key = certificate("www.elsewhere.test")
    put = f"{BASE}/{domain['id']}/certificate"
    headers = {"If-Match": f'"{domain["version"]}"'}
    for body, code in (
        ({"certificate_pem": cert, "private_key_pem": other_key}, "certificate_key_mismatch"),
        (
            {"certificate_pem": wrong_host, "private_key_pem": wrong_host_key},
            "certificate_wrong_host",
        ),
        (
            {
                "certificate_pem": "-----BEGIN CERTIFICATE-----\n" + "A" * 120,
                "private_key_pem": key,
            },
            "certificate_unreadable",
        ),
    ):
        refused = await world.call("PUT", put, a, a.admin, json=body, headers=headers)
        assert refused.status_code == 422, refused.text
        assert refused.json()["errors"][0]["code"] == code
    saved = await world.call(
        "PUT",
        put,
        a,
        a.admin,
        json={"certificate_pem": cert, "private_key_pem": key},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["tls_mode"], saved.json()["tls_status"]) == ("uploaded", "issued")
    stored = await world.sql(
        "SELECT private_key, private_key_key_id FROM tenant_domains WHERE id = $1",
        uuid.UUID(domain["id"]),
    )
    assert stored[0]["private_key_key_id"] is not None
    assert b"PRIVATE KEY" not in bytes(stored[0]["private_key"])  # encrypted at rest
    assert "domain.certificate_uploaded" in await audit_actions(world, a)


async def test_removing_a_domain_stops_it_resolving(world: World, pointing_here: list[str]) -> None:
    del pointing_here
    a = world.a
    domain = (await add(world, a, "old.acme-gone.test")).json()
    checked = (await world.call("POST", f"{BASE}/{domain['id']}/verify", a, a.admin)).json()
    assert await public_slug(world, "old.acme-gone.test") is not None
    removed = await world.call(
        "DELETE",
        f"{BASE}/{domain['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{checked["version"]}"'},
    )
    assert removed.status_code == 204, removed.text
    assert await public_slug(world, "old.acme-gone.test") is None
    assert "domain.removed" in await audit_actions(world, a)


async def test_only_brand_managers_see_and_change_domains(world: World) -> None:
    a = world.a
    assert (await world.call("GET", BASE, a, a.tech_a)).status_code == 403
    denied = await world.call(
        "POST", BASE, a, a.tech_a, json={"host": "x.acme.test"}, headers={"Idempotency-Key": "k"}
    )
    assert denied.status_code == 403


async def test_the_proof_is_this_installations_hmac(world: World) -> None:
    answer = await world.client.get("/api/v1/public/domain-check/abc123")
    assert answer.status_code == 200
    assert answer.text == proof(secret(world), "abc123")
    assert answer.headers["cache-control"] == "no-store"
