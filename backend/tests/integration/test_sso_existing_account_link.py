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
from tests.integration.keycloak_container import CONSOLE_ORIGIN, PrivateKeycloak
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


def _victim_password() -> str:
    """A random password that always meets the realm policy (a digit, upper, lower, a symbol,
    length): a bare `token_urlsafe` can lack a digit, which Keycloak refuses (a CI flake)."""
    return "Victim-" + secrets.token_hex(8) + "Aa9!"


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
                        "value": _victim_password(),
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


@pytest.fixture
def verified_domain(
    private_keycloak: PrivateKeycloak, existing_and_provider: tuple[str, str, str]
) -> Iterator[tuple[str, str, str]]:
    """The provider's tenant has VERIFIED the existing account's e-mail domain (WP-057 S5d).

    An organization holding that domain, verified, routed to the provider with autoRedirect (the
    shape domain/sso.py writes), and the provider linked to it, so its sign-ins onboard members.
    """
    existing, alias, email = existing_and_provider
    domain = email.rsplit("@", 1)[1]
    slug = f"org-{uuid.uuid4().hex[:8]}"
    with _admin(private_keycloak) as admin:
        made = admin.post(
            "/organizations",
            json={
                "name": slug,
                "alias": slug,
                "enabled": True,
                "domains": [{"name": domain, "verified": True}],
            },
        )
        assert made.status_code == 201, made.text
        organization = str(made.headers["location"].rsplit("/", 1)[1])
        # Keycloak routes a domain only to a provider already linked to the organization.
        linked = admin.post(
            f"/organizations/{organization}/identity-providers",
            content=f'"{alias}"',
            headers={"Content-Type": "application/json"},
        )
        assert linked.status_code in (201, 204), linked.text
        whole = admin.get(f"/organizations/{organization}").json()
        whole["domains"] = [
            {"name": domain, "verified": True, "identityProviderAlias": alias, "autoRedirect": True}
        ]
        routed = admin.put(f"/organizations/{organization}", json=whole)
        assert routed.status_code == 204, routed.text
        check = admin.get(f"/organizations/{organization}").json()
        assert check["domains"][0]["verified"] is True, check
    try:
        yield existing, alias, email
    finally:
        with _admin(private_keycloak) as admin:
            admin.delete(f"/organizations/{organization}")


def test_a_verified_domain_never_links_an_existing_account_without_its_proof(
    private_keycloak: PrivateKeycloak,
    verified_domain: tuple[str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S5d marks a tenant's domain verified in Keycloak: still no link by e-mail alone (D-177).

    Keycloak 26.8's verified organization domain routes sign-ins and onboards members of the
    linked provider; it must not stand in for the existing account's own proof.
    """
    existing, alias, email = verified_domain
    monkeypatch.setattr(claim_tests, "_Browser", _Linker)
    try:
        tokens: dict[str, Any] | None = _browser_tokens(
            private_keycloak, username=email, password=PASSWORD, hint=alias
        )
    except _Stopped:
        tokens = None  # Keycloak asked for proof the provider's person doesn't have: safe
    if tokens is not None:
        assert _claims(tokens["access_token"])["sub"] != existing, (
            "a verified organization domain let a provider sign in as an existing account"
        )
    with _admin(private_keycloak) as admin:
        links = admin.get(f"/users/{existing}/federated-identity").json()
        assert all(link.get("identityProvider") != alias for link in links), links
        orgs = admin.get(f"/organizations/members/{existing}/organizations").json()
        assert orgs == [], "the existing account was made an organization member without proof"


def _links_by_email_alone(steps: set[str]) -> bool:
    """Whether a broker flow could link an existing account without its proof."""
    return (
        "idp-auto-link" in steps
        or "idp-confirm-link" not in steps
        or not ({"idp-email-verification", "idp-username-password-form"} & steps)
    )


def _steps(admin: httpx.Client, flow: str) -> set[str]:
    found = admin.get(f"/authentication/flows/{flow}/executions")
    assert found.status_code == 200, found.text
    return {str(e.get("providerId")) for e in found.json() if e.get("providerId")}


def test_the_first_broker_login_flow_never_links_by_e_mail_alone(
    private_keycloak: PrivateKeycloak,
) -> None:
    """The realm property the tests above rest on (D-177; the coordinator, #568).

    Tenant providers use "first broker login" (domain/sso.py `representation`, unit-tested with
    `trustEmail: False` and this alias; the identity step repairs a provider that trusts its
    e-mail). This pins the flow itself, from the dev realm: built in, so the admin API can't add
    a step to it; it never auto-links an existing account; and it keeps the steps that make the
    account prove itself. The check is shown to catch an auto-link on an editable copy.
    """
    with _admin(private_keycloak) as admin:
        flows = {f["alias"]: f for f in admin.get("/authentication/flows").json()}
        assert flows["first broker login"]["builtIn"] is True
        assert not _links_by_email_alone(_steps(admin, "first%20broker%20login"))
        # The control: a copy with Keycloak's auto-link step added is caught.
        copy = f"broker-copy-{uuid.uuid4().hex[:6]}"
        made = admin.post(
            "/authentication/flows/first%20broker%20login/copy", json={"newName": copy}
        )
        assert made.status_code == 201, made.text
        try:
            added = admin.post(
                f"/authentication/flows/{copy}/executions/execution",
                json={"provider": "idp-auto-link"},
            )
            assert added.status_code in (201, 204), added.text
            assert _links_by_email_alone(_steps(admin, copy))
        finally:
            flow_id = next(
                f["id"] for f in admin.get("/authentication/flows").json() if f["alias"] == copy
            )
            admin.delete(f"/authentication/flows/{flow_id}")


def _first_step(private_keycloak: PrivateKeycloak, username: str) -> httpx.Response:
    """The shared sign-in page (no organisation, no provider hint), its username submitted."""
    query = {
        "client_id": "supportx-console",
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": f"{CONSOLE_ORIGIN}/api/v1/auth/callback",
        "state": secrets.token_urlsafe(8),
        "code_challenge": claim_tests._pkce()[1],  # noqa: SLF001 - the client requires PKCE
        "code_challenge_method": "S256",
    }
    browser = _Browser()
    try:
        page = browser.open(
            f"{private_keycloak.issuer}/protocol/openid-connect/auth?"
            + "&".join(f"{k}={v}" for k, v in query.items())
        )
        for _ in range(4):  # Keycloak's own redirects to its login page
            if not page.is_redirect:
                break
            page = browser.open(urljoin(str(page.url), page.headers["location"]))
        form = _FORM.search(page.text)
        assert page.status_code == 200, _text(page.text)
        assert form is not None, page.text[:400]
        return browser._request(  # noqa: SLF001 - the test browser's own cookie-keeping request
            "POST", html.unescape(form.group(1)), data={"username": username}
        )
    finally:
        browser.close()


def test_an_address_in_a_verified_domain_goes_to_its_tenants_provider(
    private_keycloak: PrivateKeycloak, verified_domain: tuple[str, str, str]
) -> None:
    """WP-057 S5d, REQ-SEC-010 AC3 (lane B's condition 3, Keycloak's half): on the shared page,
    an address in tenant A's verified domain is sent to A's provider; an address in a domain no
    tenant has verified is asked for its password, as before."""
    _existing, alias, email = verified_domain
    routed = _first_step(private_keycloak, f"someone-{uuid.uuid4().hex[:6]}@{email.split('@')[1]}")
    assert routed.is_redirect, _text(routed.text)
    assert f"/broker/{alias}/" in routed.headers["location"], routed.headers["location"]
    unknown = _first_step(private_keycloak, f"someone@unverified-{uuid.uuid4().hex[:6]}.test")
    assert not (unknown.is_redirect and "/broker/" in unknown.headers.get("location", ""))
