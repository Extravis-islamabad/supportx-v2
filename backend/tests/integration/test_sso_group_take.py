"""Integration, in a REAL Keycloak: a sign-in's read-and-clear of its groups (WP-057 S5c-1b).

Lane B's condition 6, the Keycloak half: one person linked to two tenants' providers (A and B),
both carrying the SAME group name. The identity service account (manage-users, never
manage-realm) takes provider A's four attributes: it gets A's values only, clears A's only,
and leaves B's and the person's other attributes untouched. The SupportX half (the same
external group ID mapped in two tenants applies only through its own provider) is the DB test
`tests/db/test_sso_group_sign_in.py::test_the_same_group_in_two_tenants_applies_only_through_its_own`.

The realm keeps undeclared attributes admin-only (ADMIN_EDIT, D-187), set here and restored.
"""

import secrets
import uuid
from collections.abc import Iterator

import pytest

from app.modules.identity_access.domain import sso
from app.modules.identity_access.infra.keycloak_admin import KeycloakAdmin
from tests.integration.keycloak_container import PrivateKeycloak
from tests.integration.test_idp_group_attributes import _policy
from tests.integration.test_keycloak_admin import admin, service_accounts
from tests.integration.test_sign_in_identity_provider_claim import _admin, _user

pytestmark = pytest.mark.integration

__all__ = ["admin", "service_accounts"]  # the fixtures, used by name


@pytest.fixture
def two_providers(private_keycloak: PrivateKeycloak) -> Iterator[tuple[str, str, str]]:
    """Two disabled OIDC providers (tenants A and B) and one person linked to both."""
    aliases = (f"sx-ta-{secrets.token_hex(3)}", f"sx-tb-{secrets.token_hex(3)}")
    email = f"tt-{uuid.uuid4().hex[:8]}@acme.test"
    with _admin(private_keycloak) as root:
        for alias in aliases:
            made = root.post(
                "/identity-provider/instances",
                json={
                    "alias": alias,
                    "providerId": "oidc",
                    "enabled": False,
                    "config": {
                        "authorizationUrl": "https://idp.example/auth",
                        "tokenUrl": "https://idp.example/token",
                        "clientId": "tt",
                        "clientSecret": uuid.uuid4().hex,
                    },
                },
            )
            assert made.status_code == 201, made.text
        user_id = _user(root, email)
        for alias in aliases:
            link = root.post(
                f"/users/{user_id}/federated-identity/{alias}",
                json={"identityProvider": alias, "userId": uuid.uuid4().hex, "userName": email},
            )
            assert link.status_code == 204, link.text
    try:
        yield aliases[0], aliases[1], user_id
    finally:
        with _admin(private_keycloak) as root:
            root.delete(f"/users/{user_id}")
            for alias in aliases:
                root.delete(f"/identity-provider/instances/{alias}")


async def test_taking_tenant_as_groups_reads_and_clears_only_its_own(
    private_keycloak: PrivateKeycloak,
    admin: KeycloakAdmin,
    two_providers: tuple[str, str, str],
) -> None:
    alias_a, alias_b, user_id = two_providers
    names_a, names_b = sso.group_attributes(alias_a), sso.group_attributes(alias_b)
    before = _policy(private_keycloak, "ADMIN_EDIT")
    try:
        with _admin(private_keycloak) as root:
            person = root.get(f"/users/{user_id}").json()
            # As both providers' importers would write them at sign-in: the SAME group name.
            person["attributes"] = {
                **(person.get("attributes") or {}),
                names_a.groups: ["sx-change"],
                names_a.seen: ["1"],
                names_b.groups: ["sx-change"],
                names_b.seen: ["1"],
                sso.DEPARTMENT_ATTRIBUTE: ["Finance"],
            }
            assert root.put(f"/users/{user_id}", json=person).status_code == 204

        took = await admin.take_attributes(user_id, names_a.all())

        assert took == {names_a.groups: ["sx-change"], names_a.seen: ["1"]}  # A's only
        with _admin(private_keycloak) as root:
            after = root.get(f"/users/{user_id}").json().get("attributes") or {}
        assert not set(names_a.all()) & set(after), after  # A's are cleared
        assert after.get(names_b.groups) == ["sx-change"]  # B's are untouched
        assert after.get(names_b.seen) == ["1"]
        assert after.get(sso.DEPARTMENT_ATTRIBUTE) == ["Finance"]
        # Taken once: a second read (a concurrent sign-in) finds nothing, so it is unverified.
        assert await admin.take_attributes(user_id, names_a.all()) == {}
    finally:
        _policy(private_keycloak, before)
