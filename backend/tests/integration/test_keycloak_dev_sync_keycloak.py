"""`make keycloak-dev-sync` against a real Keycloak (D-151), in a private container.

The realm is made to look like one imported before D-151 (password grant off, short sessions);
the step gives it back the quick sign-in's settings and touches nothing else.
"""

import asyncio
from typing import Any

import httpx
import pytest

from tests.integration.keycloak_container import PrivateKeycloak
from tooling import keycloak_dev_sync as sync

pytestmark = pytest.mark.integration


def _admin(keycloak: PrivateKeycloak) -> httpx.Client:
    token = httpx.post(
        f"{keycloak.base_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": keycloak.admin_user,
            "password": keycloak.admin_password,
        },
        timeout=30,
    ).json()["access_token"]
    return httpx.Client(
        base_url=f"{keycloak.base_url}/admin/realms/supportx",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )


def _client(admin: httpx.Client, client_id: str) -> dict[str, Any]:
    (found,) = admin.get("/clients", params={"clientId": client_id}).json()
    return dict(found)


def test_an_old_dev_realm_gets_the_quick_sign_in_settings_and_keeps_its_users(
    private_keycloak: PrivateKeycloak,
) -> None:
    with _admin(private_keycloak) as admin:
        for client_id in sync.CLIENTS:  # as before D-151
            client = _client(admin, client_id)
            admin.put(
                f"/clients/{client['id']}", json={**client, "directAccessGrantsEnabled": False}
            )
        admin.put("", json={"rememberMe": False, "ssoSessionIdleTimeout": 1800}).raise_for_status()
        users_before = admin.get("/users/count").json()

        changed = asyncio.run(
            sync.run(
                private_keycloak.base_url,
                user=private_keycloak.admin_user,
                password=private_keycloak.admin_password,
                realm="supportx",
                quick_sign_in="true",
                wait_seconds=30,
            )
        )
        assert changed
        assert all(_client(admin, c)["directAccessGrantsEnabled"] for c in sync.CLIENTS)
        realm = admin.get("").json()
        assert realm["rememberMe"] is True
        assert realm["ssoSessionIdleTimeout"] >= sync.WEEK
        assert admin.get("/users/count").json() == users_before  # no user touched
    again = asyncio.run(
        sync.run(
            private_keycloak.base_url,
            user=private_keycloak.admin_user,
            password=private_keycloak.admin_password,
            realm="supportx",
            quick_sign_in="true",
            wait_seconds=30,
        )
    )
    assert again == []
