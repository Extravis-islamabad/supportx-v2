"""Integration, in a REAL Keycloak: `sx_idp` says single sign-on only after one (WP-057 S1b).

The realm mapper copies the session note `identity_provider` into the token as `sx_idp`, and
the BFF reads the sign-in method from it (REQ-SEC-009: single sign-on required). Lane B's
condition: a password sign-in (browser or direct grant) must never carry it, and a brokered one
must carry the provider's alias. The AD/LDAP case runs with the directory
(tests/federation/test_ldap_keycloak.py).

The identity provider is a second realm of this private Keycloak, made and removed here.
"""

import base64
import hashlib
import html
import json
import re
import secrets
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
import pytest

from app.modules.identity_access.domain import sso
from tests.integration.keycloak_browser import KeycloakBrowser
from tests.integration.keycloak_container import CONSOLE_ORIGIN, PORTAL_ORIGIN, PrivateKeycloak

pytestmark = pytest.mark.integration

CLAIM = "sx_idp"
PASSWORD = "Strong-Pass-2026!"
_FORM = re.compile(r'<form[^>]*action="([^"]+)"')
_FIELD = re.compile(r"<input([^>]*)>")
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def _admin(keycloak: PrivateKeycloak, realm: str = "supportx") -> httpx.Client:
    token = httpx.post(
        f"{keycloak.base_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": keycloak.admin_user,
            "password": keycloak.admin_password,
        },
    ).json()["access_token"]
    return httpx.Client(
        base_url=f"{keycloak.base_url}/admin/realms/{realm}",
        headers={"Authorization": f"Bearer {token}"},
    )


def _claims(token: str) -> dict[str, Any]:  # Any: a JWT's JSON claims
    payload = token.split(".")[1]
    return dict(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))))


def _user(admin: httpx.Client, email: str) -> str:
    created = admin.post(
        "/users",
        json={
            "username": email,
            "email": email,
            "emailVerified": True,
            "firstName": "Sam",
            "lastName": "Test",
            "enabled": True,
            "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.headers["location"].rsplit("/", 1)[1])


class _Browser(KeycloakBrowser):
    """Follows redirects and fills every form (login, first broker login) up to the app.

    Cookies are kept per path: the two realms on one host set the same cookie names under
    their own paths (/realms/<realm>/), which the base browser's name-only jar would mix.
    """

    def __init__(self) -> None:
        super().__init__()
        self.jar: dict[tuple[str, str], str] = {}

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        path = urlsplit(url).path or "/"
        sent = {n: v for (p, n), v in sorted(self.jar.items()) if path.startswith(p)}
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in sent.items())} if sent else {}
        response = self._http.request(method, url, headers=headers, **kwargs)  # type: ignore[arg-type]  # httpx's keyword options, passed through
        for header in response.headers.get_list("set-cookie"):
            name, _, rest = header.partition("=")
            value = rest.split(";", 1)[0]
            found = re.search(r"(?i);\s*path=([^;]+)", header)
            key = (found.group(1).strip() if found else "/", name)
            if not value or "Max-Age=0" in header:
                self.jar.pop(key, None)
            else:
                self.jar[key] = value
        return response

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
            assert response.status_code == 200, (response.url, _text(response.text))
            assert form is not None, response.text[:400]
            data: dict[str, str] = {}
            for raw in _FIELD.findall(response.text):
                attrs = dict(_ATTR.findall(raw))
                if "name" in attrs and attrs.get("type") not in ("submit", "button"):
                    data[attrs["name"]] = html.unescape(attrs.get("value", ""))
            data.update(
                {k: v for k, v in (("username", username), ("password", password)) if k in data}
            )
            response = self._request("POST", html.unescape(form.group(1)), data=data)
        msg = "no redirect back to the app"
        raise AssertionError(msg)


def _text(page: str) -> str:
    """The end of a Keycloak page as plain words (its error message), for a failed assertion."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))[-600:]


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _browser_tokens(
    keycloak: PrivateKeycloak,
    *,
    username: str,
    password: str,
    hint: str | None = None,
    client: str = "supportx-console",
) -> dict[str, Any]:  # Any: Keycloak's token response
    origin, secret = (
        (CONSOLE_ORIGIN, keycloak.console_secret)
        if client == "supportx-console"
        else (PORTAL_ORIGIN, keycloak.portal_secret)
    )
    back_to = f"{origin}/api/v1/auth/callback"
    verifier, challenge = _pkce()
    query = {
        "client_id": client,
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": back_to,
        "state": secrets.token_urlsafe(8),
        "nonce": secrets.token_urlsafe(8),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if hint is not None:
        query["kc_idp_hint"] = hint
    browser = _Browser()
    try:
        code = browser.code(
            f"{keycloak.issuer}/protocol/openid-connect/auth?{urlencode(query)}",
            username,
            password,
            back_to=back_to,
        )
    finally:
        browser.close()
    tokens = httpx.post(
        f"{keycloak.issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": back_to,
            "client_id": client,
            "client_secret": secret,
            "code_verifier": verifier,
        },
    )
    assert tokens.status_code == 200, tokens.text
    return dict(tokens.json())


@pytest.fixture
def broker(private_keycloak: PrivateKeycloak) -> Iterator[tuple[str, str]]:
    """An OIDC identity provider (a second realm) and one person in it: (alias, email)."""
    base = private_keycloak.base_url
    idp_realm = f"idp-{uuid.uuid4().hex[:8]}"
    alias = f"sx-acme-{secrets.token_hex(3)}"
    secret = secrets.token_hex(16)
    email = f"sso-{uuid.uuid4().hex[:8]}@acme.test"
    with _admin(private_keycloak) as admin:  # an absolute URL: the realms list itself
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
            _user(idp, email)
        issuer = f"{base}/realms/{idp_realm}"
        with _admin(private_keycloak) as admin:
            added = admin.post(
                "/identity-provider/instances",
                json={
                    "alias": alias,
                    "providerId": "oidc",
                    "enabled": True,
                    "trustEmail": True,
                    # SupportX's own broker settings (domain/sso.py), from the provider's real
                    # discovery document: what a tenant's set-up writes, passMaxAge included.
                    "config": {
                        **sso.oidc_config(
                            httpx.get(f"{issuer}/.well-known/openid-configuration").json(),
                            client_id="supportx-broker",
                            scopes="openid email profile",
                        ),
                        "clientSecret": secret,
                    },
                },
            )
            assert added.status_code == 201, added.text
        yield alias, email
    finally:
        with _admin(private_keycloak) as admin:
            admin.delete(f"/identity-provider/instances/{alias}")
            for found in admin.get("/users", params={"email": email, "exact": "true"}).json():
                admin.delete(f"/users/{found['id']}")
        with _admin(private_keycloak, idp_realm) as idp:
            idp.delete("")


def test_both_apps_carry_the_mapper(private_keycloak: PrivateKeycloak) -> None:
    """The absence below is the rule, not a missing mapper."""
    with _admin(private_keycloak) as admin:
        for client_id in ("supportx-console", "supportx-portal"):
            (client,) = admin.get("/clients", params={"clientId": client_id}).json()
            mappers = admin.get(f"/clients/{client['id']}/protocol-mappers/models").json()
            (mapper,) = [m for m in mappers if m["name"] == "sign-in-identity-provider"]
            assert mapper["protocolMapper"] == "oidc-usersessionmodel-note-mapper"
            assert mapper["config"]["claim.name"] == CLAIM
            assert mapper["config"]["user.session.note"] == "identity_provider"


def test_a_password_sign_in_never_carries_the_claim(private_keycloak: PrivateKeycloak) -> None:
    email = f"pw-{uuid.uuid4().hex[:8]}@nowhere.test"
    with _admin(private_keycloak) as admin:
        user_id = _user(admin, email)
        try:
            for client in ("supportx-console", "supportx-portal"):
                tokens = _browser_tokens(
                    private_keycloak, username=email, password=PASSWORD, client=client
                )
                for kind in ("access_token", "id_token"):
                    assert CLAIM not in _claims(tokens[kind]), (client, kind)
                secret = (
                    private_keycloak.console_secret
                    if client == "supportx-console"
                    else private_keycloak.portal_secret
                )
                direct = httpx.post(
                    f"{private_keycloak.issuer}/protocol/openid-connect/token",
                    data={
                        "grant_type": "password",
                        "client_id": client,
                        "client_secret": secret,
                        "username": email,
                        "password": PASSWORD,
                        "scope": "openid",
                    },
                )
                assert direct.status_code == 200, direct.text
                for kind in ("access_token", "id_token"):
                    assert CLAIM not in _claims(direct.json()[kind]), (client, "direct", kind)
        finally:
            admin.delete(f"/users/{user_id}")


def test_a_brokered_sign_in_carries_the_providers_alias(
    private_keycloak: PrivateKeycloak, broker: tuple[str, str]
) -> None:
    alias, email = broker
    tokens = _browser_tokens(private_keycloak, username=email, password=PASSWORD, hint=alias)
    assert _claims(tokens["access_token"])[CLAIM] == alias
    assert _claims(tokens["id_token"])[CLAIM] == alias


def test_a_confirmation_reaches_the_brokered_provider(
    private_keycloak: PrivateKeycloak, broker: tuple[str, str]
) -> None:
    """WP-057 S2a, lane B A4: prompt=login and max_age=0 make the provider ask again.

    The person is already signed in at the provider (its own session). A confirmation through
    Keycloak must not be answered from that session: the provider's sign-in form appears again,
    and only then does the browser come back. Otherwise SupportX would mark someone as confirmed
    who never proved anything at their provider.
    """
    alias, email = broker
    back_to = f"{CONSOLE_ORIGIN}/api/v1/auth/callback"

    def authorize(**extra: str) -> str:
        _verifier, challenge = _pkce()
        query = {
            "client_id": "supportx-console", "response_type": "code", "scope": "openid",
            "redirect_uri": back_to, "state": secrets.token_urlsafe(8),
            "nonce": secrets.token_urlsafe(8), "code_challenge": challenge,
            "code_challenge_method": "S256", "kc_idp_hint": alias, **extra,
        }  # fmt: skip
        return f"{private_keycloak.issuer}/protocol/openid-connect/auth?{urlencode(query)}"

    browser = _Browser()
    try:
        browser.code(authorize(), email, PASSWORD, back_to=back_to)  # both sessions now exist
        response = browser.open(authorize(prompt="login", max_age="0"))
        asked_again = False
        for _ in range(12):
            if response.is_redirect:
                location = urljoin(str(response.url), response.headers["location"])
                assert not location.startswith(back_to) or asked_again, (
                    "the confirmation came back without the provider asking again"
                )
                if location.startswith(back_to):
                    break
                response = browser.open(location)
                continue
            if "/realms/idp-" in str(response.url) and _FORM.search(response.text):
                asked_again = True  # the provider's own sign-in form, despite its session
                break
            break
        assert asked_again, (response.status_code, str(response.url), _text(response.text))
    finally:
        browser.close()
