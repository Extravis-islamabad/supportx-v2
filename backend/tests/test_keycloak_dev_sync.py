"""`make keycloak-dev-sync` (D-151): only the local dev realm, only the quick sign-in's settings."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from tooling import keycloak_dev_sync as sync

LOCAL = "http://localhost:28080"


def _client(
    client_id: str, uri: str = "http://localhost:5173/api/v1/auth/callback"
) -> dict[str, Any]:
    return {"id": f"id-{client_id}", "clientId": client_id, "redirectUris": [uri]}


def test_only_this_machine_with_the_quick_sign_in_on() -> None:
    sync.check_local(LOCAL, "true")
    sync.check_local("http://127.0.0.1:28080", "TRUE")
    for url, flag in (
        ("https://id.customer.example", "true"),
        ("http://10.0.0.5:8080", "true"),
        (LOCAL, None),
        (LOCAL, "false"),
    ):
        with pytest.raises(sync.RefusedError):
            sync.check_local(url, flag)


def test_a_realm_whose_clients_leave_localhost_is_not_the_dev_realm() -> None:
    sync.check_clients({c: _client(c) for c in sync.CLIENTS})
    with pytest.raises(sync.RefusedError, match="outside localhost"):
        sync.check_clients(
            {
                "supportx-console": _client("supportx-console"),
                "supportx-portal": _client("supportx-portal", "https://portal.bank.example/cb"),
            }
        )
    with pytest.raises(sync.RefusedError, match="no supportx-portal"):
        sync.check_clients({"supportx-console": _client("supportx-console")})


def test_session_values_are_raised_never_lowered() -> None:
    assert sync.realm_changes({"rememberMe": False, "ssoSessionIdleTimeout": 1800}) == {
        "rememberMe": True,
        **dict.fromkeys(sync.SESSION_VALUES, sync.WEEK),
    }
    longer = {"rememberMe": True, **dict.fromkeys(sync.SESSION_VALUES, sync.WEEK * 2)}
    assert sync.realm_changes(longer) == {}


class FakeKeycloak:
    """The admin API calls the step makes, recorded; users are never asked for."""

    def __init__(self, uri: str = "http://localhost:5173/api/v1/auth/callback") -> None:
        self.clients = {
            c: {**_client(c, uri), "directAccessGrantsEnabled": False} for c in sync.CLIENTS
        }
        self.realm: dict[str, Any] = {"realm": "supportx", "rememberMe": False}
        self.calls: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        assert "/users" not in path  # never users or credentials
        if path.endswith("/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and path == "/admin/realms/supportx":
            return httpx.Response(200, json=self.realm)
        if request.method == "GET" and path == "/admin/realms/supportx/clients":
            wanted = request.url.params["clientId"]
            return httpx.Response(200, json=[self.clients[wanted]])
        if request.method == "PUT" and path.startswith("/admin/realms/supportx/clients/"):
            body = json.loads(request.content)
            self.clients[body["clientId"]] = body
            return httpx.Response(204)
        if request.method == "PUT" and path == "/admin/realms/supportx":
            self.realm.update(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404)


def _run(fake: FakeKeycloak) -> list[str]:
    transport = httpx.MockTransport(fake.handle)
    original = httpx.AsyncClient.__init__

    def patched(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401 - httpx options
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx.AsyncClient, "__init__", patched)
        return asyncio.run(
            sync.run(
                LOCAL,
                user="admin",
                password="x",
                realm="supportx",
                quick_sign_in="true",
                wait_seconds=0,
            )
        )


def test_it_sets_the_deltas_once_and_is_idempotent() -> None:
    fake = FakeKeycloak()
    first = _run(fake)
    assert "supportx-console: password grant on" in first
    assert "supportx-portal: password grant on" in first
    assert all(c["directAccessGrantsEnabled"] for c in fake.clients.values())
    assert fake.realm["rememberMe"] is True
    assert fake.realm["ssoSessionMaxLifespan"] == sync.WEEK
    assert _run(fake) == []  # the second run changes nothing


def test_a_non_local_realm_is_refused_before_any_change() -> None:
    fake = FakeKeycloak(uri="https://console.customer.example/api/v1/auth/callback")
    with pytest.raises(sync.RefusedError):
        _run(fake)
    assert not [c for c in fake.calls if c[0] == "PUT"]
