"""Integration: BFF login against the REAL Keycloak of the dev stack (realm import in
deploy/compose/keycloak). Needs `make dev-up`; skipped automatically otherwise. CI runs these in the
stack-smoke workflow, where the stack is up.

The API runs in-process with a throwaway, migrated database; Keycloak, Valkey and PgBouncer are the
dev stack's own. The OIDC redirect URI is http://localhost:5173/api/v1/auth/callback, as registered
for the console client.
"""

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import asyncpg
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from conftest import PRODUCTION_REQUIRED, make_settings
from tests.db.test_api_tenancy import build_app
from tests.integration.keycloak_browser import KeycloakBrowser
from tests.integration.test_ready_dev_stack import port_open, read_stack_env
from tooling import seed_dev
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.integration

CONSOLE = "http://localhost:5173"
DEMO, OTHER = seed_dev.DEMO_TENANT_ID, seed_dev.OTHER_TENANT_ID
PASSWORDS = {
    "admin@demo.test": "Admin-Demo-2026!",
    "tech@demo.test": "Tech-Demo-2026!",
    "user@demo.test": "User-Demo-2026!",
    "other@other.test": "Other-Corp-2026!",
    "multi@demo.test": "Multi-Org-2026!",
    "nobody@nowhere.test": "No-Org-User-2026!",
}


@pytest.fixture(scope="module")
def stack() -> dict[str, str]:
    env = read_stack_env()
    if env is None or not all(
        port_open(int(env[k])) for k in ("KEYCLOAK_PORT", "VALKEY_PORT", "PGBOUNCER_PORT")
    ):
        pytest.skip("dev stack not running (make dev-up)")
    assert env is not None
    return env


@pytest.fixture(scope="module")
def seeded(stack: dict[str, str], migrated_db: ThrowawayDatabase) -> ThrowawayDatabase:
    del stack  # requested only so a missing dev stack skips before seeding
    asyncio.run(seed_dev.seed(migrated_db.migrator_url))
    return migrated_db


@dataclass
class Session:
    client: AsyncClient
    browser: KeycloakBrowser

    async def login(self, email: str, *, app: str = "console") -> httpx.Response:
        start = await self.client.get(
            "/api/v1/auth/login", params={"app": app, "returnTo": "/home"}
        )
        assert start.status_code == 302, start.text
        landing = self.browser.login(start.headers["location"], email, PASSWORDS[email])
        assert landing.status_code == 302, f"Keycloak did not redirect back for {email}"
        return await self.client.get(landing.headers["location"])

    async def me(self) -> httpx.Response:
        return await self.client.get("/api/v1/auth/me")


@pytest_asyncio.fixture
async def session(stack: dict[str, str], seeded: ThrowawayDatabase) -> AsyncIterator[Session]:
    settings = make_settings(
        profile="test",
        database_url=seeded.app_url,
        valkey_url=f"valkey://:{stack['VALKEY_PASSWORD']}@127.0.0.1:{stack['VALKEY_PORT']}/0",
        oidc_issuer=f"http://localhost:{stack['KEYCLOAK_PORT']}/realms/supportx",
        oidc_console_client_secret=stack["KEYCLOAK_CONSOLE_CLIENT_SECRET"],
        oidc_portal_client_secret=stack["KEYCLOAK_PORTAL_CLIENT_SECRET"],
        session_secret=secrets.token_hex(32),
        session_cookie_secure=False,
        dev_tenant_header=True,  # proves the session still wins over the header
    )
    app = build_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url=CONSOLE) as client:
            browser = KeycloakBrowser()
            try:
                yield Session(client, browser)
            finally:
                browser.close()


async def users_in(db: ThrowawayDatabase, email: str, tenant: uuid.UUID) -> list[asyncpg.Record]:
    # Other test files share this database and may use the same emails in other tenants.
    conn = await asyncpg.connect(db.admin_url)
    try:
        return await conn.fetch(
            "SELECT tenant_id, display_name, locale, user_type FROM users "
            "WHERE email = $1 AND tenant_id = $2",
            email,
            tenant,
        )
    finally:
        await conn.close()


@pytest.mark.parametrize(
    ("email", "tenant", "user_type", "locale", "name"),
    [
        ("admin@demo.test", "Demo Company", "technician", "en", "Amal Admin"),
        ("tech@demo.test", "Demo Company", "technician", "en", "Tariq Technician"),
        ("user@demo.test", "Demo Company", "requester", "ar", "Yusra Requester"),
        ("other@other.test", "Other Company", "technician", "en", "Omar Other"),
    ],
)
async def test_each_test_user_logs_in_and_is_provisioned(
    session: Session,
    seeded: ThrowawayDatabase,
    email: str,
    tenant: str,
    user_type: str,
    locale: str,
    name: str,
) -> None:
    callback = await session.login(email)
    assert callback.status_code == 302
    assert callback.headers["location"] == f"{CONSOLE}/home"
    me = (await session.me()).json()
    assert me["tenant"]["name"] == tenant
    assert me["user"]["display_name"] == name
    assert me["user"]["user_type"] == user_type
    assert me["user"]["locale"] == locale
    (row,) = await users_in(seeded, email, DEMO if tenant == "Demo Company" else OTHER)
    assert (row["display_name"], row["locale"], row["user_type"]) == (name, locale, user_type)


async def test_admin_role_is_carried_into_the_session(session: Session) -> None:
    await session.login("admin@demo.test")
    assert set((await session.me()).json()["user"]["roles"]) == {"tenant_admin", "technician"}


async def test_logout_ends_the_bff_and_keycloak_sessions(session: Session) -> None:
    await session.login("tech@demo.test")
    # While logged in, Keycloak has an SSO session: a new authorization skips the login form.
    sso = session.browser.open((await session.client.get("/api/v1/auth/login")).headers["location"])
    assert sso.status_code == 302
    await session.login("tech@demo.test")
    token = (await session.me()).json()["csrf_token"]
    assert (
        await session.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
    ).status_code == 204
    assert (await session.me()).status_code == 401
    after = session.browser.open(
        (await session.client.get("/api/v1/auth/login")).headers["location"]
    )
    assert KeycloakBrowser.shows_login_form(after), "Keycloak session survived the logout"


async def test_other_company_user_never_sees_demo_company(session: Session) -> None:
    await session.login("other@other.test")
    me = (await session.me()).json()
    assert [t["name"] for t in me["tenants"]] == ["Other Company"]
    for headers in ({}, {"X-Tenant-ID": str(DEMO)}):
        tenant = (await session.client.get("/api/v1/organization/tenant", headers=headers)).json()
        assert tenant["id"] == str(OTHER), headers
    titles = (await session.client.get("/api/v1/probe", headers={"X-Tenant-ID": str(DEMO)})).json()
    assert titles == [] or all("demo" not in t for t in titles)
    switch = await session.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(DEMO)},
        headers={"X-CSRF-Token": me["csrf_token"]},
    )
    assert (switch.status_code, switch.json()["code"]) == (403, "not_a_member")


async def test_demo_data_stays_invisible_to_other_company(session: Session) -> None:
    await session.login("tech@demo.test")
    token = (await session.me()).json()["csrf_token"]
    secret_title = f"demo-secret-{uuid.uuid4().hex[:8]}"
    created = await session.client.post(
        "/api/v1/probe", json={"title": secret_title}, headers={"X-CSRF-Token": token}
    )
    assert created.status_code == 200
    await session.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})

    await session.login("other@other.test")
    listed = await session.client.get("/api/v1/probe", headers={"X-Tenant-ID": str(DEMO)})
    assert secret_title not in listed.text
    patched = await session.client.patch(
        f"/api/v1/probe/{created.json()['id']}?version=1",
        json={"title": "hijacked"},
        headers={"X-CSRF-Token": (await session.me()).json()["csrf_token"]},
    )
    assert patched.status_code == 404


async def test_user_without_organization_gets_403(session: Session) -> None:
    response = await session.login("nobody@nowhere.test")
    assert response.status_code == 403
    assert response.json()["code"] == "no_organization"
    assert (await session.me()).status_code == 401
    retry = session.browser.open(
        (await session.client.get("/api/v1/auth/login")).headers["location"]
    )
    assert KeycloakBrowser.shows_login_form(retry), "Keycloak session should have been ended"


async def test_multi_organization_user_can_switch(session: Session) -> None:
    await session.login("multi@demo.test")
    me = (await session.me()).json()
    assert {t["name"] for t in me["tenants"]} == {"Demo Company", "Other Company"}
    target = next(t for t in me["tenants"] if t["id"] != me["tenant"]["id"])
    switched = await session.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": target["id"]},
        headers={"X-CSRF-Token": me["csrf_token"]},
    )
    assert switched.json()["tenant"]["id"] == target["id"]
    assert (await session.client.get("/api/v1/organization/tenant")).json()["id"] == target["id"]


async def test_production_ignores_x_tenant_id_against_the_real_stack(
    stack: dict[str, str], seeded: ThrowawayDatabase
) -> None:
    settings = make_settings(
        **{
            **PRODUCTION_REQUIRED,
            "database_url": seeded.app_url,
            "valkey_url": f"valkey://:{stack['VALKEY_PASSWORD']}@127.0.0.1:{stack['VALKEY_PORT']}/0",
            "oidc_issuer": f"http://localhost:{stack['KEYCLOAK_PORT']}/realms/supportx",
            "dev_tenant_header": True,
        }
    )
    app = build_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url=CONSOLE) as client,
    ):
        response = await client.get(
            "/api/v1/organization/tenant", headers={"X-Tenant-ID": str(DEMO)}
        )
    assert (response.status_code, response.json()["code"]) == (401, "unauthenticated")


def _admin(stack: dict[str, str]) -> httpx.Client:
    base = f"http://localhost:{stack['KEYCLOAK_PORT']}"
    token = httpx.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": stack["KEYCLOAK_ADMIN_USER"],
            "password": stack["KEYCLOAK_ADMIN_PASSWORD"],
        },
    ).json()["access_token"]
    return httpx.Client(
        base_url=f"{base}/admin/realms/supportx", headers={"Authorization": f"Bearer {token}"}
    )


def test_realm_enforces_password_policy_and_brute_force_protection(stack: dict[str, str]) -> None:
    with _admin(stack) as admin:
        realm = admin.get("").json()
        assert realm["bruteForceProtected"] is True
        assert realm["failureFactor"] == 5
        assert "length(12)" in realm["passwordPolicy"]
        assert realm["organizationsEnabled"] is True
        # A throwaway user: a weak password is refused, then 5 wrong passwords lock the account.
        email = f"policy-{uuid.uuid4().hex[:8]}@nowhere.test"
        created = admin.post("/users", json={"username": email, "email": email, "enabled": True})
        user_id = created.headers["location"].rsplit("/", 1)[1]
        try:
            weak = admin.put(
                f"/users/{user_id}/reset-password",
                json={"type": "password", "value": "short", "temporary": False},
            )
            assert weak.status_code == 400
            strong = admin.put(
                f"/users/{user_id}/reset-password",
                json={"type": "password", "value": "Strong-Pass-2026!", "temporary": False},
            )
            assert strong.status_code == 204
            browser = KeycloakBrowser()
            authorize = (
                f"http://localhost:{stack['KEYCLOAK_PORT']}/realms/supportx/protocol/openid-connect/auth"
                "?client_id=supportx-console&response_type=code&scope=openid"
                "&redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fapi%2Fv1%2Fauth%2Fcallback"
                "&code_challenge=" + "x" * 43 + "&code_challenge_method=S256"
            )
            try:
                for _ in range(5):
                    browser.login(authorize, email, "Wrong-Pass-2026!")
                locked = admin.get(f"/attack-detection/brute-force/users/{user_id}").json()
                assert locked["disabled"] is True
                # Even the right password is refused while the lock lasts.
                assert browser.login(authorize, email, "Strong-Pass-2026!").status_code == 200
            finally:
                browser.close()
        finally:
            admin.delete(f"/users/{user_id}")
