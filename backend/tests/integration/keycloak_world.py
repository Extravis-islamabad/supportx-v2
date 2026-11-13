"""Shared parts of the BFF-against-a-real-Keycloak tests (from test_auth_keycloak.py, WP-057 S1).

The dev realm (deploy/helm/supportx/files/keycloak/dev) in this test process's own Keycloak
(keycloak_container.py), never the shared dev Keycloak; the API in-process with a throwaway,
migrated database and the tests' Valkey. The test files re-export the fixtures (`__all__`).
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

from conftest import make_settings
from tests.db.test_api_tenancy import build_app
from tests.db.test_rate_limit import valkey_url
from tests.integration.keycloak_browser import KeycloakBrowser
from tests.integration.keycloak_container import PrivateKeycloak
from tooling import seed_dev
from tooling.db_testing import ThrowawayDatabase

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
def valkey() -> str:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    return url


@pytest.fixture(scope="module")
def seeded(valkey: str, migrated_db: ThrowawayDatabase) -> ThrowawayDatabase:
    del valkey  # requested only so a missing Valkey skips before seeding
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
async def session(
    private_keycloak: PrivateKeycloak, valkey: str, seeded: ThrowawayDatabase
) -> AsyncIterator[Session]:
    settings = make_settings(
        profile="test",
        database_url=seeded.app_url,
        valkey_url=valkey,
        oidc_issuer=private_keycloak.issuer,
        oidc_console_client_secret=private_keycloak.console_secret,
        oidc_portal_client_secret=private_keycloak.portal_secret,
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
