"""Integration: the identity service accounts against a REAL Keycloak (WP-039, ADR-036).

Runs on this process's private Keycloak with the dev realm (tests/integration/conftest.py, lane
A's `private_keycloak`), never the shared dev Keycloak: the deploy step
(`tooling.keycloak_identity`) sets it up once with fresh secrets, exactly as an install would.
Creates only its own provider (`sx-it-…`) and users (`it-…@acme.test`) and removes them.
"""

import secrets
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from app.modules.identity_access.domain.password_policy import PasswordPolicy, to_keycloak
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminRefused,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)
from tests.integration.keycloak_container import PrivateKeycloak
from tooling import keycloak_identity, seed_dev

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def service_accounts(private_keycloak: PrivateKeycloak) -> tuple[str, str]:
    """The deploy step on the private Keycloak: (identity secret, realm secret)."""
    identity, realm = secrets.token_hex(16), secrets.token_hex(16)
    target = keycloak_identity.Target(
        private_keycloak.base_url,
        user=private_keycloak.admin_user,
        password=private_keycloak.admin_password,
        secret=identity,
        realm_secret=realm,
    )
    import asyncio  # noqa: PLC0415 - a session fixture outside the event loop

    result = asyncio.run(keycloak_identity.run(target, wait_seconds=60))
    assert result.outcome in {keycloak_identity.Outcome.UPDATED, keycloak_identity.Outcome.READY}
    return identity, realm


@pytest_asyncio.fixture
async def admin(
    private_keycloak: PrivateKeycloak, service_accounts: tuple[str, str]
) -> AsyncIterator[KeycloakAdmin]:
    client = KeycloakAdmin(
        private_keycloak.base_url,
        "supportx",
        client_id="supportx-identity",
        client_secret=service_accounts[0],
    )
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


async def test_reads_saml_metadata_with_keycloaks_own_parser(
    admin: KeycloakAdmin, private_keycloak: PrivateKeycloak
) -> None:
    base = private_keycloak.base_url
    async with httpx.AsyncClient() as client:
        descriptor = await client.get(f"{base}/realms/supportx/protocol/saml/descriptor")
    parsed = await admin.parse_saml_metadata(descriptor.text)
    assert parsed["singleSignOnServiceUrl"].endswith("/realms/supportx/protocol/saml")
    assert parsed["signingCertificate"]


async def test_logout_of_an_unknown_person_and_reading_events_are_harmless(
    admin: KeycloakAdmin,
) -> None:
    await admin.logout_user("00000000-0000-0000-0000-000000000000")
    assert isinstance(await admin.login_events(["IDENTITY_PROVIDER_LOGIN_ERROR"], 0), list)


async def test_credentials_are_listed_and_removed_by_type(
    admin: KeycloakAdmin, private_keycloak: PrivateKeycloak
) -> None:
    """WP-039 session 3: what an MFA reset reads and removes (types and IDs, never secrets)."""
    email = f"it-{secrets.token_hex(4)}@acme.test"
    user = await admin.create_user(email=email, first_name="It", last_name="Cred", locale="en")
    try:
        assert await admin.credentials(user) == []  # made without a password
        await _set_password(private_keycloak, user, "It-Cred-Pass-2026x")
        found = await admin.credentials(user)
        assert [c.type for c in found] == ["password"]
        await admin.delete_credential(user, found[0].id)
        assert await admin.credentials(user) == []
        await admin.require_actions(user, ["CONFIGURE_TOTP"])  # the enrolment a reset asks for
    finally:
        await admin.delete_user(user)


async def _set_password(keycloak: PrivateKeycloak, user: str, password: str) -> None:
    """As the person would on Keycloak's page (the master admin here, outside SupportX)."""
    async with httpx.AsyncClient(base_url=keycloak.base_url) as client:
        token = await client.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": keycloak.admin_user,
                "password": keycloak.admin_password,
            },
        )
        done = await client.put(
            f"/admin/realms/supportx/users/{user}/reset-password",
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            json={"type": "password", "value": password, "temporary": False},
        )
        assert done.status_code == httpx.codes.NO_CONTENT, done.text


async def test_only_the_realm_account_may_set_the_password_policy(
    private_keycloak: PrivateKeycloak, service_accounts: tuple[str, str], admin: KeycloakAdmin
) -> None:
    """WP-039 session 2: manage-realm is supportx-realm's alone (the API's account gets 403)."""
    realm = KeycloakAdmin(
        private_keycloak.base_url,
        "supportx",
        client_id="supportx-realm",
        client_secret=service_accounts[1],
    )
    try:
        await realm.set_password_policy(to_keycloak(PasswordPolicy(min_length=14)))
    finally:
        await realm.close()
    with pytest.raises(IdentityAdminUnavailable):
        await admin.set_password_policy("length(8)")
