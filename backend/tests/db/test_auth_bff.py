"""BFF login, sessions, CSRF, refresh, logout and tenant switching over HTTP.

Keycloak is replaced by FakeIdp (real RS256-signed tokens over httpx.MockTransport), Valkey by an
in-memory store; PostgreSQL is real (users are provisioned under RLS). The same flows run against
the real Keycloak in tests/integration/test_auth_keycloak.py.
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.errors import NotFound
from app.modules.identity_access.bff.cookies import (
    DEV_COOKIE_NAME,
    DEV_LOGIN_COOKIE_PREFIX,
    PRODUCTION_COOKIE_NAME,
    cookie_name,
    login_cookie_name,
    set_session_cookie,
)
from app.modules.identity_access.infra.crypto import SessionCipher
from app.modules.identity_access.infra.keycloak_admin import LoginEvent
from app.modules.identity_access.infra.models import SESSION_LIMITS
from app.modules.identity_access.infra.oidc import OidcClient
from app.modules.identity_access.infra.store import SessionStore
from app.modules.identity_access.service import sso_test
from app.modules.identity_access.service.auth import AuthService, binding_digest
from app.modules.identity_access.tests.fake_idp import ISSUER, FakeIdp, FakeUser, MemoryKeyValue
from app.shared.api.ratelimit import RATE_LIMITER_STATE, RateLimiter, SettingsPolicyProvider
from app.shared.api.tests.test_ip_rate_limit import CountingValkey
from app.shared.clock import FrozenClock
from app.shared.crypto import key_id_of
from conftest import make_settings
from tests.app_state import set_state
from tests.db.test_api_tenancy import build_app
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

CONSOLE = "http://console.test"
CONSOLE_LIMITS = SESSION_LIMITS["console"]  # a tenant without own settings (Appendix A)
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
        # Rate limits on memory too: the settings' Valkey is unreachable on purpose, and the
        # sign-in routes fail closed without one (audit row 14).
        # The world's frozen clock, never wall time: the limiter counts in fixed windows, and a
        # test whose requests straddled a window edge saw its count reset (a flake in CI on
        # test_login_is_limited_per_address, 2026-11-12).
        limiter = RateLimiter(
            CountingValkey(),
            prefix="t:",
            provider=SettingsPolicyProvider(settings),
            clock=lambda: clock.now().timestamp(),
        )
        setattr(app.state, RATE_LIMITER_STATE, limiter)
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
    # The other Set-Cookie clears the login-binding cookie (audit row 4).
    (set_cookie,) = (
        c for c in response.headers.get_list("set-cookie") if c.startswith(f"{DEV_COOKIE_NAME}=")
    )
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


async def test_a_requester_signing_in_on_the_console_lands_on_the_portal(bff: Bff) -> None:
    """REQ-PRT-001 AC1 (WP-028): no console session; Keycloak's own signs them in to the portal."""
    requester = bff.user("a", email="to-portal@demo.test", roles=("requester",))
    response = await bff.login(requester, return_to="/incidents/42")
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"{PORTAL}/"  # its home: console paths mean nothing
    assert bff.cookie() is None
    assert (await bff.me()).status_code == 401
    # On the portal itself they sign in as usual.
    landed = await bff.login(requester, app="portal", return_to="/requests")
    assert (landed.status_code, landed.headers["location"]) == (302, f"{PORTAL}/requests")
    assert (await bff.me()).json()["user"]["user_type"] == "requester"


async def test_a_portal_session_never_opens_the_console_on_a_shared_host(bff: Bff) -> None:
    """D-129: one host, one cookie: the console's calls are refused, the portal keeps working."""
    requester = bff.user("a", email="shared-host@demo.test", roles=("requester",))
    await bff.login(requester, app="portal")
    as_console = await bff.client.get("/api/v1/auth/me", headers={"X-SupportX-Client": "console"})
    assert (as_console.status_code, as_console.json()["code"]) == (401, "console_requester_only")
    as_portal = await bff.client.get("/api/v1/auth/me", headers={"X-SupportX-Client": "portal"})
    assert as_portal.status_code == 200  # the portal session was not ended


async def test_sign_in_and_me_apply_one_rule(bff: Bff) -> None:
    """D-129: who the BFF sends to the portal is exactly who /me refuses the console."""
    cases = {
        "only-requester@demo.test": (("requester",), False),
        "staff@demo.test": (("technician",), True),
        "both@demo.test": (("requester", "technician"), True),
    }
    for email, (roles, console) in cases.items():
        person = bff.user("a", email=email, roles=roles)
        landed = await bff.login(person)
        assert (landed.status_code == 302) is console, email
        await bff.login(person, app="portal")
        me = await bff.client.get("/api/v1/auth/me", headers={"X-SupportX-Client": "console"})
        assert (me.status_code == 200) is console, email


async def test_an_agent_signing_in_on_the_console_is_unchanged(bff: Bff) -> None:
    agent = bff.user("a", email="agent@demo.test", roles=("technician",))
    response = await bff.login(agent, return_to="/incidents/42")
    assert (response.status_code, response.headers["location"]) == (302, f"{CONSOLE}/incidents/42")
    assert bff.cookie() is not None


async def _grant(bff: Bff, email: str, role: str) -> None:
    conn = await asyncpg.connect(bff.db.admin_url)  # user_roles has FORCED RLS
    try:
        await conn.execute(
            "INSERT INTO user_roles (tenant_id, user_id, role_id)"
            " SELECT u.tenant_id, u.id, r.id FROM users u JOIN roles r ON r.tenant_id = u.tenant_id"
            " WHERE u.email = $1 AND r.key = $2 ON CONFLICT DO NOTHING",
            email,
            role,
        )
    finally:
        await conn.close()


async def _revoke(bff: Bff, email: str, role: str) -> None:
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        await conn.execute(
            "DELETE FROM user_roles ur USING users u, roles r WHERE ur.user_id = u.id"
            " AND ur.role_id = r.id AND u.email = $1 AND r.key = $2",
            email,
            role,
        )
    finally:
        await conn.close()


async def test_supportx_roles_decide_the_landing_not_keycloak(bff: Bff) -> None:
    """D-129, D-029: any role but requester opens the console; Keycloak's roles do not count."""
    promoted = bff.user("a", email="promoted@demo.test", roles=("requester",))
    await bff.login(promoted, app="portal")
    await _grant(bff, "promoted@demo.test", "technician")
    landed = await bff.login(promoted, return_to="/incidents")
    assert (landed.status_code, landed.headers["location"]) == (302, f"{CONSOLE}/incidents")

    demoted = bff.user("a", email="demoted@demo.test", roles=("technician",))
    await bff.login(demoted)
    await _revoke(bff, "demoted@demo.test", "technician")
    await _grant(bff, "demoted@demo.test", "requester")
    # Their console session ends at the next /me (made before the change), audited ...
    ended_me = await bff.me()
    assert ended_me.status_code == 401
    # ... the cookie goes with it, so the portal's sign-in passes through on Keycloak's session
    # instead of taking the ended one for a timed-out session and asking for the password.
    assert bff.cookie() is None
    portal = await bff.client.get("/api/v1/auth/login", params={"app": "portal"})
    assert "prompt=login" not in portal.headers["location"]
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        ended = await conn.fetch(
            "SELECT a.details FROM audit_entries a JOIN users u ON a.object_id = u.id::text"
            " WHERE u.email = 'demoted@demo.test' AND a.action = 'session.signed_out'"
        )
    finally:
        await conn.close()
    assert [json.loads(r["details"])["reason"] for r in ended] == ["console_requester_only"]
    # ... and signing in again on the console takes them to the portal.
    sent = await bff.login(demoted, return_to="/incidents")
    assert (sent.status_code, sent.headers["location"]) == (303, f"{PORTAL}/")


async def test_me_describes_the_session_without_tokens(bff: Bff) -> None:
    # Requesters sign in on the portal (on the console they are sent there: WP-028).
    await bff.login(bff.user("a", locale="ar", roles=("requester",)), app="portal")
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


async def test_just_in_time_provisioning_creates_then_only_records_sign_ins(bff: Bff) -> None:
    """D-092: Keycloak's profile makes the person once; after that SupportX owns the record."""
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
    # The name and language edited in SupportX are never overwritten by a sign-in, and the
    # version stays: an edit form open elsewhere does not turn stale (WP-010).
    assert (second["display_name"], second["locale"], second["version"]) == ("First Name", "en", 1)
    assert second["last_login_at"] > first["last_login_at"]


async def _precreate(bff: Bff, email: str, *, can_sign_in: bool = True) -> uuid.UUID:
    """A person added by an admin or an import: no Keycloak subject yet (WP-021)."""
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        found: uuid.UUID = await conn.fetchval(
            "INSERT INTO users (id, tenant_id, external_subject, email, display_name, first_name,"
            " user_type, can_sign_in, roles_mapped_at) VALUES (gen_random_uuid(), $1, NULL, $2,"
            " 'Pre Made', 'Pre', 'requester', $3, now()) RETURNING id",
            bff.tenants[0],
            email,
            can_sign_in,
        )
    finally:
        await conn.close()
    return found


async def test_first_sign_in_links_a_person_added_by_an_admin(bff: Bff) -> None:
    """D-092: matched by email (any case), linked once; their record and roles are kept."""
    person = await _precreate(bff, "added@demo.test")
    # Added as a requester: they sign in on the portal (the console sends them there, WP-028).
    response = await bff.login(
        bff.user("a", email="Added@Demo.test", name="Keycloak Name"), app="portal"
    )
    assert response.status_code == 302, response.text
    (row,) = await user_rows(bff.db, "added@demo.test")
    assert (row["display_name"], row["user_type"], row["version"]) == (
        "Pre Made",
        "requester",
        1,
    )
    assert {r["id"] for r in await _user_ids(bff, "added@demo.test")} == {person}
    events = await events_of(bff, "added@demo.test")
    # No role mapping: an admin-added person's roles are set in SupportX (roles_mapped_at).
    assert types(events) == ["user.updated", "user.logged_in"]
    assert events[0]["payload"]["changed_fields"] == ["sign_in_linked"]


async def test_a_contact_whose_sign_in_is_off_is_refused(bff: Bff) -> None:
    await _precreate(bff, "contact@demo.test", can_sign_in=False)
    response = await bff.login(bff.user("a", email="contact@demo.test"))
    assert (response.status_code, response.json()["code"]) == (403, "sign_in_not_allowed")
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        subject = await conn.fetchval(
            "SELECT external_subject FROM users WHERE email = 'contact@demo.test'"
        )
    finally:
        await conn.close()
    assert subject is None  # the refused sign-in linked nothing (rolled back)


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


# --- login CSRF: the sign-in is bound to the browser that started it (audit row 4) -----------


def login_cookies(bff: Bff) -> dict[str, str]:
    return {k: v for k, v in bff.client.cookies.items() if k.startswith(DEV_LOGIN_COOKIE_PREFIX)}


async def started_elsewhere(bff: Bff, user: FakeUser) -> tuple[str, str, dict[str, str]]:
    """An attacker's sign-in, stopped at Keycloak: code, state and the attacker's own cookies."""
    attacker = AsyncClient(transport=bff.client._transport, base_url=CONSOLE)  # noqa: SLF001 - same app
    async with attacker:
        start = await attacker.get("/api/v1/auth/login")
        assert start.status_code == 302, start.text
        code, state = bff.idp.issue_code(start.headers["location"], user)
        return code, state, dict(attacker.cookies.items())


async def test_login_sets_a_binding_cookie_per_sign_in(bff: Bff) -> None:
    start = await bff.client.get("/api/v1/auth/login")
    _code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    name = login_cookie_name(bff.settings, state)
    (set_cookie,) = start.headers.get_list("set-cookie")
    assert set_cookie.startswith(f"{name}=")
    for flag in ("HttpOnly", "Path=/", "SameSite=lax", "Max-Age=600"):
        assert flag in set_cookie
    token = bff.client.cookies[name]
    # Only the hash is kept server-side: the token itself appears in no stored login state.
    pending = await bff.app.state.auth.store.take_login(state)
    assert pending["binding"] == binding_digest(token)
    assert token not in json.dumps(pending)
    # A second tab gets its own cookie; the first one's is untouched.
    await bff.client.get("/api/v1/auth/login")
    assert len(login_cookies(bff)) == 2


def test_production_binding_cookie_is_host_prefixed() -> None:
    # model_copy skips validation: production needs real secrets this test never reads.
    production = make_settings(profile="test").model_copy(update={"profile": "production"})
    assert login_cookie_name(production, "s").startswith("__Host-supportx_login_")
    assert login_cookie_name(make_settings(profile="test"), "s").startswith(DEV_LOGIN_COOKIE_PREFIX)
    assert login_cookie_name(production, "s") != login_cookie_name(production, "t")


async def test_callback_without_the_binding_cookie_is_refused(bff: Bff) -> None:
    start = await bff.client.get("/api/v1/auth/login")
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    bff.client.cookies.clear()
    refused = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert (refused.status_code, refused.json()["code"]) == (400, "login_not_this_browser")
    assert bff.cookie() is None


async def test_attackers_callback_link_cannot_sign_in_another_browser(bff: Bff) -> None:
    """The login CSRF of audit row 4: the victim's browser opens the attacker's callback link."""
    victim = bff.user("a", email="victim@demo.test", subject="sub-victim")
    await bff.login(victim)
    victim_session = bff.cookie()
    assert victim_session is not None
    code, state, attacker_cookies = await started_elsewhere(
        bff, bff.user("a", email="attacker@demo.test", subject="sub-attacker")
    )
    assert login_cookie_name(bff.settings, state) in attacker_cookies
    html = {"Accept": "text/html"}
    refused = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers=html
    )
    assert refused.status_code == 303
    assert refused.headers["location"] == f"{CONSOLE}/?auth_error=login_not_this_browser"
    # Still the victim, still signed in: the rotation never ran.
    assert bff.cookie() == victim_session
    assert (await bff.me()).json()["user"]["email"] == "victim@demo.test"


async def test_another_browsers_binding_cookie_is_refused(bff: Bff) -> None:
    """A cookie of the right name with another browser's token: the hash does not match."""
    code, state, _attacker = await started_elsewhere(bff, bff.user("a"))
    mine = await bff.client.get("/api/v1/auth/login")
    assert mine.status_code == 302
    (my_token,) = login_cookies(bff).values()
    bff.client.cookies.set(login_cookie_name(bff.settings, state), my_token, domain="console.test")
    refused = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert (refused.status_code, refused.json()["code"]) == (400, "login_not_this_browser")
    # The state is spent: the attacker cannot try again with it either.
    again = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert again.json()["code"] == "invalid_login_state"


async def test_binding_cookie_is_cleared_after_the_callback(bff: Bff) -> None:
    assert (await bff.login(bff.user("a"))).status_code == 302
    assert login_cookies(bff) == {}
    assert bff.cookie() is not None
    # And on a failure too.
    start = await bff.client.get("/api/v1/auth/login")
    _code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    assert len(login_cookies(bff)) == 1
    denied = await bff.client.get(
        "/api/v1/auth/callback", params={"error": "access_denied", "state": state}
    )
    assert denied.json()["code"] == "login_failed"
    cleared = denied.headers["set-cookie"]
    assert cleared.startswith(f"{login_cookie_name(bff.settings, state)}=")
    assert "Max-Age=0" in cleared
    assert login_cookies(bff) == {}


async def test_two_tabs_signing_in_at_once_both_finish(bff: Bff) -> None:
    first = await bff.client.get("/api/v1/auth/login", params={"returnTo": "/one"})
    second = await bff.client.get("/api/v1/auth/login", params={"returnTo": "/two"})
    code1, state1 = bff.idp.issue_code(first.headers["location"], bff.user("a"))
    code2, state2 = bff.idp.issue_code(second.headers["location"], bff.user("a"))
    done1 = await bff.client.get("/api/v1/auth/callback", params={"code": code1, "state": state1})
    assert done1.headers["location"] == f"{CONSOLE}/one"
    done2 = await bff.client.get("/api/v1/auth/callback", params={"code": code2, "state": state2})
    assert done2.headers["location"] == f"{CONSOLE}/two"


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
    # The tenant's console limit (Appendix A default when never set: 60 minutes, REQ-SEC-029).
    await bff.login(bff.user("a"))
    bff.clock.advance(timedelta(seconds=CONSOLE_LIMITS["idle"] - 60))
    assert (await bff.me()).status_code == 200
    bff.clock.advance(timedelta(seconds=CONSOLE_LIMITS["idle"]))
    response = await bff.me()
    assert (response.status_code, response.json()["code"]) == (401, "session_expired")
    assert not [k for k in bff.kv.data if k.startswith("sx:session:")]


async def test_absolute_timeout_ends_even_an_active_session(bff: Bff) -> None:
    bff.idp.access_lifetime = 3 * 3600  # avoid refreshes; this test is about the absolute limit
    await bff.login(bff.user("a"))
    for _ in range(CONSOLE_LIMITS["absolute"] // 1200 - 1):
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
    # Only this test's tenants: the seeded demo tenants (made by other tests sharing the
    # database) have a person with this address too, so the whole table varies by worker.
    rows = await user_rows(bff.db, "multi@demo.test")
    assert {str(r["tenant_id"]) for r in rows} & {str(a), str(b)} == {str(a), str(b)}


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
        # This test's tenants only: other tests in the process reuse the same e-mail addresses.
        return await conn.fetch(
            "SELECT id FROM users WHERE email = $1 AND tenant_id = ANY($2::uuid[])",
            email,
            list(bff.tenants),
        )
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


async def test_a_changed_keycloak_profile_changes_nothing_after_the_first_sign_in(bff: Bff) -> None:
    """D-092: only the sign-in is recorded; no user.updated from Keycloak's profile."""
    await bff.login(bff.user("a", email="upd@demo.test", name="Before"))
    bff.clock.advance(timedelta(minutes=1))
    await bff.login(bff.user("a", email="upd@demo.test", name="After", locale="ar"))
    events = await events_of(bff, "upd@demo.test")
    assert types(events) == [
        "user.provisioned",
        "user.logged_in",
        "user_role.changed",  # the one-time role mapping (D-029); never again
        "user.logged_in",
    ]
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
    assert (await bff.login(requester, app="portal")).status_code == 302


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

    await bff.login(bff.user("a", email="perm-req@demo.test", roles=("requester",)), app="portal")
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
        # With no SupportX role left they are not let into the console (D-129): the portal.
        again = bff.user("a", email="once@demo.test", roles=("technician", "tenant_admin"))
        assert (await bff.login(again)).status_code == 303
        await bff.login(again, app="portal")
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


async def test_req_aud_002_sign_in_sign_out_and_switch_are_audited(bff: Bff) -> None:
    """WP-018: each session event writes one audit entry in the session's tenant."""
    a, b = bff.tenants
    await bff.login(bff.user("a", "b", email="audited@demo.test"))
    switched = await bff.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(b)},
        headers={"X-CSRF-Token": await bff.csrf()},
    )
    assert switched.status_code == 200
    logout = await bff.client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": await bff.csrf()}
    )
    assert logout.status_code == 204
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        rows = await conn.fetch(
            "SELECT e.tenant_id, e.action, e.client, e.actor_id = u.id AS by_self"
            " FROM audit_entries e JOIN users u ON u.id = e.actor_id"
            " WHERE u.email = $1 ORDER BY e.occurred_at",
            "audited@demo.test",
        )
    finally:
        await conn.close()
    assert [(r["tenant_id"], r["action"]) for r in rows] == [
        (a, "session.signed_in"),
        (b, "session.tenant_switched"),
        (b, "session.signed_out"),
    ]
    assert all(r["by_self"] and r["client"] == "console" for r in rows)


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


# --- a tenant's own address (WP-017, REQ-SEC-004) ------------------------------------------------


async def _on_address(bff: Bff, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Tenant A reached on its subdomain `<slug>.brand.test`; returns (slug, host)."""
    settings = bff.app.state.settings.model_copy(update={"tenant_base_domain": "brand.test"})
    set_state(monkeypatch, bff.app.state, "settings", settings)
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        slug = str(await conn.fetchval("SELECT slug FROM tenants WHERE id = $1", bff.tenants[0]))
    finally:
        await conn.close()
    return slug, f"{slug}.brand.test"


async def test_the_address_picks_the_organization_and_keeps_the_callback_on_it(
    bff: Bff, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug, host = await _on_address(bff, monkeypatch)
    start = await bff.client.get("/api/v1/auth/login", headers={"Host": host})
    location = start.headers["location"]
    assert f"organization%3A{slug}" in location  # AC1: straight to that tenant's sign-in
    assert "organization%3A%2A" not in location
    # Keycloak organization aliases are the tenant slugs (the dev realm: demo, other).
    user = replace(
        bff.user("b", email="multi@demo.test"),
        organizations={
            slug: bff.tenants[0],
            "b": bff.tenants[1],
        },
    )
    code, state = bff.idp.issue_code(location, user)
    assert bff.idp.last_redirect_uri == f"http://{host}/api/v1/auth/callback"
    done = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers={"Host": host}
    )
    assert done.status_code == 302, done.text
    assert done.headers["location"].startswith(f"http://{host}/")
    me = await bff.client.get("/api/v1/auth/me", headers={"Host": host})
    body = me.json()
    assert body["tenant"]["id"] == str(bff.tenants[0])
    assert [t["id"] for t in body["tenants"]] == [str(bff.tenants[0])]  # only this address's
    # A write from the address's own origin passes the Origin check; another origin does not.
    token = body["csrf_token"]
    own = await bff.client.post(
        "/api/v1/probe",
        json={"title": "x"},
        headers={"Host": host, "X-CSRF-Token": token, "Origin": f"http://{host}"},
    )
    assert own.status_code == 200, own.text
    other = await bff.client.post(
        "/api/v1/probe",
        json={"title": "x"},
        headers={"Host": host, "X-CSRF-Token": token, "Origin": "http://other.brand.test"},
    )
    assert (other.status_code, other.json()["code"]) == (403, "csrf_failed")


async def test_a_member_of_another_tenant_gets_no_access_through_this_address(
    bff: Bff, monkeypatch: pytest.MonkeyPatch
) -> None:
    _slug, host = await _on_address(bff, monkeypatch)
    start = await bff.client.get("/api/v1/auth/login", headers={"Host": host})
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("b"))  # B only
    done = await bff.client.get(
        "/api/v1/auth/callback", params={"code": code, "state": state}, headers={"Host": host}
    )
    assert (done.status_code, done.json()["code"]) == (403, "no_organization")  # AC2
    assert bff.cookie() is None


async def test_a_login_cannot_finish_on_another_address(
    bff: Bff, monkeypatch: pytest.MonkeyPatch
) -> None:
    _slug, host = await _on_address(bff, monkeypatch)
    start = await bff.client.get("/api/v1/auth/login", headers={"Host": host})
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("a"))
    done = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert (done.status_code, done.json()["code"]) == (400, "login_failed")


async def test_an_unknown_address_signs_in_as_before(
    bff: Bff, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _on_address(bff, monkeypatch)
    start = await bff.client.get("/api/v1/auth/login", headers={"Host": "nobody.brand.test"})
    assert "organization%3A%2A" in start.headers["location"]
    assert "redirect_uri=http%3A%2F%2Fconsole.test" in start.headers["location"]


async def test_a_refused_browser_login_returns_to_the_address_it_started_on(
    bff: Bff, monkeypatch: pytest.MonkeyPatch
) -> None:
    _slug, host = await _on_address(bff, monkeypatch)
    start = await bff.client.get("/api/v1/auth/login", headers={"Host": host})
    code, state = bff.idp.issue_code(start.headers["location"], bff.user("b"))
    done = await bff.client.get(
        "/api/v1/auth/callback",
        params={"code": code, "state": state},
        headers={"Host": host, "Accept": "text/html"},
    )
    assert done.status_code == 303
    assert done.headers["location"] == f"http://{host}/?auth_error=no_organization"


# --- WP-039: sessions per tenant, ending sessions, the SSO test sign-in ---------------------------


async def _tenant_sql(bff: Bff, sql: str, *args: object) -> None:
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


async def test_sessions_take_their_tenants_limits(bff: Bff) -> None:
    """REQ-SEC-029: a tenant's idle timeout applies to sessions begun after it was set."""
    a, _ = bff.tenants
    await _tenant_sql(
        bff, "INSERT INTO identity_settings (tenant_id, console_idle_seconds) VALUES ($1, 600)", a
    )
    await bff.login(bff.user("a"))
    bff.clock.advance(timedelta(seconds=540))
    assert (await bff.me()).status_code == 200
    bff.clock.advance(timedelta(seconds=600))
    assert (await bff.me()).json()["code"] == "session_expired"


async def test_after_a_timeout_signing_in_asks_for_the_password_again(bff: Bff) -> None:
    """Keycloak's longer session never signs a timed-out browser back in silently."""
    fresh = await bff.client.get("/api/v1/auth/login")
    assert "prompt=login" not in fresh.headers["location"]
    await bff.login(bff.user("a"))
    bff.clock.advance(timedelta(seconds=CONSOLE_LIMITS["idle"]))
    assert (await bff.me()).status_code == 401
    again = await bff.client.get("/api/v1/auth/login")
    assert "prompt=login" in again.headers["location"]


async def test_ending_a_persons_sessions_closes_their_live_connections(bff: Bff) -> None:
    """REQ-SEC-031 AC1: deactivation ends sessions and the live connection at once."""
    await bff.login(bff.user("a"))
    me = (await bff.me()).json()
    closed: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def record(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        closed.append((tenant_id, user_id))

    auth: AuthService = bff.app.state.auth
    auth.end_realtime = record
    tenant, user = uuid.UUID(me["tenant"]["id"]), uuid.UUID(me["user"]["id"])
    await auth.end_sessions(tenant, user)
    assert closed == [(tenant, user)]
    assert (await bff.me()).status_code == 401


async def _sso_world(bff: Bff) -> tuple[uuid.UUID, uuid.UUID, Any]:
    from tests.db.test_identity_api import FakeAdmin  # noqa: PLC0415 - shared fake

    a, _ = bff.tenants
    provider = uuid.uuid4()
    await _tenant_sql(
        bff,
        "INSERT INTO sso_providers (id, tenant_id, alias, protocol, preset, display_name)"
        " VALUES ($1, $2, 'sx-a-test', 'oidc', 'entra', 'Acme')",
        provider,
        a,
    )
    admin = FakeAdmin()
    auth: AuthService = bff.app.state.auth
    auth.identity_admin = admin
    return a, provider, admin


async def _start_test(
    auth: AuthService, tenant: uuid.UUID, provider: uuid.UUID
) -> sso_test.TestStarted:
    return await sso_test.start(
        auth,
        tenant_id=tenant,
        slug="a",
        admin_user_id=uuid.uuid4(),
        provider_id=provider,
        alias="sx-a-test",
    )


async def test_the_sso_test_sign_in_creates_no_session_and_marks_the_set_up_tested(
    bff: Bff,
) -> None:
    """REQ-SEC-007/008: test before switching on; the test is not a sign-in."""
    a, provider, admin = await _sso_world(bff)
    tester = bff.user("a", email="alice@acme.test", subject="sub-alice")
    admin.attributes["sub-alice"] = {"sx_department": ["Finance"]}
    auth: AuthService = bff.app.state.auth
    started = await sso_test.start(
        auth,
        tenant_id=a,
        slug="a",
        admin_user_id=uuid.uuid4(),
        provider_id=provider,
        alias="sx-a-test",
    )
    assert "kc_idp_hint=sx-a-test" in started.url
    assert "prompt=login" in started.url
    code, state = bff.idp.issue_code(started.url, tester)
    done = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert done.status_code == 303
    assert done.headers["location"] == f"{CONSOLE}/sso-test-done"
    assert bff.cookie() is None  # no SupportX session
    assert bff.idp.ended_sessions  # the tested Keycloak session ended at once
    assert await user_rows(bff.db, "alice@acme.test") == []  # nobody created
    found = await sso_test.result(auth, started.test_id, tenant_id=a, provider_id=provider)
    assert found["status"] == "passed"
    assert found["identity"]["email"] == "alice@acme.test"
    assert found["identity"]["department"] == "Finance"
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        row = await conn.fetchrow(
            "SELECT state, tested_at FROM sso_providers WHERE id = $1", provider
        )
        audit = await conn.fetchval(
            "SELECT details->>'passed' FROM audit_entries WHERE action = 'sso.tested'"
        )
    finally:
        await conn.close()
    assert row is not None
    assert (row["state"], row["tested_at"] is not None) == ("tested", True)
    assert audit == "true"
    # Only the tenant and set-up it was started for may read it.
    with pytest.raises(NotFound):
        await sso_test.result(auth, started.test_id, tenant_id=bff.tenants[1], provider_id=provider)


async def test_a_failed_sso_test_says_why_and_leaves_the_set_up_untested(bff: Bff) -> None:
    """REQ-SEC-007 AC1: a plain reason; the set-up stays off."""
    a, provider, admin = await _sso_world(bff)
    auth: AuthService = bff.app.state.auth
    # Signed in at the provider, but their email is in none of the tenant's domains.
    outsider = bff.user(email="mallory@elsewhere.test", subject="sub-mallory")
    started = await sso_test.start(
        auth,
        tenant_id=a,
        slug="a",
        admin_user_id=uuid.uuid4(),
        provider_id=provider,
        alias="sx-a-test",
    )
    code, state = bff.idp.issue_code(started.url, outsider)
    await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    found = await sso_test.result(auth, started.test_id, tenant_id=a, provider_id=provider)
    assert (found["status"], found["reason"]) == ("failed", "not_in_tenant_domains")
    # The provider's answer was refused by Keycloak (its own error page): the login error event.
    second = await sso_test.start(
        auth,
        tenant_id=a,
        slug="a",
        admin_user_id=uuid.uuid4(),
        provider_id=provider,
        alias="sx-a-test",
    )
    assert (await sso_test.result(auth, second.test_id, tenant_id=a, provider_id=provider))[
        "status"
    ] == "pending"
    admin.events.append(
        LoginEvent(
            "IDENTITY_PROVIDER_LOGIN_ERROR",
            int(bff.clock.now().timestamp() * 1000) + 1,
            "identity_provider_login_failure",
            None,
            None,
        )
    )
    failed = await sso_test.result(auth, second.test_id, tenant_id=a, provider_id=provider)
    assert (failed["status"], failed["reason"]) == ("failed", "answer_not_verified")
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        state = await conn.fetchval("SELECT state FROM sso_providers WHERE id = $1", provider)
    finally:
        await conn.close()
    assert state == "draft"


# --- the sign-in key ring (D-162, ADR-048) ------------------------------------------------------


async def test_a_session_survives_a_key_rotation_and_moves_to_the_new_key(bff: Bff) -> None:
    """Nobody is signed out: the old key stays readable, the next save seals under the new one."""
    assert (await bff.login(bff.user("a", email="rotate@demo.test"))).status_code == 302
    session_key = next(k for k in bff.kv.data if k.startswith("sx:session:"))
    assert key_id_of(bff.kv.data[session_key]) == "legacy"
    # The operator lists a new newest key and keeps "legacy" for the overlap; the API restarts.
    rotated = make_settings(
        session_secret=bff.settings.session_secret.get_secret_value(),  # type: ignore[union-attr]  # set by the fixture
        session_keys=json.dumps([{"id": "k2", "secret": "n" * 40}, {"id": "legacy"}]),
    )
    cipher = SessionCipher.from_settings(rotated)
    assert cipher is not None
    bff.app.state.auth.store = SessionStore(bff.kv, cipher)
    me = await bff.me()
    assert me.status_code == 200, me.text
    bff.clock.advance(timedelta(minutes=2))  # past the touch interval: the record is saved again
    assert (await bff.me()).status_code == 200
    assert key_id_of(bff.kv.data[session_key]) == "k2"
    # Once "legacy" is retired, the moved session still works.
    retired = SessionCipher.from_settings(
        make_settings(session_keys=json.dumps([{"id": "k2", "secret": "n" * 40}]))
    )
    assert retired is not None
    bff.app.state.auth.store = SessionStore(bff.kv, retired)
    assert (await bff.me()).status_code == 200
