"""Integration: the identity service account against a REAL Keycloak (WP-039, ADR-036).

Uses the dev stack's Keycloak after `make keycloak-identity` (CI: stack-smoke), or another one
given by SUPPORTX_TEST_KEYCLOAK_URL and SUPPORTX_TEST_KEYCLOAK_IDENTITY_SECRET. Skipped when the
service account cannot sign in. Creates only its own provider (`sx-it-…`) and removes it.
"""

import os
import secrets
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminRefused,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)
from tests.integration.test_ready_dev_stack import read_stack_env
from tooling import seed_dev

pytestmark = pytest.mark.integration


def _target() -> tuple[str, str] | None:
    url = os.environ.get("SUPPORTX_TEST_KEYCLOAK_URL")
    secret = os.environ.get("SUPPORTX_TEST_KEYCLOAK_IDENTITY_SECRET")
    if url and secret:
        return url, secret
    env = read_stack_env() or {}
    if env.get("KEYCLOAK_IDENTITY_CLIENT_SECRET"):
        port = env.get("KEYCLOAK_PORT", "28080")
        return f"http://localhost:{port}", env["KEYCLOAK_IDENTITY_CLIENT_SECRET"]
    return None


@pytest_asyncio.fixture
async def admin() -> AsyncIterator[KeycloakAdmin]:
    found = _target()
    if found is None:
        pytest.skip("no Keycloak with the identity service account (make keycloak-identity)")
    url, secret = found
    client = KeycloakAdmin(url, "supportx", client_id="supportx-identity", client_secret=secret)
    try:
        await client.login_events(["LOGIN"], 0)
    except IdentityAdminUnavailable:
        await client.close()
        pytest.skip("the identity service account cannot sign in (make keycloak-identity)")
    yield client
    await client.close()


async def test_finds_a_tenants_organization_only_with_its_tenant_id(admin: KeycloakAdmin) -> None:
    found = await admin.organization("demo", str(seed_dev.DEMO_TENANT_ID))
    assert found is not None
    assert found.alias == "demo"
    assert "demo.test" in found.domains
    # The alias alone is not enough: another tenant's ID never finds Demo Company's organization.
    assert await admin.organization("demo", str(seed_dev.OTHER_TENANT_ID)) is None


async def test_provider_life_cycle_linked_to_the_organization(admin: KeycloakAdmin) -> None:
    alias = f"sx-it-{secrets.token_hex(4)}"
    organization = await admin.organization("demo", str(seed_dev.DEMO_TENANT_ID))
    assert organization is not None
    await admin.create_provider(
        {
            "alias": alias,
            "providerId": "oidc",
            "enabled": False,
            "hideOnLogin": True,
            "config": {
                "clientId": "it",
                "clientSecret": "it-secret",
                "authorizationUrl": "https://idp.example.test/auth",
                "tokenUrl": "https://idp.example.test/token",
                "clientAuthMethod": "client_secret_post",
            },
        }
    )
    try:
        await admin.link_provider(organization.id, alias)
        assert alias in await admin.linked_providers(organization.id)
        await admin.replace_mappers(
            alias,
            [
                {
                    "name": "department",
                    "identityProviderMapper": "oidc-user-attribute-idp-mapper",
                    "config": {
                        "claim": "department",
                        "user.attribute": "department",
                        "syncMode": "INHERIT",
                    },
                }
            ],
        )
        stored = await admin.provider(alias)
        assert stored is not None
        assert stored["config"]["clientSecret"] == "**********"  # never readable back
        with pytest.raises(IdentityAdminRefused):
            await admin.create_provider({"alias": alias, "providerId": "oidc", "config": {}})
    finally:
        await admin.delete_provider(alias)
    assert await admin.provider(alias) is None


async def test_reads_saml_metadata_with_keycloaks_own_parser(admin: KeycloakAdmin) -> None:
    found = _target()
    assert found is not None
    async with httpx.AsyncClient() as client:
        descriptor = await client.get(f"{found[0]}/realms/supportx/protocol/saml/descriptor")
    parsed = await admin.parse_saml_metadata(descriptor.text)
    assert parsed["singleSignOnServiceUrl"].endswith("/realms/supportx/protocol/saml")
    assert parsed["signingCertificate"]


async def test_logout_of_an_unknown_person_and_reading_events_are_harmless(
    admin: KeycloakAdmin,
) -> None:
    await admin.logout_user("00000000-0000-0000-0000-000000000000")
    assert isinstance(await admin.login_events(["IDENTITY_PROVIDER_LOGIN_ERROR"], 0), list)
