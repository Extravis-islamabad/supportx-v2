"""A vendor support account never gets to set or change its own profile (D-173, D-177).

Lane B's reproduction (test/support-account-profile) of lane C's #566 e2e finding: with no
e-mail and an empty last name, a fresh realm's VERIFY_PROFILE asked the engineer to fill them in
("Update Account Information") and kept the address typed. The fix (#566, lane B's conditions):
the account is made through SupportX's own identity client (`KeycloakAdmin`, set up by the deploy
step with exactly its install roles) as `support_grants` makes it: a generated login, its own
verified `.invalid` address, both names, no default roles, and the first sign-in actions (a new
password, then TOTP). Its first sign-in offers no profile field, keeps the server's address, and
the account cannot change its own address through Keycloak's account API.

The control: a staff account with an e-mail and a last name signs in with no profile page.
"""

import asyncio
import base64
import hashlib
import hmac
import html
import re
import secrets
import struct
import time
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
import pytest

from app.modules.identity_access.domain import support_grants as rules
from app.modules.identity_access.infra.keycloak_admin import KeycloakAdmin
from tests.integration.keycloak_container import CONSOLE_ORIGIN, PrivateKeycloak
from tests.integration.test_keycloak_admin import service_accounts
from tests.integration.test_sign_in_identity_provider_claim import _admin, _Browser, _text

__all__ = ["service_accounts"]  # the deploy-step fixture, reused

pytestmark = pytest.mark.integration

_FORM = re.compile(r'<form[^>]*action="([^"]+)"')
_INPUT = re.compile(r"<input[^>]*>")
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
# The fields a profile page offers; a support account must never be shown one to fill.
PROFILE_FIELDS = frozenset({"email", "lastName", "firstName", "username"})
FIRST_SIGN_IN_ACTIONS = list(rules.FIRST_SIGN_IN_ACTIONS)  # support_grants' own list


def _password() -> str:
    """Random, and always within the realm's policy (a digit, upper, lower, a symbol)."""
    return "Support-" + secrets.token_hex(8) + "Aa9!"


def _totp(secret: str, at: float) -> str:
    """Keycloak's default policy (HmacSHA1, 6 digits, 30 s); the key is the secret's bytes."""
    counter = struct.pack(">Q", int(at) // 30)
    digest = hmac.new(secret.encode(), counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _fields(page: str) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for raw in _INPUT.findall(page):
        attrs = dict(_ATTR.findall(raw))
        if "name" in attrs and attrs.get("type") not in ("submit", "button"):
            found[attrs["name"]] = attrs
    return found


def _first_sign_in(keycloak: PrivateKeycloak, username: str, password: str) -> list[set[str]]:
    """Walks the browser sign-in to the app; every page's editable profile fields, in order.

    Fills what a real first sign-in fills: the password, a new password, a TOTP enrolment. A
    profile page is answered with an address of the engineer's own, as an engineer could.
    """
    back_to = f"{CONSOLE_ORIGIN}/api/v1/auth/callback"
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    query = {
        "client_id": "supportx-console",
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": back_to,
        "state": secrets.token_urlsafe(8),
        "nonce": secrets.token_urlsafe(8),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    browser = _Browser()
    offered: list[set[str]] = []
    new_password = _password()
    try:
        response = browser.open(
            f"{keycloak.issuer}/protocol/openid-connect/auth?{urlencode(query)}"
        )
        for _ in range(16):
            if response.is_redirect:
                location = urljoin(str(response.url), response.headers["location"])
                if location.startswith(back_to):
                    assert "code" in parse_qs(urlsplit(location).query), location
                    return offered
                response = browser.open(location)
                continue
            form = _FORM.search(response.text)
            assert response.status_code == 200, (response.url, _text(response.text))
            assert form is not None, _text(response.text)
            fields = _fields(response.text)
            data = {name: html.unescape(attrs.get("value", "")) for name, attrs in fields.items()}
            editable = {
                name
                for name, attrs in fields.items()
                if name in PROFILE_FIELDS
                and attrs.get("type") != "hidden"
                and "readonly" not in attrs
                and "disabled" not in attrs
            }
            # The sign-in form (identity-first: the username page, then the password page) is not
            # a profile page: its username field is the login.
            if "kc-form-login" in response.text:
                editable = set()
                data.update(
                    {
                        k: v
                        for k, v in (("username", username), ("password", password))
                        if k in fields
                    }
                )
            offered.append(editable)
            if "password-new" in data:
                data.update({"password-new": new_password, "password-confirm": new_password})
            if "totpSecret" in data:
                data["totp"] = _totp(data["totpSecret"], time.time())
                data.setdefault("userLabel", "integration")
            if "email" in editable:
                data["email"] = f"engineer-{uuid.uuid4().hex[:8]}@their-own.test"
            if "lastName" in editable:
                data["lastName"] = "Own"
            response = browser._request("POST", html.unescape(form.group(1)), data=data)  # noqa: SLF001 - the browser's own cookie-keeping request
    finally:
        browser.close()
    msg = f"no redirect back to the app; fields seen {offered}; last page: {_text(response.text)}"
    raise AssertionError(msg)


async def _support_account(
    keycloak: PrivateKeycloak, identity_secret: str, grant_id: uuid.UUID
) -> str:
    """The account exactly as `support_grants.create_grant` makes it, through the same client."""
    admin = KeycloakAdmin(
        keycloak.base_url, "supportx", client_id="supportx-identity", client_secret=identity_secret
    )
    try:
        first, last = rules.support_names("Vendor engineer", grant_id)
        account = await admin.create_user(
            email=rules.support_address(grant_id),
            email_verified=True,
            username=rules.support_login(grant_id),
            first_name=first,
            last_name=last,
            locale="en",
        )
        await admin.drop_default_roles(account)
        await admin.require_actions(account, FIRST_SIGN_IN_ACTIONS)
        return account
    finally:
        await admin.close()


@pytest.fixture
def accounts(
    private_keycloak: PrivateKeycloak, service_accounts: tuple[str, str]
) -> Iterator[dict[str, Any]]:  # Any: per account
    """A support account made as support_grants makes it, and a staff control."""
    made: list[str] = []
    out: dict[str, Any] = {}
    with _admin(private_keycloak) as admin:
        for kind in ("support", "staff"):
            password = _password()
            if kind == "support":
                grant_id = uuid.uuid4()
                username = rules.support_login(grant_id)
                user_id = asyncio.run(
                    _support_account(private_keycloak, service_accounts[0], grant_id)
                )
            else:
                grant_id = None
                username = f"staff-{uuid.uuid4().hex[:8]}@example.test"
                created = admin.post(
                    "/users",
                    json={
                        "username": username,
                        "email": username,
                        "emailVerified": True,
                        "firstName": "Staff",
                        "lastName": "Member",
                        "enabled": True,
                        "attributes": {"locale": ["en"]},
                    },
                )
                assert created.status_code == 201, created.text
                user_id = created.headers["location"].rsplit("/", 1)[1]
            made.append(user_id)
            # The engineer's sign-in starts from a password (the out-of-band path's).
            reset = admin.put(
                f"/users/{user_id}/reset-password",
                json={"type": "password", "value": password, "temporary": False},
            )
            assert reset.status_code == 204, reset.text
            # The password step resets nothing else: put the first sign-in actions back.
            if kind == "support":
                admin.put(f"/users/{user_id}", json={"requiredActions": FIRST_SIGN_IN_ACTIONS})
            out[kind] = {
                "id": user_id,
                "username": username,
                "password": password,
                "grant_id": grant_id,
            }
        try:
            yield out
        finally:
            for user_id in made:
                admin.delete(f"/users/{user_id}")


def _user(private_keycloak: PrivateKeycloak, user_id: str) -> dict[str, Any]:  # Any: user JSON
    with _admin(private_keycloak) as admin:
        found = admin.get(f"/users/{user_id}")
        assert found.status_code == 200, found.text
        return dict(found.json())


def test_a_staff_account_signs_in_with_no_profile_page(
    private_keycloak: PrivateKeycloak, accounts: dict[str, Any]
) -> None:
    """The control: the same realm, an account with a complete profile."""
    staff = accounts["staff"]
    offered = _first_sign_in(private_keycloak, staff["username"], staff["password"])
    assert all(not page for page in offered), offered


def test_a_support_account_is_never_offered_its_profile(
    private_keycloak: PrivateKeycloak, accounts: dict[str, Any]
) -> None:
    """Its first sign-in is a new password and TOTP, and nothing that edits the profile."""
    support = accounts["support"]
    before = _user(private_keycloak, support["id"])
    assert sorted(before.get("requiredActions", [])) == sorted(FIRST_SIGN_IN_ACTIONS)
    offered = _first_sign_in(private_keycloak, support["username"], support["password"])
    after = _user(private_keycloak, support["id"])
    # The address an engineer typed on a profile page would be kept: checked first, the worst
    # part. It is still exactly the server's own .invalid one (lane B).
    assert after.get("email") == rules.support_address(support["grant_id"]), after.get("email")
    assert after.get("emailVerified") is True
    assert all(not page for page in offered), offered
    assert after.get("requiredActions", []) == []


def test_a_support_account_cannot_change_its_own_address(
    private_keycloak: PrivateKeycloak, accounts: dict[str, Any]
) -> None:
    """No default roles, so no account-console role: Keycloak's account API refuses the change
    (401 or 403, lane B's condition 3), while the staff control with default roles may."""
    results: dict[str, int] = {}
    for kind in ("support", "staff"):
        who = accounts[kind]
        if kind == "support":
            # As once its first sign-in is done (no actions left); no TOTP enrolled, so the
            # password grant below needs no code. Only the account API's answer is under test.
            with _admin(private_keycloak) as admin:
                cleared = admin.put(f"/users/{who['id']}", json={"requiredActions": []})
                assert cleared.status_code == 204, cleared.text
        token = httpx.post(
            f"{private_keycloak.issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": who["username"],
                "password": who["password"],
            },
        )
        assert token.status_code == 200, token.text
        changed = httpx.post(
            f"{private_keycloak.issuer}/account",
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            json={
                "username": who["username"],
                "email": f"own-{uuid.uuid4().hex[:8]}@their-own.test",
                "firstName": "Own",
                "lastName": "Own",
            },
        )
        results[kind] = changed.status_code
    assert results["support"] in (401, 403), results
    assert results["staff"] == 204, results  # the control: default roles allow it
    with _admin(private_keycloak) as admin:
        support = admin.get(f"/users/{accounts['support']['id']}").json()
    assert support["email"] == rules.support_address(accounts["support"]["grant_id"])
