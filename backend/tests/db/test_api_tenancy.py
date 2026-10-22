"""Tenant resolution, unit of work and 409 problem details, over HTTP."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from app.core.config import Settings
from app.core.database import TenantSession
from app.core.modules import ModuleRegistry, ModuleSpec, discover_modules
from app.main import create_app
from tests.db.probe import ProbeItem, ProbeRepository
from tooling.db_testing import ThrowawayDatabase

router = APIRouter(prefix="/probe")


class Title(BaseModel):
    title: str


class ProbeOut(BaseModel):
    id: uuid.UUID
    title: str
    version: int


@router.post("")
async def create_probe(body: Title, session: TenantSession) -> ProbeOut:
    item = await ProbeRepository(session).add(ProbeItem(title=body.title))
    return ProbeOut(id=item.id, title=item.title, version=item.version)


@router.post("/fail")
async def create_then_fail(body: Title, session: TenantSession) -> None:
    await ProbeRepository(session).add(ProbeItem(title=body.title))
    msg = "boom after write"
    raise RuntimeError(msg)


@router.patch("/{item_id}")
async def rename_probe(
    item_id: uuid.UUID, version: int, body: Title, session: TenantSession
) -> ProbeOut:
    item = await ProbeRepository(session).update(
        item_id, expected_version=version, changes={"title": body.title}
    )
    return ProbeOut(id=item.id, title=item.title, version=item.version)


@router.get("")
async def list_probes(session: TenantSession) -> list[str]:
    return [item.title for item in (await ProbeRepository(session).list()).items]


def build_app(settings: Settings) -> FastAPI:
    specs = [*discover_modules(), ModuleSpec(name="probe", routers=[router])]
    return create_app(settings, ModuleRegistry.from_specs(specs))


@pytest.fixture
def dev_app(migrated_db: ThrowawayDatabase, settings_factory: Callable[..., Settings]) -> FastAPI:
    return build_app(settings_factory(profile="dev", database_url=migrated_db.app_url))


def header(tenant: uuid.UUID) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant)}


@pytest.mark.db
async def test_dev_profile_resolves_tenant_from_header(
    dev_app: FastAPI, run_app: Callable[[FastAPI], Any], tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    async with run_app(dev_app) as client:
        own = await client.get("/api/v1/organization/tenant", headers=header(a))
        other = await client.get("/api/v1/organization/tenant", headers=header(b))
    assert own.status_code == 200
    assert own.json()["id"] == str(a)
    assert own.json()["status"] == "active"
    assert other.json()["id"] == str(b)


@pytest.mark.db
async def test_unknown_tenant_sees_nothing(
    dev_app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(dev_app) as client:
        response = await client.get("/api/v1/organization/tenant", headers=header(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["code"] == "tenant_not_found"


@pytest.mark.db
async def test_missing_or_invalid_header_in_dev(
    dev_app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(dev_app) as client:
        missing = await client.get("/api/v1/organization/tenant")
        invalid = await client.get("/api/v1/organization/tenant", headers={"X-Tenant-ID": "acme"})
    assert (missing.status_code, missing.json()["code"]) == (401, "tenant_required")
    assert (invalid.status_code, invalid.json()["code"]) == (400, "invalid_tenant_id")


async def test_production_ignores_the_tenant_header(
    settings_factory: Callable[..., Settings], run_app: Callable[[FastAPI], Any]
) -> None:
    """Production must not trust a client-chosen tenant, even a valid, existing one."""
    production = settings_factory(
        profile="production",
        database_url="postgresql://supportx_app:x@127.0.0.1:1/supportx",
        valkey_url="valkey://:p@127.0.0.1:1/0",
        nats_url="nats://127.0.0.1:1",
    )
    async with run_app(build_app(production)) as client:
        response = await client.get(
            "/api/v1/organization/tenant", headers={"X-Tenant-ID": str(uuid.uuid4())}
        )
        invalid = await client.get("/api/v1/organization/tenant", headers={"X-Tenant-ID": "acme"})
    assert response.status_code == 401
    assert response.json()["code"] == "tenant_required"
    # Even a malformed header is ignored rather than parsed.
    assert invalid.json()["code"] == "tenant_required"


@pytest.mark.db
async def test_unit_of_work_commits_on_success_and_rolls_back_on_error(
    dev_app: FastAPI, run_app: Callable[[FastAPI], Any], tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = tenant_pair
    async with run_app(dev_app) as client:
        created = await client.post("/api/v1/probe", json={"title": "kept"}, headers=header(a))
        failed = await client.post(
            "/api/v1/probe/fail", json={"title": "discarded"}, headers=header(a)
        )
        titles = (await client.get("/api/v1/probe", headers=header(a))).json()
    assert created.status_code == 200
    assert failed.status_code == 500
    assert "kept" in titles
    assert "discarded" not in titles


@pytest.mark.db
async def test_stale_update_returns_409_problem_details(
    dev_app: FastAPI, run_app: Callable[[FastAPI], Any], tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = tenant_pair
    async with run_app(dev_app) as client:
        item = (
            await client.post("/api/v1/probe", json={"title": "draft"}, headers=header(a))
        ).json()
        path = f"/api/v1/probe/{item['id']}?version=1"
        first = await client.patch(path, json={"title": "first save"}, headers=header(a))
        second = await client.patch(path, json={"title": "second save"}, headers=header(a))
    assert first.status_code == 200
    assert first.json()["version"] == 2
    assert second.status_code == 409
    assert second.headers["content-type"] == "application/problem+json"
    body = second.json()
    assert body["code"] == "version_conflict"
    assert body["message_key"] == "errors.version_conflict"
    assert body["params"] == {"expected_version": 1, "current_version": 2}


async def test_tenant_endpoints_need_a_database(
    settings_factory: Callable[..., Settings], run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(build_app(settings_factory(profile="dev"))) as client:
        response = await client.get("/api/v1/organization/tenant", headers=header(uuid.uuid4()))
    assert response.status_code == 503
    assert response.json()["code"] == "database_not_configured"
