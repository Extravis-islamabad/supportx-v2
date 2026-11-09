"""The showcase personas' authenticators against a real Keycloak (D-151), in a private container.

The seed's Keycloak step pre-enrols a TOTP authenticator for every persona but the new starter.
Then the password grant the quick sign-in uses needs the persona's code, and gets real tokens.
"""

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest

from app.modules.identity_access.domain import quick_sign_in as quick
from tests.integration.keycloak_container import PrivateKeycloak
from tooling import showcase_seed as seed

pytestmark = pytest.mark.integration

PASSWORD = "Showcase-Dev-2026!q"
KEY = "integration-totp-key-" + "z" * 24


def _target(keycloak: PrivateKeycloak, key: str) -> seed.KeycloakTarget:
    return seed.KeycloakTarget(
        keycloak.base_url,
        user=keycloak.admin_user,
        password=keycloak.admin_password,
        sign_in_password=PASSWORD,
        totp_key=key,
    )


async def _ensure(keycloak: PrivateKeycloak, key: str) -> seed.KeycloakResult:
    async with httpx.AsyncClient(base_url=keycloak.base_url, timeout=30) as client:
        return await seed.ensure_keycloak(client, _target(keycloak, key))


def _grant(keycloak: PrivateKeycloak, email: str, code: str | None) -> httpx.Response:
    form = {
        "grant_type": "password",
        "client_id": "supportx-console",
        "client_secret": keycloak.console_secret,
        "username": email,
        "password": PASSWORD,
        "scope": "openid",
    }
    if code is not None:
        form["totp"] = code
    return httpx.post(f"{keycloak.issuer}/protocol/openid-connect/token", data=form, timeout=30)


def _roles_and_membership(keycloak: PrivateKeycloak, user_id: str) -> tuple[set[str], bool]:
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
    headers = {"Authorization": f"Bearer {token}"}
    realm = f"{keycloak.base_url}/admin/realms/supportx"
    roles = httpx.get(f"{realm}/users/{user_id}/role-mappings/realm", headers=headers, timeout=30)
    orgs = httpx.get(
        f"{realm}/organizations", params={"search": seed.TENANT_NAME}, headers=headers, timeout=30
    )
    org = next(o["id"] for o in orgs.json() if o.get("alias") == seed.SLUG)
    members = httpx.get(f"{realm}/organizations/{org}/members", headers=headers, timeout=30)
    return {r["name"] for r in roles.json()}, any(m.get("id") == user_id for m in members.json())


def _code(key: str, email: str) -> str:
    step = quick.time_step(datetime.now(UTC))
    return quick.totp(quick.totp_value(key.encode(), email), step)


def test_personas_are_pre_enrolled_and_the_password_grant_takes_their_code(
    private_keycloak: PrivateKeycloak,
) -> None:
    first = asyncio.run(_ensure(private_keycloak, KEY))
    enrolled = [p for p in quick.PERSONAS if p.enrolled]
    assert {f"authenticator {p.email}" for p in enrolled} <= set(first.made)
    assert "authenticator newstarter@showcase.test" not in first.made
    # One line per persona, never the secret.
    assert {f"{p.email}: enrolled" for p in enrolled} <= set(first.enrolment)
    assert "newstarter@showcase.test: not enrolled (sets it up the normal way)" in first.enrolment
    assert not [line for line in first.enrolment if KEY in line]
    # The right code first: a wrong one counts toward the realm's brute-force lock.
    granted = _grant(private_keycloak, "admin@showcase.test", _code(KEY, "admin@showcase.test"))
    assert granted.status_code == 200, granted.text
    assert "id_token" in granted.json()
    # The import replaced the user; the seed put its roles and organization back.
    roles, member = _roles_and_membership(private_keycloak, first.subjects["admin@showcase.test"])
    assert {"tenant_admin", "technician"} <= roles
    assert member
    # A second run changes nothing; the new starter has no authenticator (sets one up in QA).
    again = asyncio.run(_ensure(private_keycloak, KEY))
    assert not [m for m in again.made if m.startswith("authenticator")]
    assert {f"{p.email}: already enrolled" for p in enrolled} <= set(again.enrolment)
    assert again.subjects == first.subjects  # same Keycloak users: SupportX links hold
    new_starter = _grant(private_keycloak, "newstarter@showcase.test", None)
    assert new_starter.status_code == 200, new_starter.text


def test_a_user_made_before_the_key_is_enrolled_once_the_key_is_set(
    private_keycloak: PrivateKeycloak,
) -> None:
    """Existing personas (made before D-151, no key then) get their authenticator later."""
    before = asyncio.run(_ensure(private_keycloak, ""))
    assert all("NOT enrolled" in line or "not enrolled" in line for line in before.enrolment)
    after = asyncio.run(_ensure(private_keycloak, KEY + "-late"))
    assert "admin@showcase.test: enrolled" in after.enrolment
    granted = _grant(
        private_keycloak, "admin@showcase.test", _code(KEY + "-late", "admin@showcase.test")
    )
    assert granted.status_code == 200, granted.text


def test_a_new_key_in_the_env_re_enrols(private_keycloak: PrivateKeycloak) -> None:
    asyncio.run(_ensure(private_keycloak, KEY))
    changed = asyncio.run(_ensure(private_keycloak, KEY + "-new"))
    assert "authenticator tech@showcase.test" in changed.made
    time.sleep(1)
    granted = _grant(
        private_keycloak, "tech@showcase.test", _code(KEY + "-new", "tech@showcase.test")
    )
    assert granted.status_code == 200, granted.text
