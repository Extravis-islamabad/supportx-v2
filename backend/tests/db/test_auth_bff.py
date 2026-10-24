"""BFF login, sessions, CSRF, refresh, logout and tenant switching over HTTP.

Keycloak is replaced by FakeIdp (real RS256-signed tokens over httpx.MockTransport), Valkey by an
in-memory store; PostgreSQL is real (users are provisioned under RLS). The same flows run against
the real Keycloak in tests/integration/test_auth_keycloak.py.
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.modules.identity_access.bff.cookies import (
    DEV_COOKIE_NAME,
    PRODUCTION_COOKIE_NAME,
    cookie_name,
    set_session_cookie,
)
from app.modules.identity_access.infra.crypto import SessionCipher
from app.modules.identity_access.infra.oidc import OidcClient
from app.modules.identity_access.infra.store import SessionStore
from app.modules.identity_access.service.auth import AuthService
from app.modules.identity_access.tests.fake_idp import ISSUER, FakeIdp, FakeUser, MemoryKeyValue
from app.shared.clock import FrozenClock
from conftest import make_settings
from tests.db.test_api_tenancy import build_app
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

CONSOLE = "http://console.test"
PORTAL = "http://portal.test"


@dataclass
class Bff:
    app: FastAPI
    client: AsyncClient
    idp: FakeIdp
    kv: MemoryKeyValue
    clock: FrozenClock
    settings: Settings
    tenants: tuple[uuid.UUID, uuid.UUID]
    db: ThrowawayDatabase

    def user(self, *aliases: str, email: str = "tech@demo.test", **kw: object) -> FakeUser:
        a, b = self.tenants
        orgs = {"a": a, "b": b}
        return FakeUser(
            subject=kw.pop("subject", "sub-" + email),  # type: ignore[arg-type]
            email=email,
            name=str(kw.pop("name", "Tariq Technician")),
            organizations={alias: orgs.get(alias, uuid.UUID(int=99)) for alias in aliases},
            **kw,  # type: ignore[arg-type]
        )

    async def login(
        self, user: FakeUser, *, app: str = "console", return_to: str = "/tickets"
    ) -> httpx.Response:
        start = await self.client.get(
            "/api/v1/auth/login", params={"app": app, "returnTo": return_to}
        )
        assert start.status_code == 302, start.text
        code, state = self.idp.issue_code(start.headers["location"], user)
        return await self.client.get("/api/v1/auth/callback", params={"code": code, "state": state})

    async def me(self) -> httpx.Response:
        return await self.client.get("/api/v1/auth/me")

    async def csrf(self) -> str:
        return str((await self.me()).json()["csrf_token"])

    def cookie(self) -> str | None:
        return self.client.cookies.get(DEV_COOKIE_NAME)


@pytest_asyncio.fixture
async def bff(
    migrated_db: ThrowawayDatabase, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> AsyncIterator[Bff]:
    settings = make_settings(
        profile="test",
        database_url=migrated_db.app_url,
        oidc_issuer=ISSUER,
        oidc_console_client_secret="console-secret",
        oidc_portal_client_secret="portal-secret",
        valkey_url="valkey://127.0.0.1:1/0",
        session_secret="x" * 40,
        console_url=CONSOLE,
        portal_url=PORTAL,
        session_cookie_secure=False,
        dev_tenant_header=True,
    )
    app = build_app(settings)
    clock = FrozenClock(datetime.now(UTC).replace(microsecond=0))
    idp = FakeIdp(now=lambda: clock.now().timestamp())
    kv = MemoryKeyValue()
    async with app.router.lifespan_context(app):
        service = AuthService(
            settings=settings,
            store=SessionStore(kv, SessionCipher(settings.session_secret.get_secret_value())),  # type: ignore[union-attr]
            oidc=OidcClient(ISSUER, idp.client()),
            database=app.state.db,
            clock=clock,
            cookie_name=cookie_name(settings),
        )
        app.state.auth = service
        app.state.session_resolver = service.resolve
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url=CONSOLE) as client:
            yield Bff(app, client, idp, kv, clock, settings, tenant_pair, migrated_db)


async def user_rows(db: ThrowawayDatabase, email: str) -> list[asyncpg.Record]:
    # Superuser: users has FORCED RLS; even its owner (the migrator) sees nothing without a tenant.
    conn = await asyncpg.connect(db.admin_url)
    try:
        return await conn.fetch(
            "SELECT tenant_id, display_name, locale, user_type, version, last_login_at, created_by "
            "FROM users WHERE email = $1 ORDER BY tenant_id",
            email,
        )
    finally:
        await conn.close()


# --- login --------------------------------------------------------------------------------------


async def test_login_sets_a_safe_session_cookie_and_returns_to_the_app(bff: Bff) -> None:
    response = await bff.login(bff.user("a"), return_to="/tickets?id=7")
    assert response.status_code == 302
    assert response.headers["location"] == f"{CONSOLE}/tickets?id=7"
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{DEV_COOKIE_NAME}=")
    for flag in ("HttpOnly", "Path=/", "SameSite=lax"):
        assert flag in set_cookie
    assert "Max-Age" not in set_cookie  # browser-session cookie; the server enforces timeouts


async def test_login_never_redirects_off_site(bff: Bff) -> None:
    for evil in ("https://evil.test/x", "//evil.test", "/\\evil.test", "/%2F%2Fevil.test"):
        response = await bff.login(bff.user("a"), return_to=evil)
        assert response.headers["location"] == f"{CONSOLE}/", evil


async def test_portal_login_uses_the_portal_client_and_origin(bff: Bff) -> None:
    start = await bff.client.get("/api/v1/auth/login", params={"app": "portal"})
    assert "client_id=supportx-portal" in start.headers["location"]
    assert (
        "redirect_uri=http%3A%2F%2Fportal.test%2Fapi%2Fv1%2Fauth%2Fcallback"
        in start.headers["location"]
    )


async def test_me_describes_the_session_without_tokens(bff: Bff) -> None:
    await bff.login(bff.user("a", locale="ar", roles=("requester",)))
    response = await bff.me()
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "tech@demo.test"
    assert body["user"]["locale"] == "ar"
    assert body["user"]["user_type"] == "requester"
    assert body["tenant"]["id"] == str(bff.tenants[0])
    assert len(body["csrf_token"]) >= 32
    for secret in ("at-", "refresh", "id_token", bff.idp.kid):
        assert secret not in response.text


async def test_just_in_time_provisioning_creates_then_updates_the_user(bff: Bff) -> None:
    await bff.login(bff.user("a", email="jit@demo.test", name="First Name"))
    (first,) = await user_rows(bff.db, "jit@demo.test")
    assert (first["display_name"], first["version"], first["user_type"]) == (
        "First Name",
        1,
        "technician",
    )
    assert first["tenant_id"] == bff.tenants[0]
    bff.clock.advance(timedelta(minutes=1))
    await bff.login(bff.user("a", email="jit@demo.test", name="Renamed", locale="ar"))
    (second,) = await user_rows(bff.db, "jit@demo.test")
    assert (second["display_name"], second["locale"], second["version"]) == ("Renamed", "ar", 2)
    assert second["last_login_at"] > first["last_login_at"]

    # Signing in again with nothing changed keeps the version: an edit form open elsewhere
    # must not turn stale just because the user signed in on another device (WP-010).
    bff.clock.advance(timedelta(minutes=1))
    await bff.login(bff.user("a", email="jit@demo.test", name="Renamed", locale="ar"))
    (third,) = await user_rows(bff.db, "jit@demo.test")
    assert third["version"] == second["version"]
    assert third["last_login_at"] > second["last_login_at"]


async def test_every_login_issues_a_new_session_id(bff: Bff) -> None:
    bff.client.cookies.set(DEV_COOKIE_NAME, "attacker-chosen-session-id", domain="console.test")
    await bff.login(bff.user("a"))
    first = bff.cookie()
    assert first not in (None, "attacker-chosen-session-id")
    await bff.login(bff.user("a"))
    second = bff.cookie()
    assert second not in (None, first)
    bff.client.cookies.set(DEV_COOKIE_NAME, first or "", domain="console.test")
    assert (await bff.me()).status_code == 401  # the old session died at re-login


async def test_callback_state_is_single_use(bff: Bff) -> None:
    start = await bff.client.get("/api/v1/auth/login")
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    assert (
        await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    ).status_code == 302
    replay = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert (replay.status_code, replay.json()["code"]) == (400, "invalid_login_state")
    forged = await bff.client.get("/api/v1/auth/callback", params={"code": "x", "state": "made-up"})
    assert forged.json()["code"] == "invalid_login_state"


async def test_keycloak_errors_and_bad_tokens_fail_the_login(bff: Bff) -> None:
    start = await bff.client.get("/api/v1/auth/login")
    _code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    denied = await bff.client.get(
        "/api/v1/auth/callback", params={"error": "access_denied", "state": state}
    )
    assert (denied.status_code, denied.json()["code"]) == (400, "login_failed")
    bff.idp.token_overrides = {"iss": "http://evil.test/realms/supportx"}
    wrong_issuer = await bff.login(bff.user("a"))
    assert (wrong_issuer.status_code, wrong_issuer.json()["code"]) == (400, "login_failed")
    assert bff.cookie() is None


async def test_user_without_organization_gets_403_and_keycloak_session_ends(bff: Bff) -> None:
    response = await bff.login(bff.user())
    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "no_organization"
    assert len(bff.idp.ended_sessions) == 1
    assert bff.cookie() is None


async def test_browser_failures_land_on_the_app_with_a_label_code(bff: Bff) -> None:
    start = await bff.client.get("/api/v1/auth/login", params={"app": "portal"})
    code, state = bff.idp.issue_code(start.headers["location"], bff.user())
    html = {"Accept": "text/html,application/xhtml+xml"}
    response = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers=html
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"{PORTAL}/?auth_error=no_organization"
    replay = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers=html
    )
    assert replay.headers["location"] == f"{CONSOLE}/?auth_error=invalid_login_state"


async def test_organization_without_a_tenant_row_is_refused(bff: Bff) -> None:
    response = await bff.login(bff.user("unknown-org"))
    assert (response.status_code, response.json()["code"]) == (403, "tenant_not_provisioned")


async def test_disabled_user_cannot_log_in(bff: Bff) -> None:
    await bff.login(bff.user("a", email="gone@demo.test"))
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        await conn.execute("UPDATE users SET status = 'disabled' WHERE email = 'gone@demo.test'")
    finally:
        await conn.close()
    response = await bff.login(bff.user("a", email="gone@demo.test"))
    assert (response.status_code, response.json()["code"]) == (403, "user_disabled")


async def test_keycloak_down_at_login_is_a_clean_503(bff: Bff) -> None:
    bff.idp.available = False
    response = await bff.client.get("/api/v1/auth/login")
    assert response.status_code == 503
    assert response.json()["code"] == "identity_provider_unavailable"
    assert "Traceback" not in response.text
    assert "ConnectError" not in response.text


# --- CSRF ---------------------------------------------------------------------------------------


async def test_state_changing_requests_need_the_csrf_token(bff: Bff) -> None:
    await bff.login(bff.user("a"))
    token = await bff.csrf()
    missing = await bff.client.post("/api/v1/auth/logout")
    wrong = await bff.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "guess"})
    foreign = await bff.client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": token, "Origin": "https://evil.test"}
    )
    business = await bff.client.post("/api/v1/probe", json={"title": "x"})
    for response in (missing, wrong, foreign, business):
        assert (response.status_code, response.json()["code"]) == (403, "csrf_failed")
    # GET is safe and needs no token.
    assert (await bff.client.get("/api/v1/probe")).status_code == 200
    ok = await bff.client.post(
        "/api/v1/probe", json={"title": "x"}, headers={"X-CSRF-Token": token, "Origin": CONSOLE}
    )
    assert ok.status_code == 200


# --- expiry and refresh -------------------------------------------------------------------------


async def test_idle_timeout_ends_the_session(bff: Bff) -> None:
    await bff.login(bff.user("a"))
    bff.clock.advance(timedelta(seconds=bff.settings.session_idle_timeout_seconds))
    response = await bff.me()
    assert (response.status_code, response.json()["code"]) == (401, "session_expired")
    assert not [k for k in bff.kv.data if k.startswith("sx:session:")]


async def test_absolute_timeout_ends_even_an_active_session(bff: Bff) -> None:
    bff.idp.access_lifetime = 3 * 3600  # avoid refreshes; this test is about the absolute limit
    await bff.login(bff.user("a"))
    for _ in range(bff.settings.session_absolute_timeout_seconds // 1200 - 1):
        bff.clock.advance(timedelta(minutes=20))
        assert (await bff.me()).status_code == 200
    bff.clock.advance(timedelta(minutes=20))
    response = await bff.me()
    assert (response.status_code, response.json()["code"]) == (401, "session_expired")


async def test_expired_access_token_is_refreshed_silently(bff: Bff) -> None:
    await bff.login(bff.user("a"))
    issued = len(bff.idp.refresh_tokens)
    bff.clock.advance(timedelta(minutes=6))
    assert (await bff.me()).status_code == 200
    assert len(bff.idp.refresh_tokens) == issued + 1


async def test_refused_refresh_ends_the_session_cleanly(bff: Bff) -> None:
    await bff.login(bff.user("a"))
    bff.idp.refresh_ok = False  # e.g. the user was logged out or disabled in Keycloak
    bff.clock.advance(timedelta(minutes=6))
    response = await bff.me()
    assert (response.status_code, response.json()["code"]) == (401, "session_expired")
    assert (await bff.me()).json()["code"] == "unauthenticated"


async def test_keycloak_outage_during_refresh_keeps_the_session(bff: Bff) -> None:
    await bff.login(bff.user("a"))
    bff.idp.available = False
    bff.clock.advance(timedelta(minutes=6))
    assert (await bff.me()).status_code == 200


async def test_removed_membership_ends_the_session_at_refresh(bff: Bff) -> None:
    await bff.login(bff.user("a"))
    for user, client_id in list(bff.idp.refresh_tokens.values()):
        user.organizations.clear()
        del client_id
    bff.clock.advance(timedelta(minutes=6))
    assert (await bff.me()).json()["code"] == "session_expired"


# --- logout, tenants ------------------------------------------------------------------------------


async def test_logout_ends_both_sessions(bff: Bff) -> None:
    await bff.login(bff.user("a"))
    response = await bff.client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": await bff.csrf()}
    )
    assert response.status_code == 204
    assert (
        'supportx_session=""' in response.headers["set-cookie"]
        or "Max-Age=0" in response.headers["set-cookie"]
    )
    assert len(bff.idp.ended_sessions) == 1
    assert (await bff.me()).status_code == 401


async def test_session_tenant_wins_over_the_dev_header(bff: Bff) -> None:
    a, b = bff.tenants
    await bff.login(bff.user("a"))
    response = await bff.client.get("/api/v1/organization/tenant", headers={"X-Tenant-ID": str(b)})
    assert response.json()["id"] == str(a)


async def test_multi_organization_user_switches_tenant_with_a_new_session(bff: Bff) -> None:
    a, b = bff.tenants
    await bff.login(bff.user("a", "b", email="multi@demo.test"))
    me = (await bff.me()).json()
    assert {t["id"] for t in me["tenants"]} == {str(a), str(b)}
    assert me["tenant"]["id"] == str(a)  # first by alias
    before, token = bff.cookie(), me["csrf_token"]

    not_member = await bff.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(uuid.uuid4())},
        headers={"X-CSRF-Token": token},
    )
    assert (not_member.status_code, not_member.json()["code"]) == (403, "not_a_member")
    no_csrf = await bff.client.post("/api/v1/auth/switch-tenant", json={"tenant_id": str(b)})
    assert no_csrf.json()["code"] == "csrf_failed"

    switched = await bff.client.post(
        "/api/v1/auth/switch-tenant", json={"tenant_id": str(b)}, headers={"X-CSRF-Token": token}
    )
    assert switched.status_code == 200
    assert switched.json()["tenant"]["id"] == str(b)
    assert switched.json()["csrf_token"] != token
    assert bff.cookie() not in (None, before)
    assert (await bff.client.get("/api/v1/organization/tenant")).json()["id"] == str(b)
    assert [r["tenant_id"] for r in await user_rows(bff.db, "multi@demo.test")] == sorted([a, b])


async def test_writes_are_attributed_to_the_session_user(bff: Bff) -> None:
    await bff.login(bff.user("a", email="writer@demo.test"))
    me = (await bff.me()).json()
    created = await bff.client.post(
        "/api/v1/probe", json={"title": "mine"}, headers={"X-CSRF-Token": me["csrf_token"]}
    )
    item_id = created.json()["id"]
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        created_by = await conn.fetchval(
            "SELECT created_by FROM probe_items WHERE id = $1", uuid.UUID(item_id)
        )
    finally:
        await conn.close()
    assert str(created_by) == me["user"]["id"]


async def test_anonymous_requests_get_401(bff: Bff) -> None:
    assert (await bff.me()).json()["code"] == "unauthenticated"
    assert (await bff.client.post("/api/v1/auth/logout")).status_code == 401


# --- cookie flags (no database needed) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("profile", "name", "secure"),
    [
        ("production", PRODUCTION_COOKIE_NAME, True),
        ("test", DEV_COOKIE_NAME, True),
        ("dev", DEV_COOKIE_NAME, False),
    ],
)
def test_cookie_flags_per_profile(profile: str, name: str, secure: bool) -> None:
    overrides: dict[str, object] = {"profile": profile}
    if profile == "production":
        from conftest import PRODUCTION_REQUIRED  # noqa: PLC0415 - only this case needs it

        overrides = {**PRODUCTION_REQUIRED}
    settings = make_settings(**overrides)
    response = httpx.Response(200)
    from fastapi import Response  # noqa: PLC0415 - FastAPI response for set_cookie

    fastapi_response = Response()
    set_session_cookie(fastapi_response, settings, "sid")
    header = fastapi_response.headers["set-cookie"]
    assert header.startswith(f"{name}=sid")
    assert ("Secure" in header) is secure
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Domain" not in header
    del response


# --- events (WP-007): written with the change they describe, CLAUDE.md rule b ----------------


async def events_of(bff: Bff, email: str) -> list[dict[str, Any]]:
    """Every identity event about the user with `email` (any tenant), oldest first."""
    ids = {str(row["id"]) for row in await _user_ids(bff, email)}
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        rows = await conn.fetch(
            "SELECT envelope FROM outbox_events WHERE event_type LIKE 'identity_access.%'"
            " ORDER BY id"
        )
    finally:
        await conn.close()
    envelopes = [json.loads(row["envelope"]) for row in rows]
    return [e for e in envelopes if e["payload"].get("user_id") in ids]


async def _user_ids(bff: Bff, email: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        return await conn.fetch("SELECT id FROM users WHERE email = $1", email)
    finally:
        await conn.close()


def types(events: list[dict[str, Any]]) -> list[str]:
    return [e["event_type"].removeprefix("identity_access.") for e in events]


async def test_first_login_provisions_then_logs_in(bff: Bff) -> None:
    await bff.login(bff.user("a", email="new@demo.test", name="Noor New"))
    events = await events_of(bff, "new@demo.test")
    # WP-016 / D-029: the first login also maps the Keycloak roles to SupportX roles, once.
    assert types(events) == ["user.provisioned", "user.logged_in", "user_role.changed"]
    provisioned, logged_in, role = events
    user_id = provisioned["payload"]["user_id"]
    assert provisioned["payload"] == {"user_id": user_id, "user_type": "technician", "locale": "en"}
    assert logged_in["payload"] == {"user_id": user_id, "client": "console"}
    # The mapping is done by the platform, not the user: a system actor.
    assert (role["payload"]["user_id"], role["payload"]["change"]) == (user_id, "assigned")
    assert role["actor"] == {"type": "system", "id": "identity_access"}
    for event in (provisioned, logged_in):
        assert event["tenant_id"] == str(bff.tenants[0])
        assert event["actor"] == {"type": "user", "id": user_id}
        assert (event["aggregate_type"], event["aggregate_id"]) == ("user", user_id)
        assert event["aggregate_version"] == 1
        assert event["correlation_id"]  # the callback request's ID
    # Payloads carry IDs and codes only, never personal data (architecture.md §8.2).
    assert "new@demo.test" not in json.dumps(events)
    assert "Noor New" not in json.dumps(events)


async def test_changed_profile_is_a_user_updated_event_naming_the_fields(bff: Bff) -> None:
    await bff.login(bff.user("a", email="upd@demo.test", name="Before"))
    bff.clock.advance(timedelta(minutes=1))
    await bff.login(bff.user("a", email="upd@demo.test", name="After", locale="ar"))
    bff.clock.advance(timedelta(minutes=1))
    await bff.login(bff.user("a", email="upd@demo.test", name="After", locale="ar"))
    events = await events_of(bff, "upd@demo.test")
    assert types(events) == [
        "user.provisioned",
        "user.logged_in",
        "user_role.changed",  # the one-time role mapping (D-029); never again
        "user.updated",
        "user.logged_in",
        "user.logged_in",  # nothing changed the third time: no user.updated
    ]
    assert events[3]["payload"]["changed_fields"] == ["display_name", "locale"]
    assert events[3]["aggregate_version"] == 2
    assert "After" not in json.dumps(events)


async def test_logout_is_recorded(bff: Bff) -> None:
    await bff.login(bff.user("a", email="out@demo.test"))
    response = await bff.client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": await bff.csrf()}
    )
    assert response.status_code == 204
    events = await events_of(bff, "out@demo.test")
    assert types(events)[-1] == "user.logged_out"
    assert events[-1]["payload"]["client"] == "console"


async def test_tenant_switch_is_recorded_only_in_the_target_tenant(bff: Bff) -> None:
    a, b = bff.tenants
    await bff.login(bff.user("a", "b", email="sw@demo.test"))
    switched = await bff.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(b)},
        headers={"X-CSRF-Token": await bff.csrf()},
    )
    assert switched.status_code == 200
    events = await events_of(bff, "sw@demo.test")
    in_a = [e for e in events if e["tenant_id"] == str(a)]
    in_b = [e for e in events if e["tenant_id"] == str(b)]
    assert types(in_a) == ["user.provisioned", "user.logged_in", "user_role.changed"]
    assert types(in_b) == ["user.provisioned", "session.tenant_switched", "user_role.changed"]
    assert str(a) not in json.dumps(in_b)  # tenant B never learns about tenant A


async def test_refused_login_records_nothing(bff: Bff) -> None:
    await bff.login(bff.user("a", email="off@demo.test"))
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        await conn.execute("UPDATE users SET status = 'disabled' WHERE email = 'off@demo.test'")
    finally:
        await conn.close()
    before = await events_of(bff, "off@demo.test")
    response = await bff.login(bff.user("a", email="off@demo.test", name="Changed"))
    assert response.status_code == 403
    assert await events_of(bff, "off@demo.test") == before
    (row,) = await user_rows(bff.db, "off@demo.test")
    assert row["display_name"] != "Changed"  # the refresh rolled back with the events


# --- technician seats (WP-009) --------------------------------------------------------------------


async def set_technician_seats(db: ThrowawayDatabase, tenant: uuid.UUID, seats: int) -> None:
    """Change a tenant's plan directly (this test app caches nothing: its Valkey is unreachable)."""
    conn = await asyncpg.connect(db.migrator_url)
    try:
        await conn.execute(
            "UPDATE tenant_subscriptions SET limits = jsonb_build_object('technicians', $2::int)"
            " WHERE tenant_id = $1",
            tenant,
            seats,
        )
    finally:
        await conn.close()


async def test_technician_over_the_seat_limit_cannot_log_in(bff: Bff) -> None:
    a, _b = bff.tenants
    await set_technician_seats(bff.db, a, 1)
    first = await bff.login(bff.user("a", email="first@demo.test"))
    assert first.status_code == 302

    blocked = await bff.login(bff.user("a", email="second@demo.test"))
    body = blocked.json()
    assert (blocked.status_code, body["code"], body["message_key"]) == (
        403,
        "technician_limit_reached",
        "errors.technician_limit_reached",
    )
    assert body["params"] == {"limit": "technicians", "max": 1}
    assert await user_rows(bff.db, "second@demo.test") == []  # nothing provisioned

    # A browser lands back on the console with a translatable code, never raw JSON.
    start = await bff.client.get("/api/v1/auth/login", params={"app": "console"})
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("a", email="x@demo.test"))
    html = {"Accept": "text/html,application/xhtml+xml"}
    response = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers=html
    )
    assert response.headers["location"] == f"{CONSOLE}/?auth_error=technician_limit_reached"

    # The seat holder keeps working, and requesters are never counted.
    assert (await bff.login(bff.user("a", email="first@demo.test"))).status_code == 302
    requester = bff.user("a", email="req@demo.test", roles=("requester",))
    assert (await bff.login(requester)).status_code == 302


async def test_switching_into_a_full_tenant_is_refused(bff: Bff) -> None:
    a, b = bff.tenants
    await set_technician_seats(bff.db, b, 0)
    await bff.login(bff.user("a", "b", email="multi@demo.test"))
    switched = await bff.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(b)},
        headers={"X-CSRF-Token": await bff.csrf()},
    )
    assert (switched.status_code, switched.json()["code"]) == (403, "technician_limit_reached")
    assert (await bff.me()).json()["tenant"]["id"] == str(a)  # still in the old tenant


# --- WP-016: roles and permissions in the session ------------------------------------------------


async def test_me_returns_supportx_roles_and_effective_permissions(bff: Bff) -> None:
    admin = bff.user("a", email="perm-admin@demo.test", roles=("tenant_admin", "technician"))
    await bff.login(admin)
    me = (await bff.me()).json()
    assert me["user"]["roles"] == ["technician", "tenant_admin"]
    held = {p["key"]: p for p in me["permissions"]}
    assert held["roles.manage"] == {
        "key": "roles.manage",
        "scope": "all",
        "scopes": ["all"],
        "conditional": False,
    }
    assert held["profile.edit"]["scope"] == "own"

    await bff.login(bff.user("a", email="perm-req@demo.test", roles=("requester",)))
    me = (await bff.me()).json()
    assert me["user"]["roles"] == ["requester"]
    assert "users.view" not in {p["key"] for p in me["permissions"]}
    assert {p["key"]: p["scope"] for p in me["permissions"]}["requests.view"] == "own"


async def test_keycloak_roles_are_mapped_only_once(bff: Bff) -> None:
    """D-029: after the first login SupportX is authoritative; Keycloak roles no longer apply."""
    a, _b = bff.tenants
    await bff.login(bff.user("a", email="once@demo.test", roles=("technician",)))
    (row,) = await user_rows(bff.db, "once@demo.test")
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        # An admin removes the technician role in SupportX...
        await conn.execute(
            "DELETE FROM user_roles WHERE tenant_id = $1 AND user_id ="
            " (SELECT id FROM users WHERE tenant_id = $1 AND email = 'once@demo.test')",
            a,
        )
        # ...then the user signs in again, still a technician in Keycloak, now even an admin there.
        await bff.login(bff.user("a", email="once@demo.test", roles=("technician", "tenant_admin")))
        count = await conn.fetchval(
            "SELECT count(*) FROM user_roles ur JOIN users u ON u.id = ur.user_id"
            " WHERE u.tenant_id = $1 AND u.email = 'once@demo.test'",
            a,
        )
    finally:
        await conn.close()
    assert count == 0
    assert row["tenant_id"] == a
    assert (await bff.me()).json()["permissions"] == []


async def test_bug_04_ui_language_is_kept_per_user_across_logins_and_devices(bff: Bff) -> None:
    """QA BUG-04: the language chosen in the UI is stored with the user, not in the browser.

    Keycloak's locale only seeds it: a later login (another device, Keycloak still "en") keeps
    the choice. Choosing nothing (null) falls back to Keycloak's locale again.
    """
    user = bff.user("a", email="lang@demo.test", locale="en", roles=("technician",))
    await bff.login(user)
    me = (await bff.me()).json()
    assert me["user"]["locale"] == "en"
    path = f"/api/v1/users/{me['user']['id']}"
    read = await bff.client.get(path)
    assert read.status_code == 200, read.text
    chosen = await bff.client.patch(
        path,
        json={"ui_locale": "ar"},
        headers={"X-CSRF-Token": me["csrf_token"], "If-Match": read.headers["ETag"]},
    )
    assert chosen.status_code == 200, chosen.text
    assert (await bff.me()).json()["user"]["locale"] == "ar"
    bff.client.cookies.clear()
    await bff.login(user)  # a new session, as on another device
    again = (await bff.me()).json()
    assert again["user"]["locale"] == "ar"
    bad = await bff.client.patch(
        path,
        json={"ui_locale": "fr"},
        headers={"X-CSRF-Token": again["csrf_token"], "If-Match": chosen.headers["ETag"]},
    )
    assert bad.status_code == 422, bad.text
    cleared = await bff.client.patch(
        path,
        json={"ui_locale": None},
        headers={"X-CSRF-Token": again["csrf_token"], "If-Match": chosen.headers["ETag"]},
    )
    assert cleared.status_code == 200, cleared.text
    assert (await bff.me()).json()["user"]["locale"] == "en"
