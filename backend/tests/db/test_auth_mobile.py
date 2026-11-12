"""Mobile sign-in over HTTP (ADR-044): the browser login ends in the app with a one-time code.

The same fake identity provider and real PostgreSQL as test_auth_bff.py. The app never holds a
cookie: it exchanges the code (with the verifier of the challenge it started with) for its
session ID and sends that in the `X-SupportX-Session` header.
"""

import secrets
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx

from app.modules.identity_access.domain.mobile import SESSION_HEADER, challenge_for
from tests.db import test_auth_bff
from tests.db.test_auth_bff import PORTAL, Bff

pytestmark = test_auth_bff.pytestmark
bff = test_auth_bff.bff  # the BFF world fixture, reused

# The settings default outside production (ADR-044 item 3: the chart sets the https one).
APP_RETURN = "http://localhost:5173/mobile/auth"


def new_verifier() -> str:
    return secrets.token_urlsafe(32)  # 43 characters of the RFC 7636 alphabet


async def mobile_login(
    bff: Bff, user: object, verifier: str, *, app: str = "console", **device: str
) -> httpx.Response:
    """Start a mobile login and finish it at the identity provider; the callback's answer."""
    start = await bff.client.get(
        "/api/v1/auth/login",
        params={"app": app, "mobile_challenge": challenge_for(verifier), **device},
    )
    assert start.status_code == 302, start.text
    code, state = bff.idp.issue_code(start.headers["location"], user)  # type: ignore[arg-type]
    return await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})


def handoff_of(response: httpx.Response) -> str:
    target = urlsplit(response.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == APP_RETURN
    return parse_qs(target.query)["handoff"][0]


async def exchange(bff: Bff, handoff: str, verifier: str) -> httpx.Response:
    return await bff.client.post(
        "/api/v1/auth/mobile/exchange", json={"handoff": handoff, "verifier": verifier}
    )


async def signed_in(bff: Bff, user: object) -> str:
    """A full mobile sign-in: the session ID the app would keep."""
    verifier = new_verifier()
    answer = await mobile_login(bff, user, verifier)
    exchanged = await exchange(bff, handoff_of(answer), verifier)
    assert exchanged.status_code == 200, exchanged.text
    return str(exchanged.json()["session_id"])


async def test_the_login_ends_in_the_app_with_a_code_and_no_cookie(bff: Bff) -> None:
    verifier = new_verifier()
    answer = await mobile_login(bff, bff.user("a", email="mobile@demo.test"), verifier)
    assert answer.status_code == 302, answer.text
    assert "set-cookie" not in answer.headers
    assert bff.cookie() is None

    exchanged = await exchange(bff, handoff_of(answer), verifier)
    assert exchanged.status_code == 200, exchanged.text
    session_id = exchanged.json()["session_id"]
    assert "set-cookie" not in exchanged.headers

    me = await bff.client.get("/api/v1/auth/me", headers={SESSION_HEADER: session_id})
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == "mobile@demo.test"
    assert "access_token" not in me.text  # Keycloak's tokens never reach the device


async def test_a_code_works_once_and_only_with_its_verifier(bff: Bff) -> None:
    verifier = new_verifier()
    handoff = handoff_of(await mobile_login(bff, bff.user("a"), verifier))

    wrong = await exchange(bff, handoff, new_verifier())
    assert (wrong.status_code, wrong.json()["code"]) == (401, "handoff_invalid")
    # Spent by the wrong try: the right verifier no longer helps (no second guess).
    spent = await exchange(bff, handoff, verifier)
    assert (spent.status_code, spent.json()["code"]) == (401, "handoff_invalid")

    verifier = new_verifier()
    handoff = handoff_of(await mobile_login(bff, bff.user("a"), verifier))
    assert (await exchange(bff, handoff, verifier)).status_code == 200
    replay = await exchange(bff, handoff, verifier)
    assert (replay.status_code, replay.json()["code"]) == (401, "handoff_invalid")
    unknown = await exchange(bff, "made-up", verifier)
    assert (unknown.status_code, unknown.json()["code"]) == (401, "handoff_invalid")


async def test_a_malformed_challenge_is_refused_before_keycloak(bff: Bff) -> None:
    for bad in ("short", "x" * 43 + "=", "+" * 43):
        start = await bff.client.get("/api/v1/auth/login", params={"mobile_challenge": bad})
        assert start.status_code in {400, 422}, bad
        if start.status_code == 400:
            assert start.json()["code"] == "invalid_mobile_challenge"


async def test_failures_go_back_to_the_app_with_a_label_code(bff: Bff) -> None:
    """No JSON in the phone's browser: the app shows the code's label (rule 5d)."""
    verifier = new_verifier()
    answer = await mobile_login(bff, bff.user(), verifier)  # no organization
    assert answer.status_code == 303
    assert answer.headers["location"] == f"{APP_RETURN}?auth_error=no_organization"
    assert bff.cookie() is None


async def test_a_requester_gets_a_portal_session_in_the_same_app(bff: Bff) -> None:
    """D-160: one app for both. A requester never gets a console session (D-129)."""
    requester = bff.user("a", email="mobile-requester@demo.test", roles=("requester",))
    verifier = new_verifier()
    answer = await mobile_login(bff, requester, verifier)
    assert answer.status_code == 303, answer.text
    again = urlsplit(answer.headers["location"])
    assert f"{again.scheme}://{again.netloc}{again.path}" == f"{PORTAL}/api/v1/auth/login"
    query = parse_qs(again.query)
    assert query["app"] == ["portal"]
    assert query["mobile_challenge"] == [challenge_for(verifier)]  # the same verifier finishes it

    portal = await mobile_login(bff, requester, verifier, app="portal")
    exchanged = await exchange(bff, handoff_of(portal), verifier)
    assert exchanged.status_code == 200, exchanged.text
    session_id = exchanged.json()["session_id"]
    me = await bff.client.get(
        "/api/v1/auth/me", headers={SESSION_HEADER: session_id, "X-SupportX-Client": "mobile"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["user"]["user_type"] == "requester"


async def test_writes_need_the_csrf_token_and_logout_ends_the_session(bff: Bff) -> None:
    session_id = await signed_in(bff, bff.user("a", email="mobile-writer@demo.test"))
    header = {SESSION_HEADER: session_id}
    token = (await bff.client.get("/api/v1/auth/me", headers=header)).json()["csrf_token"]

    no_csrf = await bff.client.post("/api/v1/auth/logout", headers=header)
    assert (no_csrf.status_code, no_csrf.json()["code"]) == (403, "csrf_failed")
    out = await bff.client.post("/api/v1/auth/logout", headers={**header, "X-CSRF-Token": token})
    assert out.status_code == 204
    assert (await bff.client.get("/api/v1/auth/me", headers=header)).status_code == 401


async def test_a_tenant_switch_hands_the_app_its_new_session_id(bff: Bff) -> None:
    _a, b = bff.tenants
    session_id = await signed_in(bff, bff.user("a", "b", email="mobile-multi@demo.test"))
    header = {SESSION_HEADER: session_id}
    token = (await bff.client.get("/api/v1/auth/me", headers=header)).json()["csrf_token"]

    switched = await bff.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(b)},
        headers={**header, "X-CSRF-Token": token},
    )
    assert switched.status_code == 200, switched.text
    new_id = switched.headers[SESSION_HEADER]
    assert new_id != session_id
    me = await bff.client.get("/api/v1/auth/me", headers={SESSION_HEADER: new_id})
    assert me.json()["tenant"]["id"] == str(b)
    assert (await bff.client.get("/api/v1/auth/me", headers=header)).status_code == 401
    assert uuid.UUID(me.json()["user"]["id"])


async def test_the_session_list_names_the_phone(bff: Bff) -> None:
    """ADR-044 item 5: the person sees which phone and app version each mobile session is."""
    verifier = new_verifier()
    answer = await mobile_login(
        bff,
        bff.user("a", email="mobile-listed@demo.test"),
        verifier,
        mobile_platform="ios",
        mobile_version="1.4.2",
    )
    exchanged = await exchange(bff, handoff_of(answer), verifier)
    session_id = exchanged.json()["session_id"]

    listed = await bff.client.get("/api/v1/auth/sessions", headers={SESSION_HEADER: session_id})
    assert listed.status_code == 200, listed.text
    (row,) = listed.json()
    assert (row["client"], row["platform"], row["app_version"]) == ("mobile", "ios", "1.4.2")
    assert row["current"] is True


async def test_an_unknown_platform_or_a_strange_version_never_reaches_the_list(bff: Bff) -> None:
    verifier = new_verifier()
    start = await bff.client.get(
        "/api/v1/auth/login",
        params={"mobile_challenge": challenge_for(verifier), "mobile_platform": "windows"},
    )
    assert start.status_code == 422  # only ios and android

    answer = await mobile_login(
        bff,
        bff.user("a", email="mobile-version@demo.test"),
        verifier,
        mobile_platform="android",
        mobile_version="<b>1</b>",
    )
    exchanged = await exchange(bff, handoff_of(answer), verifier)
    header = {SESSION_HEADER: exchanged.json()["session_id"]}
    (row,) = (await bff.client.get("/api/v1/auth/sessions", headers=header)).json()
    assert (row["client"], row["platform"], row["app_version"]) == ("mobile", "android", None)
