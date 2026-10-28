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
    assert body["failed"] == ["postgres", "valkey", "nats", "keycloak"]
    assert body["checks"]["postgres"] == {
        "status": "not_configured",
        "latency_ms": None,
        "reason": None,
        "critical": True,
    }
    assert body["degraded"] == []  # no NATS configured: worker heartbeats are not probed


async def test_docs_are_served_in_dev_and_hidden_in_production(
    settings_factory: Callable[..., Settings],
    production_settings: Callable[..., Settings],
    run_app: Callable[[FastAPI], Any],
) -> None:
    async with run_app(create_app(settings_factory(api_docs_enabled=True))) as client:
        docs = await client.get("/api/v1/docs")
        schema = await client.get("/api/v1/openapi.json")
    assert docs.status_code == 200
    assert "frame-ancestors 'none'" in docs.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert schema.json()["openapi"].startswith("3.1")

    production = production_settings()
    async with run_app(create_app(production)) as client:
        assert (await client.get("/api/v1/docs")).status_code == 404
        assert (await client.get("/api/v1/openapi.json")).status_code == 404


async def test_ready_says_event_delivery_is_stalled_when_a_worker_is_cut_off(
    settings_factory: Callable[..., Settings], run_app: Callable[[FastAPI], Any]
) -> None:
    """Must-fix before the pilot: a worker that lost PostgreSQL or NATS shows, never silently."""
    from app.modules.system.domain.readiness import FailureReason, ProbeFailedError  # noqa: PLC0415
    from app.modules.system.service.readiness import ReadinessService  # noqa: PLC0415
    from app.modules.system.tests.test_readiness_service import FakeProbe  # noqa: PLC0415

    app = create_app(settings_factory())
    async with run_app(app) as client:
        app.state.readiness = ReadinessService(
            [FakeProbe("postgres"), FakeProbe("nats")],
            informational=[
                FakeProbe("outbox_relay", ProbeFailedError(FailureReason.DISCONNECTED)),
                FakeProbe("event_consumers"),
            ],
            timeout=1.0,
        )
        stalled = await client.get("/api/v1/ready")
        app.state.readiness = ReadinessService(
            [FakeProbe("postgres"), FakeProbe("nats")],
            informational=[FakeProbe("outbox_relay"), FakeProbe("event_consumers")],
            timeout=1.0,
        )
        fine = await client.get("/api/v1/ready")

    assert stalled.status_code == 200  # informational: the API stays in service
    assert stalled.json()["event_delivery"] == "stalled"
    assert stalled.json()["checks"]["outbox_relay"]["reason"] == "disconnected"
    assert fine.json()["event_delivery"] == "ok"
