"""The upgrade step creating SupportX's identity service account (tooling/keycloak_identity.py)."""

import json
from typing import Any

import httpx
import pytest

from tooling.keycloak_identity import (
    CLIENT_ID,
    EVENT_TYPES,
    ROLES,
    SSO_MAX_SECONDS,
    Outcome,
    Result,
    Target,
    run,
    smtp_from_env,
)
from tooling.keycloak_theme import KeycloakUnavailableError

BASE = "http://keycloak:8080/auth"
SECRET = "a-long-identity-client-secret"  # test data
MANAGEMENT_ROLES = [*ROLES, "realm-admin", "manage-realm", "view-users"]


class FakeKeycloak:
    """The admin endpoints the step uses, with state, recording every write."""

    def __init__(self, *, realm: bool = True) -> None:
        self.realm: dict[str, Any] | None = (
            {"realm": "supportx", "ssoSessionIdleTimeout": 1800, "ssoSessionMaxLifespan": 43200}
            if realm
            else None
        )
        self.clients: list[dict[str, Any]] = []
        self.secrets: dict[str, str] = {}
        self.held: list[dict[str, str]] = []
        self.events: dict[str, Any] = {"eventsEnabled": False, "eventsListeners": ["jboss-logging"]}
        self.profile: dict[str, Any] = {"attributes": [{"name": "email"}], "groups": []}
        self.writes: list[str] = []
        self.password = "right"

    def handler(self, request: httpx.Request) -> httpx.Response:  # noqa: C901, PLR0911, PLR0912 - one fake for the whole admin API
        path = request.url.path.removeprefix("/auth")
        method = request.method
        if path == "/realms/master/protocol/openid-connect/token":
            if f"password={self.password}" not in request.content.decode():
                return httpx.Response(401)
            return httpx.Response(200, json={"access_token": "t"})
        if self.realm is None:
            return httpx.Response(404)
        body: Any = json.loads(request.content) if request.content else {}
        if method != "GET":
            self.writes.append(f"{method} {path}")
        if path == "/admin/realms/supportx":
            if method == "PUT":
                self.realm.update(body)
                return httpx.Response(204)
            return httpx.Response(200, json=self.realm)
        if path == "/admin/realms/supportx/clients":
            wanted = request.url.params.get("clientId")
            if method == "POST":
                self.clients.append({**body, "id": "c1"})
                self.secrets["c1"] = body["secret"]
                return httpx.Response(201)
            if wanted == "realm-management":
                return httpx.Response(200, json=[{"id": "rm"}])
            return httpx.Response(200, json=[c for c in self.clients if c["clientId"] == wanted])
        if path == "/admin/realms/supportx/clients/c1":
            self.clients[0] = body
            self.secrets["c1"] = body["secret"]
            return httpx.Response(204)
        if path == "/admin/realms/supportx/clients/c1/client-secret":
            return httpx.Response(200, json={"value": self.secrets["c1"]})
        if path == "/admin/realms/supportx/clients/c1/service-account-user":
            return httpx.Response(200, json={"id": "sa"})
        if path == "/admin/realms/supportx/clients/rm/roles":
            return httpx.Response(200, json=[{"id": n, "name": n} for n in MANAGEMENT_ROLES])
        if path == "/admin/realms/supportx/users/sa/role-mappings/clients/rm":
            if method == "POST":
                self.held += body
            elif method == "DELETE":
                self.held = [r for r in self.held if r not in body]
            return httpx.Response(200 if method == "GET" else 204, json=self.held)
        if path == "/admin/realms/supportx/users/profile":
            if method == "PUT":
                self.profile = body
                return httpx.Response(200, json=body)
            return httpx.Response(200, json=self.profile)
        if path == "/admin/realms/supportx/events/config":
            if method == "PUT":
                self.events = body
                return httpx.Response(204)
            return httpx.Response(200, json=self.events)
        return httpx.Response(404)


async def _run(keycloak: FakeKeycloak, password: str = "right") -> Result:  # noqa: S107 - test data  # noqa: ANN401 - Result
    return await run(
        Target(BASE, user="admin", password=password, secret=SECRET),
        wait_seconds=0,
        transport=httpx.MockTransport(keycloak.handler),
        retry_seconds=0,
    )


async def test_sets_up_the_service_account_once_then_changes_nothing() -> None:
    keycloak = FakeKeycloak()
    first = await _run(keycloak)
    assert first.outcome == Outcome.UPDATED
    client = keycloak.clients[0]
    assert client["clientId"] == CLIENT_ID
    # Client credentials only: no browser sign-in through this client, ever.
    assert client["serviceAccountsEnabled"] is True
    assert client["standardFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert keycloak.secrets["c1"] == SECRET
    assert sorted(r["name"] for r in keycloak.held) == sorted(ROLES)
    assert keycloak.events["eventsEnabled"] is True
    assert set(EVENT_TYPES) <= set(keycloak.events["enabledEventTypes"])
    assert keycloak.events["eventsListeners"] == ["jboss-logging"]  # the operator's kept
    assert keycloak.realm is not None
    assert keycloak.realm["ssoSessionMaxLifespan"] == SSO_MAX_SECONDS
    declared = {a["name"]: a for a in keycloak.profile["attributes"]}
    assert set(declared) == {"email", "sx_department", "sx_site"}  # the realm's own kept
    assert declared["sx_department"]["permissions"] == {"view": ["admin"], "edit": ["admin"]}
    keycloak.writes.clear()
    second = await _run(keycloak)
    assert (second.outcome, keycloak.writes) == (Outcome.READY, [])


async def test_puts_back_a_changed_secret_and_removes_extra_rights() -> None:
    keycloak = FakeKeycloak()
    await _run(keycloak)
    keycloak.secrets["c1"] = "rotated-by-hand"
    keycloak.held.append({"id": "realm-admin", "name": "realm-admin"})  # granted by hand
    result = await _run(keycloak)
    assert result.outcome == Outcome.UPDATED
    assert keycloak.secrets["c1"] == SECRET
    assert "realm-admin" not in {r["name"] for r in keycloak.held}
    assert "roles removed: realm-admin" in result.changes


async def test_never_shortens_a_longer_realm_session_or_drops_event_types() -> None:
    keycloak = FakeKeycloak()
    assert keycloak.realm is not None
    keycloak.realm["ssoSessionMaxLifespan"] = 2 * SSO_MAX_SECONDS
    keycloak.events = {"eventsEnabled": True, "enabledEventTypes": ["UPDATE_PASSWORD"]}
    await _run(keycloak)
    assert keycloak.realm["ssoSessionMaxLifespan"] == 2 * SSO_MAX_SECONDS
    assert keycloak.events["enabledEventTypes"][0] == "UPDATE_PASSWORD"


async def test_missing_realm_and_refused_admin_change_nothing() -> None:
    assert (await _run(FakeKeycloak(realm=False))).outcome == Outcome.NO_REALM
    keycloak = FakeKeycloak()
    assert (await _run(keycloak, password="replaced")).outcome == Outcome.ADMIN_REFUSED
    assert keycloak.writes == []


async def test_unreachable_keycloak_is_an_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    with pytest.raises(KeycloakUnavailableError):
        await run(
            Target(BASE, user="admin", password="x", secret=SECRET),
            wait_seconds=0,
            transport=httpx.MockTransport(refuse),
            retry_seconds=0,
        )


async def test_the_realm_sends_mail_through_the_installations_mail_settings() -> None:
    """D-099: one place to configure mail; Keycloak's e-mails leave from the same sender."""
    smtp = smtp_from_env(
        {
            "SUPPORTX_MAIL_SMTP_HOST": "127.0.0.1",
            "SUPPORTX_KEYCLOAK_SMTP_HOST": "mailpit",  # as Keycloak reaches it (Compose)
            "SUPPORTX_KEYCLOAK_SMTP_PORT": "1025",
            "SUPPORTX_MAIL_SMTP_SECURITY": "none",
            "SUPPORTX_MAIL_FROM_ADDRESS": "support@acme.test",
            "SUPPORTX_MAIL_FROM_NAME": "Acme IT",
        }
    )
    assert smtp == {
        "host": "mailpit",
        "port": "1025",
        "from": "support@acme.test",
        "fromDisplayName": "Acme IT",
        "ssl": "false",
        "starttls": "false",
        "auth": "false",
    }
    keycloak = FakeKeycloak()
    result = await run(
        Target(BASE, user="admin", password="right", secret=SECRET, smtp=smtp),
        wait_seconds=0,
        transport=httpx.MockTransport(keycloak.handler),
        retry_seconds=0,
    )
    assert "SMTP set from the mail settings" in result.changes
    assert keycloak.realm is not None
    assert keycloak.realm["smtpServer"] == smtp
    assert smtp_from_env({"SUPPORTX_MAIL_SMTP_HOST": "x"}) is None  # no sender: not configured
