"""A vendor support account never gets to set or change its own profile (D-173, D-177).

A temporary support account is made exactly as `support_grants` makes it: a generated login, no
e-mail, an empty last name, and the first sign-in actions (a new password, then TOTP). On a fresh
realm (this private Keycloak, imported from the shipped realm file), Keycloak's VERIFY_PROFILE
then asks for an e-mail and a last name ("Update Account Information"), so the engineer could
type in an address of their own. Lane C found it in #566's e2e; this test reproduces it, and the
fix in #566 turns it green (remove the xfail there).

The control: a staff account with an e-mail and a last name signs in with no profile page.
"""

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

import pytest

from tests.integration.keycloak_container import CONSOLE_ORIGIN, PrivateKeycloak
from tests.integration.test_sign_in_identity_provider_claim import _admin, _Browser, _text

pytestmark = pytest.mark.integration

_FORM = re.compile(r'<form[^>]*action="([^"]+)"')
_INPUT = re.compile(r"<input[^>]*>")
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
# The fields a profile page offers; a support account must never be shown one to fill.
PROFILE_FIELDS = frozenset({"email", "lastName", "firstName", "username"})
FIRST_SIGN_IN_ACTIONS = ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]  # support_grants' own list


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


@pytest.fixture
def accounts(private_keycloak: PrivateKeycloak) -> Iterator[dict[str, Any]]:  # Any: per account
    """A support account made as support_grants makes it, and a staff control."""
    made: list[str] = []
    out: dict[str, Any] = {}
    with _admin(private_keycloak) as admin:
        for kind in ("support", "staff"):
            password = _password()
            if kind == "support":
                username = f"support-{uuid.uuid4().hex[:10]}"
                body: dict[str, Any] = {  # Any: Keycloak's user JSON
                    "username": username,
                    "firstName": "Vendor engineer",
                    "lastName": "",
                    "enabled": True,
                    "attributes": {"locale": ["en"]},
                    "requiredActions": FIRST_SIGN_IN_ACTIONS,
                }
            else:
                username = f"staff-{uuid.uuid4().hex[:8]}@example.test"
                body = {
                    "username": username,
                    "email": username,
                    "emailVerified": True,
                    "firstName": "Staff",
                    "lastName": "Member",
                    "enabled": True,
                    "attributes": {"locale": ["en"]},
                }
            created = admin.post("/users", json=body)
            assert created.status_code == 201, created.text
            user_id = created.headers["location"].rsplit("/", 1)[1]
            made.append(user_id)
            reset = admin.put(
                f"/users/{user_id}/reset-password",
                json={"type": "password", "value": password, "temporary": False},
            )
            assert reset.status_code == 204, reset.text
            # The password step resets nothing else: put the first sign-in actions back.
            if kind == "support":
                admin.put(f"/users/{user_id}", json={"requiredActions": FIRST_SIGN_IN_ACTIONS})
            out[kind] = {"id": user_id, "username": username, "password": password}
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


@pytest.mark.xfail(
    strict=True,
    reason="D-177 finding (lane C, #566 e2e): VERIFY_PROFILE asks a support account for an "
    "e-mail and last name; #566 fixes it and removes this mark",
)
def test_a_support_account_is_never_offered_its_profile(
    private_keycloak: PrivateKeycloak, accounts: dict[str, Any]
) -> None:
    """Its first sign-in is a new password and TOTP, and nothing that edits the profile."""
    support = accounts["support"]
    before = _user(private_keycloak, support["id"])
    assert sorted(before.get("requiredActions", [])) == sorted(FIRST_SIGN_IN_ACTIONS)
    offered = _first_sign_in(private_keycloak, support["username"], support["password"])
    after = _user(private_keycloak, support["id"])
    # The address an engineer typed on a profile page would be kept: checked first, the worst part.
    assert after.get("email") in (None, ""), after.get("email")
    assert all(not page for page in offered), offered
    assert after.get("requiredActions", []) == []
