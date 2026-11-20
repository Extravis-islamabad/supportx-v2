"""Integration, in a REAL Keycloak: a tenant's identity provider can't take over an account.

Every tenant shares one realm (ADR-006), and a tenant admin sets up their own identity provider
(domain/sso.py). A provider asserting the e-mail of an account that already exists in the realm
must never sign in AS that account without the account's own proof: a brokered sign-in may not
land on another person's account through an e-mail match alone.

The identity provider is a second realm of this private Keycloak, made and removed here.
"""

import html
import re
import secrets
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
import pytest

import tests.integration.test_sign_in_identity_provider_claim as claim_tests
from app.modules.identity_access.domain import sso
from tests.integration.keycloak_container import PrivateKeycloak
from tests.integration.test_sign_in_identity_provider_claim import (
    _FIELD,
    _FORM,
    PASSWORD,
    _admin,
    _Browser,
    _browser_tokens,
    _claims,
    _text,
    _user,
)

pytestmark = pytest.mark.integration

_ATTR = re.compile(r'(\w+)="([^"]*)"')
_LINK_BUTTON = re.compile(
    r'name="submitAction"[^>]*value="linkAccount"'
    r'|value="linkAccount"[^>]*name="submitAction"'
)


class _Linker(_Browser):
    """The other side: at Keycloak's "account already exists" page, it asks to link."""

    def code(self, url: str, username: str, password: str, *, back_to: str) -> str:
        response = self.open(url)
        for _ in range(16):
            if response.is_redirect:
                location = urljoin(str(response.url), response.headers["location"])
                if location.startswith(back_to):
                    query = parse_qs(urlsplit(location).query)
                    assert "code" in query, location
                    return query["code"][0]
                response = self.open(location)
                continue
            form = _FORM.search(response.text)
            if response.status_code != 200 or form is None:
                raise _Stopped(_text(response.text))
            data: dict[str, str] = {}
            for raw in _FIELD.findall(response.text):
                attrs = dict(_ATTR.findall(raw))
                if "name" in attrs and attrs.get("type") not in ("submit", "button"):
                    data[attrs["name"]] = html.unescape(attrs.get("value", ""))
            # Only the provider's own person signs in here: never the existing account's password.
            if "password" in data and "username" not in data:
                reason = "asked for the existing account's password"
                raise _Stopped(reason)
            data.update(
                {k: v for k, v in (("username", username), ("password", password)) if k in data}
            )
            if _LINK_BUTTON.search(response.text):
                data["submitAction"] = "linkAccount"
            response = self._request("POST", html.unescape(form.group(1)), data=data)
        reason = "no redirect back to the app"
        raise _Stopped(reason)


class _Stopped(Exception):
    """Keycloak stopped the sign-in (asked for proof the provider's person doesn't have)."""


@pytest.fixture
def existing_and_provider(private_keycloak: PrivateKeycloak) -> Iterator[tuple[str, str, str]]:
    """An account already in the realm, and a provider whose person asserts its e-mail.

    Returns (existing account ID, the provider's alias, the shared e-mail).
    """
    base = private_keycloak.base_url
    idp_realm = f"idp-{uuid.uuid4().hex[:8]}"
    alias = f"sx-other-{secrets.token_hex(3)}"
    secret = secrets.token_hex(16)
    email = f"existing-{uuid.uuid4().hex[:8]}@victim.test"
    with _admin(private_keycloak) as admin:
        # The existing account's own password is one the provider's person doesn't know: Keycloak
        # may ask the account to prove itself (re-authentication), and the attacker can't.
        made = admin.post(
            "/users",
            json={
                "username": email,
                "email": email,
                "emailVerified": True,
                "enabled": True,
                "credentials": [
                    {
                        "type": "password",
                        "value": "Victim-" + secrets.token_urlsafe(12),
                        "temporary": False,
                    }
                ],
            },
        )
        assert made.status_code == 201, made.text
        existing = str(made.headers["location"].rsplit("/", 1)[1])
        made_realm = admin.post(f"{base}/admin/realms", json={"realm": idp_realm, "enabled": True})
        assert made_realm.status_code == 201, made_realm.text
    try:
        with _admin(private_keycloak, idp_realm) as idp:
            made = idp.post(
                "/clients",
                json={
                    "clientId": "supportx-broker",
                    "secret": secret,
                    "publicClient": False,
                    "standardFlowEnabled": True,
                    "redirectUris": [f"{base}/realms/supportx/broker/{alias}/endpoint"],
                },
            )
            assert made.status_code == 201, made.text
            _user(idp, email)  # the provider's own person, with the existing account's e-mail
        issuer = f"{base}/realms/{idp_realm}"
        config = sso.oidc_config(
            httpx.get(f"{issuer}/.well-known/openid-configuration").json(),
            client_id="supportx-broker",
            scopes="openid email profile",
        )
        with _admin(private_keycloak) as admin:
            # Exactly what a tenant's set-up writes (domain/sso.py `representation`).
            added = admin.post(
                "/identity-provider/instances",
                json=sso.representation(
                    alias=alias,
                    protocol="oidc",
                    display_name="Other tenant",
                    config=config,
                    state="on",
                    client_secret=secret,
                ),
            )
            assert added.status_code == 201, added.text
        yield existing, alias, email
    finally:
        with _admin(private_keycloak) as admin:
            admin.delete(f"/identity-provider/instances/{alias}")
            for found in admin.get("/users", params={"email": email, "exact": "true"}).json():
                admin.delete(f"/users/{found['id']}")
        with _admin(private_keycloak, idp_realm) as idp:
            idp.delete("")


def test_a_provider_cannot_sign_in_as_an_existing_account_by_email(
    private_keycloak: PrivateKeycloak,
    existing_and_provider: tuple[str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing, alias, email = existing_and_provider
    monkeypatch.setattr(claim_tests, "_Browser", _Linker)
    try:
        tokens: dict[str, Any] | None = _browser_tokens(
            private_keycloak, username=email, password=PASSWORD, hint=alias
        )
    except _Stopped:
        tokens = None  # Keycloak asked for proof the provider's person doesn't have: safe
    if tokens is not None:
        signed_in_as = _claims(tokens["access_token"])["sub"]
        assert signed_in_as != existing, (
            "a tenant's identity provider signed in as an existing account by e-mail alone"
        )


def test_a_new_person_still_signs_in_through_the_provider(
    private_keycloak: PrivateKeycloak, existing_and_provider: tuple[str, str, str]
) -> None:
    """D-177 keeps single sign-on working for people with no account yet: a new account."""
    existing, alias, email = existing_and_provider
    with _admin(private_keycloak) as admin:
        for found in admin.get("/users", params={"email": email, "exact": "true"}).json():
            assert admin.delete(f"/users/{found['id']}").status_code == 204
    tokens = _browser_tokens(private_keycloak, username=email, password=PASSWORD, hint=alias)
    claims = _claims(tokens["access_token"])
    assert claims["sub"] != existing
    assert claims["sx_idp"] == alias
