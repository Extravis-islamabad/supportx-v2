from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app.core.config import Settings
from app.core.telemetry import build_tracer_provider
from app.main import create_app


def test_no_exporter_by_default(settings_factory: Callable[..., Settings]) -> None:
    provider = build_tracer_provider(settings_factory(tracing_enabled=True))
    processors = provider._active_span_processor._span_processors  # noqa: SLF001 - SDK has no public accessor
    assert processors == ()
    assert provider.resource.attributes["service.name"] == "supportx-api"
    assert provider.resource.attributes["deployment.environment.name"] == "test"


def test_console_exporter_is_opt_in(settings_factory: Callable[..., Settings]) -> None:
    provider = build_tracer_provider(settings_factory(trace_exporter="console"))
    processors = provider._active_span_processor._span_processors  # noqa: SLF001 - as above
    assert len(processors) == 1
    assert isinstance(processors[0], SimpleSpanProcessor)


async def test_requests_are_traced_and_ids_reach_the_logs(
    settings_factory: Callable[..., Settings],
    run_app: Callable[[FastAPI], Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(settings_factory(tracing_enabled=True))
    async with run_app(app) as client:
        await client.get("/api/v1/does-not-exist")
        await client.get("/api/v1/health")

    access = [r.msg for r in caplog.records if r.name == "app.access"]
    assert isinstance(access[0], dict)
    assert len(access[0]["trace_id"]) == 32
    # Probe endpoints are excluded from tracing to keep traces free of orchestrator noise.
    assert isinstance(access[1], dict)
    assert "trace_id" not in access[1]


async def test_tracing_can_be_disabled(
    settings_factory: Callable[..., Settings],
    run_app: Callable[[FastAPI], Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with run_app(create_app(settings_factory(tracing_enabled=False))) as client:
        await client.get("/api/v1/does-not-exist")
    access = [r.msg for r in caplog.records if r.name == "app.access"]
    assert isinstance(access[0], dict)
    assert "trace_id" not in access[0]
