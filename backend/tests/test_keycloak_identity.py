"""The upgrade step creating SupportX's identity service account (tooling/keycloak_identity.py)."""

import json
import secrets
from typing import Any

import httpx
import pytest

from app.modules.identity_access.domain.security_notice_import import NOTICE_TYPES
from tooling.keycloak_identity import (
    CLIENT_ID,
    EVENT_TYPES,
    EVENTS_CLIENT_ID,
    FEDERATION_CLIENT_ID,
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
        # WP-057 S1b: SupportX's post-broker flow (authentication/flows, its executions).
        self.flows: list[dict[str, Any]] = []
        self.flow_executions: list[dict[str, Any]] = []

    @property
    def held(self) -> list[dict[str, str]]:
        """The identity client's roles (the first client made)."""
        return self.held_by.setdefault("sa-c1", [])

    @held.setter
    def held(self, roles: list[dict[str, str]]) -> None:
        self.held_by["sa-c1"] = roles

    def client(self, client_id: str) -> dict[str, Any]:
        return next(c for c in self.clients if c["clientId"] == client_id)

    def _flows(self, method: str, path: str, body: Any) -> httpx.Response | None:  # noqa: ANN401 - JSON
        """SupportX's post-broker flow and its one step (WP-057 S1b); None for other paths."""
        if path == "/admin/realms/supportx/authentication/flows":
            if method == "POST":
                self.flows.append(body)
                return httpx.Response(201)
            return httpx.Response(200, json=self.flows)
        if not path.startswith("/admin/realms/supportx/authentication/flows/supportx-otp-after"):
            return None
        if method == "POST":
            step = {"id": "e-pb", "providerId": body["provider"], "requirement": "DISABLED"}
            self.flow_executions.append(step)
            return httpx.Response(201)
        if method == "PUT":
            self.flow_executions = [body]
            return httpx.Response(202)
        return httpx.Response(200, json=self.flow_executions)

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
        flows = self._flows(method, path, body)
        if flows is not None:
            return flows
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


async def _run(
    keycloak: FakeKeycloak,
    password: str = "right",  # noqa: S107 - test data
    realm_secret: str = "",
    federation_secret: str = "",
    events_secret: str = "",
) -> Result:
    return await run(
        Target(
            BASE,
            user="admin",
            password=password,
            secret=SECRET,
            realm_secret=realm_secret,
            federation_secret=federation_secret,
            events_secret=events_secret,
        ),
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


async def test_audit_26_an_upgraded_realm_gets_refresh_token_rotation_once() -> None:
    keycloak = FakeKeycloak()
    assert keycloak.realm is not None
    keycloak.realm.update({"revokeRefreshToken": False, "refreshTokenMaxReuse": 3})
    first = await _run(keycloak)
    assert (keycloak.realm["revokeRefreshToken"], keycloak.realm["refreshTokenMaxReuse"]) == (
        True,
        0,
    )
    assert "refresh-token rotation on" in first.changes
    assert "refresh-token rotation on" not in (await _run(keycloak)).changes


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


# Made at run time: a fixed random-looking constant reads as a leaked key to the secret scan.
FEDERATION_SECRET = secrets.token_urlsafe(24)


async def test_the_federation_account_exists_only_where_ldap_is_on() -> None:
    """WP-040 (D-118, product owner 2026-11-03): on-prem LDAP only, manage-realm only.

    The identity account stays limited.
    """
    keycloak = FakeKeycloak()
    await _run(keycloak)
    assert FEDERATION_CLIENT_ID not in {c["clientId"] for c in keycloak.clients}  # LDAP off
    result = await _run(keycloak, federation_secret=FEDERATION_SECRET)
    federation = keycloak.client(FEDERATION_CLIENT_ID)
    assert f"client {FEDERATION_CLIENT_ID} created" in result.changes
    assert (federation["serviceAccountsEnabled"], federation["standardFlowEnabled"]) == (
        True,
        False,
    )
    assert keycloak.secrets[federation["id"]] == FEDERATION_SECRET
    assert [r["name"] for r in keycloak.held_by[f"sa-{federation['id']}"]] == ["manage-realm"]
    assert "manage-realm" not in {r["name"] for r in keycloak.held}  # never on the identity account
    keycloak.writes.clear()
    again = await _run(keycloak, federation_secret=FEDERATION_SECRET)
    assert (again.outcome, keycloak.writes) == (Outcome.READY, [])


async def test_turning_ldap_off_switches_the_federation_account_off_and_never_deletes_it() -> None:
    keycloak = FakeKeycloak()
    await _run(keycloak, federation_secret=FEDERATION_SECRET)
    result = await _run(keycloak)  # the chart no longer passes the secret
    federation = keycloak.client(FEDERATION_CLIENT_ID)
    assert federation["enabled"] is False
    assert f"client {FEDERATION_CLIENT_ID} switched off (LDAP not enabled)" in result.changes
    assert not any(w.startswith("DELETE") and "clients" in w for w in keycloak.writes)
    keycloak.writes.clear()
    again = await _run(keycloak)
    assert keycloak.writes == []  # already off: nothing more
    assert again.outcome == Outcome.READY
    back = await _run(keycloak, federation_secret=FEDERATION_SECRET)  # LDAP on again
    assert keycloak.client(FEDERATION_CLIENT_ID)["enabled"] is True
    assert f"client {FEDERATION_CLIENT_ID} settings or secret set" in back.changes


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


async def test_the_post_broker_mfa_flow_is_made_once_with_one_required_code_step() -> None:
    """REQ-SEC-026 AC2 (WP-057 S1b): made once, never duplicated; the step is required."""
    keycloak = FakeKeycloak()
    result = await _run(keycloak)
    assert "post-broker MFA flow created" in result.changes
    assert [f["alias"] for f in keycloak.flows] == ["supportx-otp-after-broker"]
    assert [(e["providerId"], e["requirement"]) for e in keycloak.flow_executions] == [
        ("auth-otp-form", "REQUIRED")
    ]
    keycloak.writes.clear()
    await _run(keycloak)
    assert len(keycloak.flows) == 1
    assert not [w for w in keycloak.writes if "authentication/flows/supportx-otp" in w]


EVENTS_SECRET = secrets.token_urlsafe(24)  # made at run time, as FEDERATION_SECRET


async def test_the_events_client_reads_events_only_and_loses_any_extra_role() -> None:
    """WP-057 S1b (lane B): supportx-events holds exactly view-events; extras are taken away."""
    keycloak = FakeKeycloak()
    assert EVENTS_CLIENT_ID not in {c["clientId"] for c in keycloak.clients}
    await _run(keycloak)  # no secret: not made
    assert EVENTS_CLIENT_ID not in {c["clientId"] for c in keycloak.clients}
    result = await _run(keycloak, events_secret="events-s3cret")
    events = keycloak.client(EVENTS_CLIENT_ID)
    assert f"client {EVENTS_CLIENT_ID} created" in result.changes
    assert events["serviceAccountsEnabled"] is True
    assert not events["standardFlowEnabled"]
    assert not events["directAccessGrantsEnabled"]
    assert not events["implicitFlowEnabled"]
    assert events["publicClient"] is False
    assert not events.get("redirectUris")
    held = keycloak.held_by[f"sa-{events['id']}"]
    assert sorted(r["name"] for r in held) == ["view-events"]
    # Someone gives it more by hand: the next run takes it away.
    held.append({"id": "manage-users", "name": "manage-users"})
    again = await _run(keycloak, events_secret="events-s3cret")
    assert sorted(r["name"] for r in keycloak.held_by[f"sa-{events['id']}"]) == ["view-events"]
    assert again.outcome is Outcome.UPDATED  # the extra role was taken away


async def test_adds_the_notice_event_types_once_and_keeps_a_longer_expiry() -> None:
    """REQ-SEC-033 part 2 (lane B): the three user event types are added idempotently; the
    operator's longer events expiry is kept; supportx-events still holds view-events only."""
    keycloak = FakeKeycloak()
    keycloak.events = {
        "eventsEnabled": True,
        "enabledEventTypes": [t for t in EVENT_TYPES if t not in NOTICE_TYPES],
        "eventsExpiration": 30 * 86400,
    }
    await _run(keycloak)
    types = keycloak.events["enabledEventTypes"]
    assert set(NOTICE_TYPES) <= set(types)
    assert len(types) == len(set(types))  # none twice
    assert keycloak.events["eventsExpiration"] == 30 * 86400
    keycloak.writes.clear()
    assert (await _run(keycloak)).outcome == Outcome.READY
    assert keycloak.writes == []
