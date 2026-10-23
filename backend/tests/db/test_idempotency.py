"""Idempotency-Key on POST over HTTP, with real PostgreSQL (WP-008, ADR-020)."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI, Response
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.database import TenantSession
from app.core.modules import ModuleRegistry, ModuleSpec, discover_modules
from app.core.tenancy import SESSION_RESOLVER_STATE
from app.main import create_app
from app.shared.api.idempotency import Created, Idempotency
from conftest import create_tenant, make_settings
from tests.db.probe import ProbeItem, ProbeRepository
from tests.db.test_users_api import fake_session
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db
router = APIRouter(prefix="/probe-items")


class NewItem(BaseModel):
    title: str


class ItemOut(BaseModel):
    id: uuid.UUID
    title: str


@router.post("", status_code=201, response_model=ItemOut)
async def create_item(body: NewItem, session: TenantSession, idempotency: Idempotency) -> Response:
    async def create() -> Created:
        item = await ProbeRepository(session).add(ProbeItem(title=body.title))
        await asyncio.sleep(0.05)  # widen the window for concurrent duplicates
        if body.title == "explode":
            msg = "failed after writing"
            raise RuntimeError(msg)
        return Created(
            ItemOut(id=item.id, title=item.title),
            headers={"Location": f"/api/v1/probe-items/{item.id}", "X-Ignored": "1"},
        )

    return await idempotency.run(body, create)


@dataclass
class Api:
    client: AsyncClient
    db: ThrowawayDatabase
    tenant: uuid.UUID

    async def post(
        self,
        title: str,
        key: str | None,
        *,
        user: uuid.UUID | None = None,
        tenant: uuid.UUID | None = None,
    ) -> httpx.Response:
        headers = {"X-Test-Tenant": str(tenant or self.tenant)}
        if user:
            headers["X-Test-User"] = str(user)
        if key is not None:
            headers["Idempotency-Key"] = key
        return await self.client.post("/api/v1/probe-items", json={"title": title}, headers=headers)

    async def count(self, tenant: uuid.UUID | None = None) -> int:
        conn = await asyncpg.connect(self.db.admin_url)
        try:
            return int(
                await conn.fetchval(
                    "SELECT count(*) FROM probe_items WHERE tenant_id = $1", tenant or self.tenant
                )
            )
        finally:
            await conn.close()


@pytest_asyncio.fixture
async def api(migrated_db: ThrowawayDatabase) -> AsyncIterator[Api]:
    tenant = await create_tenant(migrated_db.migrator_url, "Idempotency")
    registry = ModuleRegistry.from_specs(
        [*discover_modules(), ModuleSpec(name="probe", routers=[router])]
    )
    app: FastAPI = create_app(make_settings(database_url=migrated_db.app_url), registry)
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield Api(client, migrated_db, tenant)


async def test_same_key_and_body_replays_the_first_response(api: Api) -> None:
    key = str(uuid.uuid4())
    first = await api.post("Printer jam", key)
    second = await api.post("Printer jam", key)
    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["location"] == first.headers["location"]
    assert second.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    assert "x-ignored" not in second.headers  # only Location/ETag are replayed
    assert await api.count() == 1


async def test_same_key_with_a_different_body_is_refused(api: Api) -> None:
    key = str(uuid.uuid4())
    await api.post("Printer jam", key)
    reused = await api.post("Something else", key)
    assert (reused.status_code, reused.json()["code"]) == (422, "idempotency_key_reused")
    assert await api.count() == 1


async def test_without_a_key_every_post_creates(api: Api) -> None:
    await api.post("a", None)
    await api.post("a", None)
    assert await api.count() == 2


async def test_keys_are_scoped_to_user_and_tenant(api: Api, migrated_db: ThrowawayDatabase) -> None:
    key = "shared-key-123"
    alice, bob = uuid.uuid4(), uuid.uuid4()
    a = await api.post("same", key, user=alice)
    b = await api.post("same", key, user=bob)
    assert a.json()["id"] != b.json()["id"]  # Bob does not get Alice's stored response
    assert "idempotent-replayed" not in b.headers
    other_tenant = await create_tenant(migrated_db.migrator_url, "Other")
    c = await api.post("same", key, user=alice, tenant=other_tenant)
    assert c.status_code == 201
    assert "idempotent-replayed" not in c.headers
    assert await api.count() == 2
    assert await api.count(other_tenant) == 1


async def test_concurrent_duplicates_create_exactly_one_record(api: Api) -> None:
    key = str(uuid.uuid4())
    responses = await asyncio.gather(*(api.post("Burst", key) for _ in range(10)))
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert sum(r.headers.get("idempotent-replayed") == "true" for r in responses) == 9
    assert await api.count() == 1


async def test_a_failed_request_leaves_no_key_behind(api: Api) -> None:
    key = str(uuid.uuid4())
    failed = await api.post("explode", key)
    assert failed.status_code == 500
    assert await api.count() == 0  # the item rolled back with the key
    conn = await asyncpg.connect(api.db.admin_url)
    try:
        assert await conn.fetchval("SELECT count(*) FROM idempotency_keys WHERE key = $1", key) == 0
    finally:
        await conn.close()


async def test_an_expired_key_starts_over(api: Api) -> None:
    key = str(uuid.uuid4())
    first = await api.post("Old", key)
    conn = await asyncpg.connect(api.db.admin_url)
    try:
        await conn.execute(
            "UPDATE idempotency_keys SET expires_at = now() - interval '1 second' WHERE key = $1",
            key,
        )
    finally:
        await conn.close()
    again = await api.post("New body is fine after expiry", key)
    assert again.status_code == 201
    assert again.json()["id"] != first.json()["id"]
    assert await api.count() == 2


async def test_malformed_keys_are_refused(api: Api) -> None:
    response = await api.post("x", "has spaces in it")
    assert (response.status_code, response.json()["code"]) == (400, "invalid_idempotency_key")


async def test_the_app_role_sees_only_its_tenants_keys(
    api: Api, migrated_db: ThrowawayDatabase
) -> None:
    await api.post("mine", "visible-only-to-me")
    from sqlalchemy import text  # noqa: PLC0415

    from app.core.database import Database, create_engine  # noqa: PLC0415 - local to this check
    from app.core.tenancy import TenantContext  # noqa: PLC0415

    other_tenant = await create_tenant(migrated_db.migrator_url, "Snoop")
    database = Database(
        create_engine(migrated_db.app_url, application_name="t", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(other_tenant)) as session:
            assert (
                await session.execute(text("SELECT count(*) FROM idempotency_keys"))
            ).scalar() == 0
    finally:
        await database.dispose()
