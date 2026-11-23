"""Per-address limits on the sign-in routes, failing closed without Valkey (audit row 14).

The BFF world of test_auth_bff.py, whose rate limiter counts in memory (CountingValkey).
"""

from typing import Any

import httpx
import pytest

from app.modules.identity_access.bff.routes import CALLBACKS_PER_ADDRESS, LOGINS_PER_ADDRESS
from app.modules.identity_access.domain.mobile import challenge_for
from app.modules.organization.api.branding import PUBLIC_BRANDING_PER_ADDRESS
from app.modules.organization.api.domains import DOMAIN_CHECKS_PER_ADDRESS
from app.shared.api.ratelimit import RATE_LIMITER_STATE
from tests.db import test_auth_bff
from tests.db.test_auth_bff import CONSOLE, PORTAL, Bff
from tests.db.test_auth_mobile import APP_RETURN, new_verifier

pytestmark = test_auth_bff.pytestmark
bff = test_auth_bff.bff  # the BFF world fixture, reused

HTML = {"Accept": "text/html,application/xhtml+xml"}


def from_address(bff: Bff, monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    """Later requests come from `address` (as uvicorn resolved it through trusted proxies)."""
    transport = bff.client._transport  # noqa: SLF001 - the ASGI transport's client address
    monkeypatch.setattr(transport, "client", (address, 1234))


def valkey_down(bff: Bff) -> None:
    getattr(bff.app.state, RATE_LIMITER_STATE).client.down = True


async def test_login_is_limited_per_address(bff: Bff, monkeypatch: pytest.MonkeyPatch) -> None:
    from_address(bff, monkeypatch, "203.0.113.7")
    answers = [await bff.client.get("/api/v1/auth/login") for _ in range(LOGINS_PER_ADDRESS)]
    assert {a.status_code for a in answers} == {302}
    assert answers[0].headers["ratelimit-limit"] == str(LOGINS_PER_ADDRESS)
    refused = await bff.client.get("/api/v1/auth/login")
    assert (refused.status_code, refused.json()["code"]) == (429, "rate_limited")
    assert int(refused.headers["retry-after"]) >= 1
    # A browser is sent back to its app with a label code, never a JSON page.
    page = await bff.client.get("/api/v1/auth/login", headers=HTML)
    assert page.status_code == 303
    assert page.headers["location"] == f"{CONSOLE}/?auth_error=rate_limited"
    # Another address is untouched.
    from_address(bff, monkeypatch, "203.0.113.8")
    assert (await bff.client.get("/api/v1/auth/login")).status_code == 302


async def test_callback_is_limited_per_address(bff: Bff, monkeypatch: pytest.MonkeyPatch) -> None:
    from_address(bff, monkeypatch, "203.0.113.9")
    junk = {"code": "x", "state": "made-up"}
    answers = [
        await bff.client.get("/api/v1/auth/callback", params=junk)
        for _ in range(CALLBACKS_PER_ADDRESS)
    ]
    assert {a.json()["code"] for a in answers} == {"invalid_login_state"}
    refused = await bff.client.get("/api/v1/auth/callback", params=junk)
    assert (refused.status_code, refused.json()["code"]) == (429, "rate_limited")
    # A refused callback leaves a real state alone: once the window passes it still works.
    from_address(bff, monkeypatch, "203.0.113.10")
    assert (await bff.login(bff.user("a"))).status_code == 302


async def _flood_callbacks(bff: Bff) -> None:
    junk = {"code": "x", "state": "made-up"}
    for _ in range(CALLBACKS_PER_ADDRESS):
        await bff.client.get("/api/v1/auth/callback", params=junk)


async def test_a_refused_callback_goes_back_to_the_app_its_sign_in_started_in(
    bff: Bff, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pending login says which app; it is read, never spent, so the retry still works."""
    from_address(bff, monkeypatch, "203.0.113.11")
    start = await bff.client.get("/api/v1/auth/login", params={"app": "portal"})
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    await _flood_callbacks(bff)
    page = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers=HTML
    )
    assert page.status_code == 303
    assert page.headers["location"] == f"{PORTAL}/?auth_error=rate_limited"
    # An unknown state (a scripted flood) goes to the console, as before.
    junk = await bff.client.get(
        "/api/v1/auth/callback", params={"code": "x", "state": "made-up"}, headers=HTML
    )
    assert junk.headers["location"] == f"{CONSOLE}/?auth_error=rate_limited"
    # The state was not spent: from an address with budget left, the same callback signs in.
    from_address(bff, monkeypatch, "203.0.113.12")
    done = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert done.status_code == 302, done.text
    assert done.headers["location"].startswith(PORTAL)


async def test_a_refused_app_callback_goes_back_to_the_app(
    bff: Bff, monkeypatch: pytest.MonkeyPatch
) -> None:
    from_address(bff, monkeypatch, "203.0.113.13")
    params = {"mobile_challenge": challenge_for(new_verifier())}
    start = await bff.client.get("/api/v1/auth/login", params=params)
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    await _flood_callbacks(bff)
    page = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers=HTML
    )
    target = httpx.URL(page.headers["location"])
    assert f"{target.scheme}://{target.host}:{target.port}{target.path}" == APP_RETURN
    assert target.params["auth_error"] == "rate_limited"


async def test_a_refused_callback_with_valkey_down_goes_to_the_console(bff: Bff) -> None:
    """With Valkey down the pending login cannot be read: the console, as before."""
    start = await bff.client.get("/api/v1/auth/login", params={"app": "portal"})
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    valkey_down(bff)
    page = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers=HTML
    )
    assert page.headers["location"] == f"{CONSOLE}/?auth_error=sign_in_unavailable"


async def test_sign_in_fails_closed_when_valkey_is_down(bff: Bff) -> None:
    start = await bff.client.get("/api/v1/auth/login")
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    valkey_down(bff)
    login = await bff.client.get("/api/v1/auth/login")
    assert (login.status_code, login.json()["code"]) == (503, "sign_in_unavailable")
    assert login.headers["retry-after"] == "2"
    page = await bff.client.get("/api/v1/auth/login", headers=HTML)
    assert page.headers["location"] == f"{CONSOLE}/?auth_error=sign_in_unavailable"
    callback = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert (callback.status_code, callback.json()["code"]) == (503, "sign_in_unavailable")
    assert bff.cookie() is None


async def test_public_routes_still_fail_open_when_valkey_is_down(bff: Bff) -> None:
    """Only the sign-in routes fail closed: a sign-in page's brand keeps loading."""
    valkey_down(bff)
    branding = await bff.client.get("/api/v1/public/branding")
    assert branding.status_code == 200, branding.text
    assert "ratelimit-limit" not in branding.headers


async def test_the_app_sign_in_refused_goes_back_to_the_app(bff: Bff) -> None:
    valkey_down(bff)
    params: dict[str, Any] = {"mobile_challenge": challenge_for(new_verifier())}
    answer = await bff.client.get("/api/v1/auth/login", params=params)
    assert answer.status_code == 303
    target = httpx.URL(answer.headers["location"])
    assert f"{target.scheme}://{target.host}:{target.port}{target.path}" == APP_RETURN
    assert target.params["auth_error"] == "sign_in_unavailable"


async def test_public_routes_carry_their_address_budgets(bff: Bff) -> None:
    """Nobody signs in for these: counted per address, with the usual headers (audit row 14)."""
    branding = await bff.client.get("/api/v1/public/branding")
    assert branding.headers["ratelimit-limit"] == str(PUBLIC_BRANDING_PER_ADDRESS)
    # The proof is a plain Response the route builds, so no headers there; the limit still holds.
    path = "/api/v1/public/domain-check/abc"
    checks = [await bff.client.get(path) for _ in range(DOMAIN_CHECKS_PER_ADDRESS)]
    assert {c.status_code for c in checks} == {200}
    refused = await bff.client.get(path)
    assert (refused.status_code, refused.json()["code"]) == (429, "rate_limited")
