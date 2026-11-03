"""The directory-federation calls of KeycloakAdmin (WP-040, D-118) against a fake admin API."""

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.identity_access.infra.keycloak_admin import KeycloakAdmin

BASE = "http://keycloak.test/auth"


class FakeRealm:
    """Components and their mappers, the token grant, and every call made."""

    def __init__(self) -> None:
        self.components: dict[str, dict[str, Any]] = {}  # Any: Keycloak's JSON
        self.calls: list[str] = []
        self.synced: list[str] = []
        self.client_id: str | None = None
        self.users: list[dict[str, Any]] = []  # Any: Keycloak's JSON

    def handler(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - one answer per call
        path = request.url.path.removeprefix("/auth")
        self.calls.append(f"{request.method} {path}")
        if path.endswith("/protocol/openid-connect/token"):
            form = dict(x.split("=") for x in request.content.decode().split("&"))
            self.client_id = form["client_id"]
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        base = "/admin/realms/supportx"
        if path == base:
            return httpx.Response(200, json={"id": "realm-1", "realm": "supportx"})
        if path == f"{base}/components" and request.method == "GET":
            params = request.url.params
            found = [
                c
                for c in self.components.values()
                if ("name" not in params or c["name"] == params["name"])
                and ("parent" not in params or c.get("parentId") == params["parent"])
                and ("type" not in params or c.get("providerType") == params["type"])
            ]
            return httpx.Response(200, json=found)
        if path == f"{base}/components" and request.method == "POST":
            body = json.loads(request.content)
            new = f"cmp-{len(self.components) + 1}"
            self.components[new] = {**body, "id": new}
            return httpx.Response(201, headers={"Location": f"{BASE}{base}/components/{new}"})
        if path.startswith(f"{base}/components/"):
            component = path.rsplit("/", 1)[-1]
            if request.method == "PUT":
                self.components[component] = json.loads(request.content)
                return httpx.Response(204)
            if request.method == "DELETE":
                self.components.pop(component, None)
                return httpx.Response(204)
        if path == f"{base}/users" and request.method == "GET":
            first, size = int(request.url.params["first"]), int(request.url.params["max"])
            return httpx.Response(200, json=self.users[first : first + size])
        if path.startswith(f"{base}/user-storage/") and path.endswith("/sync"):
            self.synced.append(request.url.params["action"])
            return httpx.Response(200, json={"added": 3, "updated": 0, "removed": 0, "failed": 0})
        return httpx.Response(404)


def _admin(realm: FakeRealm) -> KeycloakAdmin:
    return KeycloakAdmin(
        BASE,
        "supportx",
        client_id="supportx-federation",
        client_secret="s",
        transport=httpx.MockTransport(realm.handler),
    )


def _ldap(name: str = "Corp AD") -> dict[str, Any]:  # Any: Keycloak's JSON
    return {
        "name": name,
        "providerId": "ldap",
        "providerType": "org.keycloak.storage.UserStorageProvider",
        "parentId": "realm-1",
        "config": {"connectionUrl": ["ldaps://dc1:636"]},
    }


def test_only_the_consumers_worker_with_ldap_on_gets_a_federation_client() -> None:
    settings = Settings.load(
        env_file=None, profile="test", oidc_issuer="http://kc.test/auth/realms/supportx"
    )
    assert KeycloakAdmin.federation_from_settings(settings) is None  # LDAP off: no secret
    on = settings.model_copy(update={"keycloak_federation_client_secret": SecretStr("s" * 24)})
    admin = KeycloakAdmin.federation_from_settings(on)
    assert admin is not None
    assert admin._client_id == "supportx-federation"  # noqa: SLF001 - the account it acts as


async def test_the_component_is_created_once_then_replaced_with_its_mappers() -> None:
    realm = FakeRealm()
    admin = _admin(realm)
    assert await admin.realm_id() == "realm-1"
    first = await admin.put_federation_component(_ldap())
    assert realm.client_id == "supportx-federation"
    again = await admin.put_federation_component(
        {**_ldap(), "config": {"connectionUrl": ["ldaps://dc2:636"]}}
    )
    assert first == again  # same component, replaced
    assert realm.components[first]["config"]["connectionUrl"] == ["ldaps://dc2:636"]
    mapper = {"name": "email", "providerId": "user-attribute-ldap-mapper", "parentId": first}
    await admin.replace_federation_mappers(first, [mapper, {**mapper, "name": "first name"}])
    await admin.replace_federation_mappers(first, [mapper])
    children = [c["name"] for c in realm.components.values() if c.get("parentId") == first]
    assert children == ["email"]  # exactly what SupportX gave, nothing left over
    assert (await admin.sync_federation(first, full=False))["added"] == 3
    assert realm.synced == ["triggerChangedUsersSync"]
    await admin.delete_federation_component(first)
    assert first not in realm.components
    await admin.close()


@pytest.mark.parametrize("name", ["Corp AD", "Other"])
async def test_a_component_is_found_by_its_exact_name(name: str) -> None:
    realm = FakeRealm()
    admin = _admin(realm)
    made = await admin.put_federation_component(_ldap("Corp AD"))
    found = await admin.federation_component(name)
    assert (found is not None and found["id"] == made) is (name == "Corp AD")
    await admin.close()


async def test_federated_users_are_read_page_by_page_and_only_the_components() -> None:
    realm = FakeRealm()
    realm.users = [
        {"id": "u1", "federationLink": "cmp-1"},
        {"id": "u2", "federationLink": "other"},
        {"id": "u3"},  # a local account
        {"id": "u4", "federationLink": "cmp-1"},
        {"id": "u5", "federationLink": "cmp-1"},
    ]
    admin = _admin(realm)
    found = await admin.federated_users("cmp-1", page=2)
    assert [u["id"] for u in found] == ["u1", "u4", "u5"]
    assert sum(c.endswith("/users") for c in realm.calls) == 3  # 2 + 2 + 1
    await admin.close()
