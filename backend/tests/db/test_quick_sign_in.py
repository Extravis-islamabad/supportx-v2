"""Dev-only quick sign-in over HTTP (D-151): guards, the second step, refusals, audit, logout.

Keycloak is FakeIdp (its password grant checks the password and, for an enrolled persona, the TOTP
code); PostgreSQL is real. The ASGI transport's client is 127.0.0.1, so "local" is the Host header.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.core.config import Settings
from app.modules.identity_access.bff.cookies import cookie_name
from app.modules.identity_access.domain.quick_sign_in import time_step, totp, totp_value
from app.modules.identity_access.infra.crypto import SessionCipher
from app.modules.identity_access.infra.oidc import OidcClient
from app.modules.identity_access.infra.store import SessionStore
from app.modules.identity_access.service.auth import AuthService
from app.modules.identity_access.tests.fake_idp import ISSUER, FakeIdp, FakeUser, MemoryKeyValue
from app.shared.clock import FrozenClock
from conftest import create_tenant, make_settings
from tests.db.test_api_tenancy import build_app
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

LOCAL = "http://localhost:5173"
PASSWORD = "Showcase-Dev-2026!"
TOTP_KEY = "test-totp-key-" + "x" * 32
SIGN_IN = "/api/v1/auth/dev/sign-in"
PERSONAS = "/api/v1/auth/dev/personas"


@dataclass
class Quick:
    app: FastAPI
    idp: FakeIdp
    clock: FrozenClock
    showcase: uuid.UUID
    other: uuid.UUID
    db: ThrowawayDatabase

    def client(self, base: str = LOCAL) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=self.app), base_url=base)

    def enrol(
        self,
        email: str,
        *,
        tenant: uuid.UUID | None = None,
        roles: tuple[str, ...] = ("technician",),
    ) -> FakeUser:
        user = FakeUser(
            subject="sub-" + email,
            email=email,
            name=email.split("@", maxsplit=1)[0].title(),
            roles=roles,
            organizations={"showcase": tenant or self.showcase},
        )
        value = totp_value(TOTP_KEY.encode(), email)
        self.idp.passwords[email] = (user, PASSWORD, value)
        return user


def _settings(db: ThrowawayDatabase, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "profile": "dev",
        "database_url": db.app_url,
        "oidc_issuer": ISSUER,
        "oidc_console_client_secret": "console-secret",
        "oidc_portal_client_secret": "portal-secret",
        "valkey_url": "valkey://127.0.0.1:1/0",
        "session_secret": "x" * 40,
        "console_url": LOCAL,
        "portal_url": LOCAL + "/portal",
        "session_cookie_secure": False,
        "dev_quick_sign_in": True,
        "showcase_password": PASSWORD,
        "showcase_totp_key": TOTP_KEY,
    }
    return make_settings(**{**values, **overrides})


async def _start(settings: Settings) -> tuple[FastAPI, FakeIdp, FrozenClock]:
    app = build_app(settings)
    clock = FrozenClock(datetime.now(UTC).replace(microsecond=0))
    idp = FakeIdp(now=lambda: clock.now().timestamp())
    return app, idp, clock


@pytest_asyncio.fixture
async def quick(migrated_db: ThrowawayDatabase) -> AsyncIterator[Quick]:
    other = await create_tenant(migrated_db.migrator_url, "Other Company")
    conn = await asyncpg.connect(migrated_db.migrator_url)
    try:  # one showcase tenant per database (the slug is unique)
        found = await conn.fetchval("SELECT id FROM tenants WHERE slug = 'showcase'")
    finally:
        await conn.close()
    showcase = found or await create_tenant(migrated_db.migrator_url, "Showcase Company")
    if found is None:
        conn = await asyncpg.connect(migrated_db.migrator_url)
        try:
            await conn.execute("UPDATE tenants SET slug = 'showcase' WHERE id = $1", showcase)
        finally:
            await conn.close()
    settings = _settings(migrated_db)
    app, idp, clock = await _start(settings)
    async with app.router.lifespan_context(app):
        service = AuthService(
            settings=settings,
            store=SessionStore(MemoryKeyValue(), SessionCipher("x" * 40)),
            oidc=OidcClient(ISSUER, idp.client()),
            database=app.state.db,
            clock=clock,
            cookie_name=cookie_name(settings),
        )
        app.state.auth = service
        app.state.session_resolver = service.resolve
        yield Quick(app, idp, clock, showcase, other, migrated_db)


async def _sign_in(quick: Quick, client: AsyncClient, code: str) -> Response:
    del quick
    return await client.post(SIGN_IN, json={"persona": code}, headers={"Origin": LOCAL})


async def _audit(db: ThrowawayDatabase, tenant: uuid.UUID) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(db.admin_url)
    try:
        return await conn.fetch(
            "SELECT action, details FROM audit_entries WHERE tenant_id = $1"
            " AND action = 'session.quick_sign_in'",
            tenant,
        )
    finally:
        await conn.close()


async def test_a_persona_signs_in_through_keycloak_with_its_second_step(quick: Quick) -> None:
    quick.enrol("admin@showcase.test", roles=("tenant_admin", "technician"))
    async with quick.client() as client:
        listed = await client.get(PERSONAS)
        assert listed.status_code == 200
        assert {p["code"] for p in listed.json()} >= {
            "admin",
            "technician",
            "lead",
            "approver",
            "requester",
            "new_starter",
        }
        done = await _sign_in(quick, client, "admin")
        assert done.status_code == 200, done.text
        assert done.json()["redirect_to"].startswith(LOCAL)
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200, me.text
        assert me.json()["tenant"]["id"] == str(quick.showcase)
        # The second step: the code of this 30 s window, from the persona's dev-only secret.
        [grant] = quick.idp.password_grants
        value = totp_value(TOTP_KEY.encode(), "admin@showcase.test")
        assert grant["totp"] == totp(value, time_step(quick.clock.now()))
        assert grant["client_id"] == "supportx-console"
        # Logout works as for any session.
        csrf = me.json()["csrf_token"]
        out = await client.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf, "Origin": LOCAL}
        )
        assert out.status_code in {200, 204}, out.text
        assert (await client.get("/api/v1/auth/me")).status_code == 401
    entries = await _audit(quick.db, quick.showcase)
    assert any('"persona": "admin"' in e["details"] for e in entries)


async def test_a_code_is_never_sent_twice_and_the_third_waits(quick: Quick) -> None:
    quick.enrol("tech@showcase.test")
    async with quick.client() as client:
        assert (await _sign_in(quick, client, "technician")).status_code == 200
        assert (await _sign_in(quick, client, "technician")).status_code == 200
        codes = [g["totp"] for g in quick.idp.password_grants]
        assert len(set(codes)) == 2  # the next step's code the second time
        third = await _sign_in(quick, client, "technician")
        assert third.status_code == 409
        assert third.json()["code"] == "quick_sign_in_wait"
        assert len(quick.idp.password_grants) == 2  # never a guess toward the brute-force lock


async def test_keycloak_refusing_is_a_named_reason_never_a_500(quick: Quick) -> None:
    user = quick.enrol("lead@showcase.test")
    quick.idp.passwords["lead@showcase.test"] = (user, "not-the-seed-password", None)
    async with quick.client() as client:
        refused = await _sign_in(quick, client, "lead")
    assert refused.status_code == 403
    assert refused.json()["code"] == "quick_sign_in_refused"
    assert refused.json()["params"] == {"reason": "credentials_refused"}
    assert PASSWORD not in refused.text
    assert TOTP_KEY not in refused.text


async def test_only_the_showcase_tenant(quick: Quick) -> None:
    quick.enrol("approver@showcase.test", tenant=quick.other, roles=("requester",))
    async with quick.client() as client:
        refused = await _sign_in(quick, client, "approver")
    assert refused.status_code == 403
    assert refused.json()["params"] == {"reason": "not_showcase"}
    assert quick.idp.ended_sessions  # the Keycloak session it got is ended


async def test_the_new_starter_goes_to_the_real_sign_in(quick: Quick) -> None:
    async with quick.client() as client:
        done = await _sign_in(quick, client, "new_starter")
        assert done.status_code == 200
        assert "/protocol/openid-connect/auth" in done.json()["redirect_to"]
        assert (await client.get("/api/v1/auth/me")).status_code == 401  # no session made
    assert quick.idp.password_grants == []


@pytest.mark.parametrize(
    ("base", "headers"),
    [
        ("http://console.test", {"Origin": "http://console.test"}),  # not a localhost Host
        (LOCAL, {"Origin": LOCAL, "X-Forwarded-For": "203.0.113.9"}),  # forwarded from outside
        (LOCAL, {}),  # no Origin: another site's form could post here
        (LOCAL, {"Origin": "http://evil.example"}),
    ],
)
async def test_anything_not_local_finds_nothing(
    quick: Quick, base: str, headers: dict[str, str]
) -> None:
    quick.enrol("admin@showcase.test")
    async with quick.client(base) as client:
        answered = await client.post(SIGN_IN, json={"persona": "admin"}, headers=headers)
    assert answered.status_code == 404
    assert quick.idp.password_grants == []


async def test_switched_off_it_does_not_exist(migrated_db: ThrowawayDatabase) -> None:
    app = build_app(_settings(migrated_db, dev_quick_sign_in=False))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url=LOCAL) as client,
    ):
        assert (await client.get(PERSONAS)).status_code == 404
        assert (
            await client.post(SIGN_IN, json={"persona": "admin"}, headers={"Origin": LOCAL})
        ).status_code == 404
    paths = app.openapi()["paths"]
    assert not [p for p in paths if "/auth/dev" in p]
