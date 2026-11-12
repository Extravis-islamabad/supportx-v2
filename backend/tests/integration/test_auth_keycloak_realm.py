"""Integration: the dev realm's own sign-in rules, in a REAL Keycloak (split from
test_auth_keycloak.py, WP-057 S1): the password policy and brute-force protection."""

import uuid

import httpx
import pytest

from tests.integration.keycloak_browser import KeycloakBrowser
from tests.integration.keycloak_container import PrivateKeycloak

pytestmark = pytest.mark.integration


def _admin(keycloak: PrivateKeycloak) -> httpx.Client:
    base = keycloak.base_url
    token = httpx.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": keycloak.admin_user,
            "password": keycloak.admin_password,
        },
    ).json()["access_token"]
    return httpx.Client(
        base_url=f"{base}/admin/realms/supportx", headers={"Authorization": f"Bearer {token}"}
    )


def test_realm_enforces_password_policy_and_brute_force_protection(
    private_keycloak: PrivateKeycloak,
) -> None:
    with _admin(private_keycloak) as admin:
        realm = admin.get("").json()
        assert realm["bruteForceProtected"] is True
        assert realm["failureFactor"] == 5
        assert "length(12)" in realm["passwordPolicy"]
        assert realm["organizationsEnabled"] is True
        # A throwaway user: a weak password is refused, then 5 wrong passwords lock the account.
        email = f"policy-{uuid.uuid4().hex[:8]}@nowhere.test"
        created = admin.post("/users", json={"username": email, "email": email, "enabled": True})
        user_id = created.headers["location"].rsplit("/", 1)[1]
        try:
            weak = admin.put(
                f"/users/{user_id}/reset-password",
                json={"type": "password", "value": "short", "temporary": False},
            )
            assert weak.status_code == 400
            strong = admin.put(
                f"/users/{user_id}/reset-password",
                json={"type": "password", "value": "Strong-Pass-2026!", "temporary": False},
            )
            assert strong.status_code == 204
            browser = KeycloakBrowser()
            authorize = (
                f"{private_keycloak.issuer}/protocol/openid-connect/auth"
                "?client_id=supportx-console&response_type=code&scope=openid"
                "&redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fapi%2Fv1%2Fauth%2Fcallback"
                "&code_challenge=" + "x" * 43 + "&code_challenge_method=S256"
            )
            try:
                for _ in range(5):
                    browser.login(authorize, email, "Wrong-Pass-2026!")
                locked = admin.get(f"/attack-detection/brute-force/users/{user_id}").json()
                assert locked["disabled"] is True
                # Even the right password is refused while the lock lasts.
                assert browser.login(authorize, email, "Strong-Pass-2026!").status_code == 200
            finally:
                browser.close()
        finally:
            admin.delete(f"/users/{user_id}")
