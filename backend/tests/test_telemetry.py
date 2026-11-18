from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import telemetry
from app.core.config import Settings
from app.core.telemetry import build_tracer_provider, redacted_query
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


def test_a_query_keeps_its_keys_and_loses_its_values() -> None:
    assert redacted_query(b"filter=%7B%22v%22%3A%22X%22%7D&limit=50") == (
        "filter=REDACTED&limit=REDACTED"
    )
    assert redacted_query("") == ""


async def test_no_query_value_reaches_a_span(
    settings_factory: Callable[..., Settings],
    run_app: Callable[[FastAPI], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A list filter on a sealed field (ADR-050): its value is in no span attribute (lane C)."""
    exported = InMemorySpanExporter()
    made = telemetry.build_tracer_provider

    def with_memory(settings: Settings) -> Any:  # noqa: ANN401 - the SDK's provider
        provider = made(settings)
        provider.add_span_processor(SimpleSpanProcessor(exported))
        return provider

    monkeypatch.setattr(telemetry, "build_tracer_provider", with_memory)
    secret = "AB-1234-SEALED"
    sealed_filter = '{"field":"custom.national_id","op":"eq","value":"' + secret + '"}'
    async with run_app(create_app(settings_factory(tracing_enabled=True))) as client:
        await client.get("/api/v1/incidents", params={"filter": sealed_filter, "limit": "50"})
    spans = exported.get_finished_spans()
    assert spans, "the request made no span"
    for span in spans:
        for value in (span.attributes or {}).values():
            assert secret not in str(value)
            assert "national_id" not in str(value)
    server = [s for s in spans if (s.attributes or {}).get("url.query")]
    assert server
    attrs = server[0].attributes or {}
    assert attrs.get("url.query") == "filter=REDACTED&limit=REDACTED"
