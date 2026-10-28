"""The upgrade step creating SupportX's identity service account (tooling/keycloak_identity.py)."""

import json
from typing import Any

import httpx
import pytest

from tooling.keycloak_identity import (
    CLIENT_ID,
    EVENT_TYPES,
    LOCKOUT,
    OLD_DEFAULT_POLICY,
    PROFILE_ATTRIBUTES,
    REALM_CLIENT_ID,
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
REALM_SECRET = "a-long-realm-client-secret"  # test data
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
        self.held_by: dict[str, list[dict[str, str]]] = {}
        self.events: dict[str, Any] = {"eventsEnabled": False, "eventsListeners": ["jboss-logging"]}
        self.profile: dict[str, Any] = {"attributes": [{"name": "email"}], "groups": []}
        self.writes: list[str] = []
        self.executions: list[dict[str, str]] = [
            {"id": "e-otp", "providerId": "auth-otp-form", "requirement": "ALTERNATIVE"},
            {
                "id": "e-rec",
                "providerId": "auth-recovery-authn-code-form",
                "requirement": "DISABLED",
            },
        ]
        self.password = "right"

    @property
    def held(self) -> list[dict[str, str]]:
        """The identity client's roles (the first client made)."""
        return self.held_by.setdefault("sa-c1", [])

    @held.setter
    def held(self, roles: list[dict[str, str]]) -> None:
        self.held_by["sa-c1"] = roles

    def client(self, client_id: str) -> dict[str, Any]:
        return next(c for c in self.clients if c["clientId"] == client_id)

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
                internal = f"c{len(self.clients) + 1}"
                self.clients.append({**body, "id": internal})
                self.secrets[internal] = body["secret"]
                return httpx.Response(201)
            if wanted == "realm-management":
                return httpx.Response(200, json=[{"id": "rm"}])
            return httpx.Response(200, json=[c for c in self.clients if c["clientId"] == wanted])
        parts = path.removeprefix("/admin/realms/supportx/").split("/")
        if parts[0] == "clients" and parts[1] == "rm" and parts[2:] == ["roles"]:
            return httpx.Response(200, json=[{"id": n, "name": n} for n in MANAGEMENT_ROLES])
        if parts[0] == "clients" and len(parts) >= 2:
            internal, rest = parts[1], parts[2:]
            if not rest:
                index = next(i for i, c in enumerate(self.clients) if c["id"] == internal)
                self.clients[index] = body
                self.secrets[internal] = body["secret"]
                return httpx.Response(204)
            if rest == ["client-secret"]:
                return httpx.Response(200, json={"value": self.secrets[internal]})
            if rest == ["service-account-user"]:
                return httpx.Response(200, json={"id": f"sa-{internal}"})
        if parts[0] == "users" and parts[2:] == ["role-mappings", "clients", "rm"]:
            held = self.held_by.setdefault(parts[1], [])
            if method == "POST":
                held += body
            elif method == "DELETE":
                self.held_by[parts[1]] = [r for r in held if r not in body]
            return httpx.Response(200 if method == "GET" else 204, json=self.held_by[parts[1]])
        if path == "/admin/realms/supportx/authentication/flows/browser/executions":
            if method == "PUT":
                for execution in self.executions:
                    if execution["id"] == body["id"]:
                        execution["requirement"] = body["requirement"]
                return httpx.Response(202)
            return httpx.Response(200, json=self.executions)
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


async def _run(keycloak: FakeKeycloak, password: str = "right", realm_secret: str = "") -> Result:  # noqa: S107 - test data
    return await run(
        Target(BASE, user="admin", password=password, secret=SECRET, realm_secret=realm_secret),
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
    assert set(declared) == {"email", *PROFILE_ATTRIBUTES}  # the realm's own kept
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


async def test_a_second_client_holds_only_manage_realm_for_the_password_policy() -> None:
    """WP-039 session 2: the realm setting has its own account, given to the worker alone."""
    keycloak = FakeKeycloak()
    await _run(keycloak)
    assert [c["clientId"] for c in keycloak.clients] == [CLIENT_ID]  # no secret: not made
    result = await _run(keycloak, realm_secret=REALM_SECRET)
    realm_client = keycloak.client(REALM_CLIENT_ID)
    assert f"client {REALM_CLIENT_ID} created" in result.changes
    assert realm_client["serviceAccountsEnabled"] is True
    assert realm_client["standardFlowEnabled"] is False
    assert keycloak.secrets[realm_client["id"]] == REALM_SECRET
    assert [r["name"] for r in keycloak.held_by[f"sa-{realm_client['id']}"]] == ["manage-realm"]
    assert "manage-realm" not in {r["name"] for r in keycloak.held}  # never on the API's
    keycloak.writes.clear()
    again = await _run(keycloak, realm_secret=REALM_SECRET)
    assert (again.outcome, keycloak.writes) == (Outcome.READY, [])


async def test_only_the_old_shipped_password_policy_is_upgraded() -> None:
    keycloak = FakeKeycloak()
    assert keycloak.realm is not None
    keycloak.realm["passwordPolicy"] = OLD_DEFAULT_POLICY
    result = await _run(keycloak)
    assert "password policy: the new default (breached list on)" in result.changes
    assert "passwordBlacklist(supportx-breached.txt)" in keycloak.realm["passwordPolicy"]
    chosen = "length(16) and passwordHistory(3)"  # an operator's or an admin's own
    keycloak.realm["passwordPolicy"] = chosen
    await _run(keycloak)
    assert keycloak.realm["passwordPolicy"] == chosen


async def test_only_the_old_shipped_lock_out_is_upgraded() -> None:
    """REQ-SEC-005 AC2 (D-104): 15 minutes, growing in equal steps, at most an hour."""
    keycloak = FakeKeycloak()
    assert keycloak.realm is not None
    keycloak.realm.update(
        {"failureFactor": 5, "waitIncrementSeconds": 60, "maxFailureWaitSeconds": 900}
    )
    result = await _run(keycloak)
    assert "lock-out: 15 minutes, growing, at most an hour" in result.changes
    assert {key: keycloak.realm[key] for key in LOCKOUT} == LOCKOUT
    keycloak.realm["waitIncrementSeconds"] = 300  # an operator's own choice
    keycloak.writes.clear()
    await _run(keycloak)
    assert keycloak.realm["waitIncrementSeconds"] == 300
    assert keycloak.writes == []


async def test_recovery_codes_are_offered_at_sign_in_once() -> None:
    """REQ-SEC-025: Keycloak ships the step disabled; an operator's own choice is kept."""
    keycloak = FakeKeycloak()
    result = await _run(keycloak)
    assert "recovery codes offered at sign-in" in result.changes
    assert keycloak.executions[1]["requirement"] == "ALTERNATIVE"
    keycloak.executions[1]["requirement"] = "REQUIRED"  # an operator's own choice
    keycloak.writes.clear()
    await _run(keycloak)
    assert keycloak.executions[1]["requirement"] == "REQUIRED"
    assert keycloak.writes == []
