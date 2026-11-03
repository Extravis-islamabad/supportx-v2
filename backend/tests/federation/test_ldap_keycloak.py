"""AD/LDAP federation end to end: a throwaway Keycloak and a test OpenLDAP (WP-040, D-130).

Builds the test-only slapd image (tests/fixtures/slapd), starts it and a fresh Keycloak 26.8.1
(the stack's version, the dev realm imported) on a private Docker network, and removes all of
it afterwards. Never the shared dev stack's Keycloak. Proves the component and mappers SupportX
writes are ones Keycloak accepts and syncs, that people come back with the attributes SupportX
maps, and that only `supportx-federation` may do it.

Runs with SUPPORTX_LDAP_FEDERATION_TESTS=1 (CI job "ldap federation"); needs Docker.
"""

import asyncio
import os
import secrets
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.identity_access import (
    federated_users,
    put_ldap_federation,
    remove_ldap_federation,
    sync_ldap_federation,
)
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminRefused,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)
from app.modules.integrations.domain import ldap
from app.modules.integrations.domain.directory import DirectoryPerson
from tooling.keycloak_identity import Target, run

if os.environ.get("SUPPORTX_LDAP_FEDERATION_TESTS") != "1" or shutil.which("docker") is None:
    pytest.skip("set SUPPORTX_LDAP_FEDERATION_TESTS=1 (needs Docker)", allow_module_level=True)

pytestmark = pytest.mark.ldap_federation

ROOT = Path(__file__).resolve().parents[3]
SLAPD = ROOT / "backend" / "tests" / "fixtures" / "slapd"
KEYCLOAK_FILES = ROOT / "deploy" / "helm" / "supportx" / "files" / "keycloak"
DENYLISTS = KEYCLOAK_FILES / "password-blacklists"
KEYCLOAK_IMAGE = "quay.io/keycloak/keycloak:26.8.1"  # the stack's (deploy/compose)
SLAPD_IMAGE = "supportx-test-slapd:local"


def _docker(*args: str) -> str:
    done = subprocess.run(["docker", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607 - the test's own containers
    return done.stdout.strip()


@dataclass(frozen=True)
class Stack:
    """The throwaway Keycloak (admin URL) and the secrets this test made."""

    base_url: str
    admin_password: str
    identity_secret: str
    federation_secret: str
    ldap_password: str


@pytest.fixture(scope="module")
def stack() -> Iterator[Stack]:
    tag = uuid.uuid4().hex[:8]
    network, slapd, keycloak = f"sx-ldap-{tag}", f"sx-slapd-{tag}", f"sx-kc-{tag}"
    made = Stack(
        base_url="",
        admin_password=secrets.token_urlsafe(18),
        identity_secret=secrets.token_urlsafe(24),
        federation_secret=secrets.token_urlsafe(24),
        ldap_password=secrets.token_urlsafe(18),
    )
    _docker("build", "-q", "-t", SLAPD_IMAGE, str(SLAPD))
    _docker("network", "create", network)
    try:
        _docker(
            "run", "-d", "--name", slapd, "--network", network, "--network-alias", "slapd",
            "-e", f"LDAP_ADMIN_PASSWORD={made.ldap_password}", SLAPD_IMAGE,
        )  # fmt: skip
        _docker(
            "run", "-d", "--name", keycloak, "--network", network, "-p", "127.0.0.1::8080",
            # The same three folders as deploy/compose: realm, theme, password denylist.
            "-v", f"{KEYCLOAK_FILES / 'dev'}:/opt/keycloak/data/import:ro",
            "-v", f"{KEYCLOAK_FILES / 'themes' / 'supportx'}:/opt/keycloak/themes/supportx:ro",
            "-v", f"{DENYLISTS}:/opt/keycloak/data/password-blacklists:ro",
            "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=admin",
            "-e", f"KC_BOOTSTRAP_ADMIN_PASSWORD={made.admin_password}",
            "-e", "SUPPORTX_KC_CONSOLE_ORIGIN=http://localhost:5173",
            "-e", "SUPPORTX_KC_PORTAL_ORIGIN=http://localhost:5174",
            "-e", f"SUPPORTX_KC_CONSOLE_SECRET={secrets.token_urlsafe(24)}",
            "-e", f"SUPPORTX_KC_PORTAL_SECRET={secrets.token_urlsafe(24)}",
            KEYCLOAK_IMAGE, "start-dev", "--import-realm",
        )  # fmt: skip
        port = _docker("port", keycloak, "8080/tcp").rsplit(":", 1)[-1]
        yield Stack(**{**made.__dict__, "base_url": f"http://127.0.0.1:{port}"})
    finally:
        logs = os.environ.get("SUPPORTX_LDAP_FEDERATION_LOGS")  # CI: kept for the failure step
        for name in (keycloak, slapd):
            if logs:
                found = subprocess.run(["docker", "logs", name], check=False, capture_output=True)  # noqa: S603, S607
                Path(logs, f"ldap-federation-{name.split('-')[1]}.log").write_bytes(
                    found.stdout + found.stderr
                )
            subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)  # noqa: S603, S607
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)  # noqa: S603, S607


@pytest.fixture
async def settings(stack: Stack) -> Settings:
    """The realm's two SupportX accounts made by the identity step, as an install with LDAP on."""
    await run(
        Target(
            stack.base_url,
            user="admin",
            password=stack.admin_password,
            secret=stack.identity_secret,
            federation_secret=stack.federation_secret,
        ),
        wait_seconds=240,
    )
    loaded = Settings.load(
        env_file=None, profile="test", oidc_issuer=f"{stack.base_url}/realms/supportx"
    )
    return loaded.model_copy(
        update={
            "keycloak_federation_client_secret": SecretStr(stack.federation_secret),
            "keycloak_identity_client_secret": SecretStr(stack.identity_secret),
        }
    )


def _directory() -> ldap.LdapSettings:
    # The test server has no TLS: plain, by the explicit choice the screen records.
    return ldap.LdapSettings(
        host="slapd",
        port=389,
        security=ldap.Security.PLAIN,
        allow_plain=True,
        vendor=ldap.Vendor.OTHER,
        bind_dn="cn=admin,dc=example,dc=org",
        users_dn="ou=People,dc=example,dc=org",
        department_from="departmentNumber",
        site_from="physicalDeliveryOfficeName",
    )


async def _people(settings: Settings, component_id: str) -> dict[str, DirectoryPerson]:
    found: dict[str, DirectoryPerson] = {}
    for user in await federated_users(settings, component_id):
        change = ldap.from_keycloak(user)
        assert isinstance(change, DirectoryPerson), change
        found[str(change.values["email"])] = change
    return found


async def test_keycloak_accepts_syncs_and_removes_the_directory(
    settings: Settings, stack: Stack
) -> None:
    directory = _directory()

    def component(realm: str) -> dict[str, object]:
        return ldap.component(
            directory, name="supportx-test", realm_id=realm, bind_password=stack.ldap_password
        )

    def mappers(component_id: str) -> list[dict[str, object]]:
        return ldap.mappers(directory, component_id=component_id)

    component_id = await put_ldap_federation(settings, component=component, mappers=mappers)
    again = await put_ldap_federation(settings, component=component, mappers=mappers)
    assert again == component_id  # found by its name and replaced, never a second one

    counts = await sync_ldap_federation(settings, component_id, full=True)
    assert counts.get("added") == 2, counts
    people = await _people(settings, component_id)
    assert set(people) == {"sam.lee@example.org", "noor.khan@example.org"}
    sam = people["sam.lee@example.org"]
    assert sam.values["first_name"] == "Sam"
    assert dict(sam.refs) == {"department": "IT", "site": "HQ"}  # SupportX's mappers at work
    assert sam.external_id != ""  # the directory's own ID (entryUUID)
    assert people["noor.khan@example.org"].refs["site"] is None

    await remove_ldap_federation(settings, component_id)
    for _ in range(20):  # Keycloak drops the people it imported with the component
        if not await federated_users(settings, component_id):
            break
        await asyncio.sleep(0.5)
    assert await federated_users(settings, component_id) == []


async def test_the_identity_account_may_not_federate(settings: Settings, stack: Stack) -> None:
    """Least privilege (D-130): only supportx-federation holds manage-realm."""
    federation = KeycloakAdmin.federation_from_settings(settings)
    assert federation is not None  # LDAP is on in these settings
    try:
        realm_id = await federation.realm_id()
    finally:
        await federation.close()
    admin = KeycloakAdmin(
        stack.base_url,
        "supportx",
        client_id="supportx-identity",
        client_secret=stack.identity_secret,
    )
    try:
        component = ldap.component(
            _directory(),
            name="supportx-forbidden",
            realm_id=realm_id,
            bind_password=stack.ldap_password,
        )
        with pytest.raises((IdentityAdminRefused, IdentityAdminUnavailable)):  # 403
            await admin.put_federation_component(component)
    finally:
        await admin.close()


async def test_the_federation_account_has_no_user_rights(settings: Settings) -> None:
    """D-130: supportx-federation writes the component only; people are the identity account's."""
    federation = KeycloakAdmin.federation_from_settings(settings)
    assert federation is not None
    try:
        with pytest.raises(Exception, match="identity_admin"):
            await federation.federated_users("any")
    finally:
        await federation.close()
