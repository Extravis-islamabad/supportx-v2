"""Integration, in a REAL Keycloak: clearing a provider's group attributes (WP-057 S5c).

The identity service account (manage-users, never manage-realm) clears a provider's
`sx_groups*` attributes from everyone linked to it, and leaves the person's other attributes
alone. The realm keeps undeclared attributes admin-only (`unmanagedAttributePolicy`
ADMIN_EDIT, the deploy step's, pending the product owner); this test sets it on the private
Keycloak and restores it. Its own provider (`sx-ga-…`) and person, removed afterwards.
"""

import secrets
import uuid
from collections.abc import Iterator

import httpx
import pytest

from app.modules.identity_access.domain import sso
from app.modules.identity_access.infra.keycloak_admin import KeycloakAdmin
from tests.integration.keycloak_container import PrivateKeycloak
from tests.integration.test_keycloak_admin import admin, service_accounts
from tests.integration.test_sign_in_identity_provider_claim import (
    PASSWORD,
    _admin,
    _browser_tokens,
    _user,
)

pytestmark = pytest.mark.integration

__all__ = ["admin", "service_accounts"]  # the fixtures, used by name


@pytest.fixture
def linked(private_keycloak: PrivateKeycloak) -> Iterator[tuple[str, str]]:
    """A disabled OIDC provider and one person linked to it: (alias, user id)."""
    alias = f"sx-ga-{secrets.token_hex(3)}"
    email = f"ga-{uuid.uuid4().hex[:8]}@acme.test"
    with _admin(private_keycloak) as root:
        made = root.post(
            "/identity-provider/instances",
            json={
                "alias": alias,
                "providerId": "oidc",
                "enabled": False,
                "config": {
                    "authorizationUrl": "https://idp.example/auth",
                    "tokenUrl": "https://idp.example/token",
                    "clientId": "ga",
                    "clientSecret": uuid.uuid4().hex,
                },
            },
        )
        assert made.status_code == 201, made.text
        user_id = _user(root, email)
        link = root.post(
            f"/users/{user_id}/federated-identity/{alias}",
            json={"identityProvider": alias, "userId": uuid.uuid4().hex, "userName": email},
        )
        assert link.status_code == 204, link.text
    try:
        yield alias, user_id
    finally:
        with _admin(private_keycloak) as root:
            root.delete(f"/users/{user_id}")
            root.delete(f"/identity-provider/instances/{alias}")


def _policy(keycloak: PrivateKeycloak, value: str | None) -> str | None:
    with _admin(keycloak) as root:
        profile = root.get("/users/profile").json()
        before = profile.get("unmanagedAttributePolicy")
        if value is None:
            profile.pop("unmanagedAttributePolicy", None)
        else:
            profile["unmanagedAttributePolicy"] = value
        assert root.put("/users/profile", json=profile).status_code == 200
    return before if isinstance(before, str) else None


async def test_clearing_removes_only_the_providers_group_attributes(
    private_keycloak: PrivateKeycloak, admin: KeycloakAdmin, linked: tuple[str, str]
) -> None:
    alias, user_id = linked
    names = sso.group_attributes(alias)
    before = _policy(private_keycloak, "ADMIN_EDIT")
    try:
        with _admin(private_keycloak) as root:
            person = root.get(f"/users/{user_id}").json()
            person["attributes"] = {
                **(person.get("attributes") or {}),
                names.groups: ["Change Managers", "Network"],
                names.seen: ["1"],
                sso.DEPARTMENT_ATTRIBUTE: ["Finance"],
            }
            assert root.put(f"/users/{user_id}", json=person).status_code == 204
            kept = root.get(f"/users/{user_id}").json()["attributes"]
            assert kept[names.groups] == ["Change Managers", "Network"]
        assert await admin.clear_group_attributes(alias) == 1
        with _admin(private_keycloak) as root:
            after = root.get(f"/users/{user_id}").json().get("attributes") or {}
        assert not set(names.all()) & set(after), after
        assert after.get(sso.DEPARTMENT_ATTRIBUTE) == ["Finance"], "only the group attributes go"
        assert await admin.clear_group_attributes(alias) == 0  # nothing left: nothing written
    finally:
        _policy(private_keycloak, before)


def _self_service_write(keycloak: PrivateKeycloak, email: str, attribute: str) -> None:
    """The person, signed in, writes `attribute` on themselves through the account API."""
    token = _browser_tokens(keycloak, username=email, password=PASSWORD)["access_token"]
    # The account REST API answers JSON only when asked; otherwise it is the account console page.
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    account = f"{keycloak.issuer}/account"
    me = httpx.get(account, headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    body["attributes"] = {**(body.get("attributes") or {}), attribute: ["Domain Admins"]}
    httpx.post(account, headers=headers, json=body)  # accepted or refused: the result is read back


def test_d187_a_person_can_never_write_their_own_group_attributes(
    private_keycloak: PrivateKeycloak, linked: tuple[str, str]
) -> None:
    """ADMIN_EDIT: the account API never sets `sx_groups_*` (ENABLED would; the control)."""
    alias, user_id = linked
    names = sso.group_attributes(alias)
    with _admin(private_keycloak) as root:
        email = root.get(f"/users/{user_id}").json()["email"]

    def written() -> list[str]:
        with _admin(private_keycloak) as root:
            attributes = root.get(f"/users/{user_id}").json().get("attributes") or {}
        return list(attributes.get(names.groups) or [])

    before = _policy(private_keycloak, "ENABLED")
    try:
        _self_service_write(private_keycloak, email, names.groups)
        assert written() == ["Domain Admins"]  # the control: ENABLED lets a person write it
        with _admin(private_keycloak) as root:
            person = root.get(f"/users/{user_id}").json()
            person["attributes"] = {
                k: v for k, v in (person.get("attributes") or {}).items() if k != names.groups
            }
            assert root.put(f"/users/{user_id}", json=person).status_code == 204
        _policy(private_keycloak, "ADMIN_EDIT")
        _self_service_write(private_keycloak, email, names.groups)
        assert written() == []  # ADMIN_EDIT (D-187): never from the person
    finally:
        _policy(private_keycloak, before)
