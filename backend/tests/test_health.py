from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from app import __version__
from app.core.config import Settings
from app.main import create_app


async def test_health_returns_ok_and_version(
    settings_factory: Callable[..., Settings], run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(create_app(settings_factory())) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_ready_reports_unconfigured_dependencies_as_not_ready(
    settings_factory: Callable[..., Settings], run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(create_app(settings_factory())) as client:
        response = await client.get("/api/v1/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["failed"] == ["postgres", "valkey", "nats"]
    assert body["checks"]["postgres"] == {
        "status": "not_configured",
        "latency_ms": None,
        "reason": None,
    }


async def test_docs_are_served_in_dev_and_hidden_in_production(
    settings_factory: Callable[..., Settings], run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(create_app(settings_factory(api_docs_enabled=True))) as client:
        docs = await client.get("/api/v1/docs")
        schema = await client.get("/api/v1/openapi.json")
    assert docs.status_code == 200
    assert "frame-ancestors 'none'" in docs.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert schema.json()["openapi"].startswith("3.1")

    production = settings_factory(
        profile="production",
        database_url="postgresql://u:p@db/x",
        valkey_url="valkey://:p@kv:6379/0",
        nats_url="nats://bus:4222",
    )
    async with run_app(create_app(production)) as client:
        assert (await client.get("/api/v1/docs")).status_code == 404
        assert (await client.get("/api/v1/openapi.json")).status_code == 404
