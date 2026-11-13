"""Integration: one tenant's people never reach another's data, against a REAL Keycloak.

Split from test_auth_keycloak.py (WP-057 S1): the session's tenant wins over a header, data
stays inside its tenant, a person in two organizations switches, and production ignores
X-Tenant-ID.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import PRODUCTION_REQUIRED, make_settings
from tests.db.test_api_tenancy import build_app
from tests.integration.keycloak_container import PrivateKeycloak
from tests.integration.keycloak_world import CONSOLE, DEMO, OTHER, Session, seeded, session, valkey
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.integration

__all__ = ["seeded", "session", "valkey"]  # the fixtures, re-used


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
    private_keycloak: PrivateKeycloak, valkey: str, seeded: ThrowawayDatabase
) -> None:
    settings = make_settings(
        **{
            **PRODUCTION_REQUIRED,
            "database_url": seeded.app_url,
            "valkey_url": valkey,
            "oidc_issuer": private_keycloak.issuer,
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
