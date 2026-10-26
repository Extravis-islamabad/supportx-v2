"""The upgrade step giving existing realms the SupportX login theme (tooling/keycloak_theme.py)."""

import json
from typing import Any

import httpx
import pytest

from tooling.keycloak_theme import KeycloakUnavailableError, Outcome, Target, run

BASE = "http://keycloak:8080/auth"
RIGHT = "right"  # the fake admin password (test data)


class FakeKeycloak:
    """Keycloak's token and realm endpoints, recording the updates it receives."""

    def __init__(self, realm: dict[str, Any] | None, *, password: str = RIGHT) -> None:
        self.realm = realm
        self.password = password
        self.updates: list[dict[str, Any]] = []
        self.failures_left = 0  # answer 503 this many times first (Keycloak starting)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.failures_left:
            self.failures_left -= 1
            return httpx.Response(503)
        path = request.url.path.removeprefix("/auth")
        if path == "/realms/master/protocol/openid-connect/token":
            form = dict(x.split("=") for x in request.content.decode().split("&"))
            if form["client_id"] != "admin-cli" or form["password"] != self.password:
                return httpx.Response(401, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "token"})
        assert request.headers["Authorization"] == "Bearer token"
        if path != "/admin/realms/supportx" or self.realm is None:
            return httpx.Response(404)
        if request.method == "PUT":
            body = json.loads(request.content)
            self.updates.append(body)
            self.realm.update(body)
            return httpx.Response(204)
        return httpx.Response(200, json=self.realm)


async def _run(keycloak: FakeKeycloak, password: str = RIGHT, wait: float = 0) -> Any:  # noqa: ANN401 - Result
    return await run(
        Target(BASE, user="admin", password=password),
        wait_seconds=wait,
        transport=httpx.MockTransport(keycloak.handler),
        retry_seconds=0,
    )


async def test_sets_the_theme_on_a_realm_without_one() -> None:
    keycloak = FakeKeycloak({"realm": "supportx", "displayName": "SupportX"})
    result = await _run(keycloak)
    assert (result.outcome, result.theme) == (Outcome.SET, "supportx")
    # Only the login theme is sent: nothing else of the realm is touched.
    assert keycloak.updates == [{"loginTheme": "supportx"}]
    assert (await _run(keycloak)).outcome == Outcome.KEPT  # idempotent: the next deploy keeps it


@pytest.mark.parametrize("chosen", ["keycloak.v2", "acme-corp", "supportx"])
async def test_never_overwrites_a_chosen_theme(chosen: str) -> None:
    keycloak = FakeKeycloak({"realm": "supportx", "loginTheme": chosen})
    result = await _run(keycloak)
    assert (result.outcome, result.theme) == (Outcome.KEPT, chosen)
    assert keycloak.updates == []


async def test_empty_theme_counts_as_none() -> None:
    keycloak = FakeKeycloak({"realm": "supportx", "loginTheme": ""})
    assert (await _run(keycloak)).outcome == Outcome.SET


async def test_missing_realm_and_refused_admin_change_nothing() -> None:
    assert (await _run(FakeKeycloak(None))).outcome == Outcome.NO_REALM
    keycloak = FakeKeycloak({"realm": "supportx"})
    assert (await _run(keycloak, password="replaced")).outcome == Outcome.ADMIN_REFUSED
    assert keycloak.updates == []


async def test_waits_for_keycloak_to_start_then_gives_up() -> None:
    keycloak = FakeKeycloak({"realm": "supportx"})
    keycloak.failures_left = 3
    assert (await _run(keycloak, wait=30)).outcome == Outcome.SET
    down = FakeKeycloak({"realm": "supportx"})
    down.failures_left = 10_000
    with pytest.raises(KeycloakUnavailableError):
        await _run(down, wait=0)


async def test_unreachable_keycloak_is_an_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    with pytest.raises(KeycloakUnavailableError, match="refused"):
        await run(
            Target(BASE, user="admin", password=RIGHT),
            wait_seconds=0,
            transport=httpx.MockTransport(refuse),
            retry_seconds=0,
        )
