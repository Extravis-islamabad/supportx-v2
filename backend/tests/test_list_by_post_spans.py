"""No span holds a sealed filter value, by GET or by POST (lane C's condition 7, sealed filters).

The GET form's query values are redacted in spans (f718b695b, tests/test_telemetry.py); the POST
form keeps its filter in the body, which no span records. Both are captured here with an
in-memory exporter, around the GET refusal and the POST.
"""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import telemetry
from app.core.config import Settings
from app.main import create_app

SECRET = "ZX-9081-SEALED"


async def test_no_span_holds_a_sealed_value_by_get_or_post(
    settings_factory: Callable[..., Settings],
    run_app: Callable[[FastAPI], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exported = InMemorySpanExporter()
    made = telemetry.build_tracer_provider

    def with_memory(settings: Settings) -> Any:  # noqa: ANN401 - the SDK's provider
        provider = made(settings)
        provider.add_span_processor(SimpleSpanProcessor(exported))
        return provider

    monkeypatch.setattr(telemetry, "build_tracer_provider", with_memory)
    tree = {"field": "custom.national_id", "op": "eq", "value": SECRET}
    async with run_app(create_app(settings_factory(tracing_enabled=True))) as client:
        await client.get(
            "/api/v1/incidents",
            params={"filter": f'{{"field":"custom.national_id","op":"eq","value":"{SECRET}"}}'},
        )
        await client.post("/api/v1/incidents/list", json={"filter": tree, "limit": 50})
    spans = exported.get_finished_spans()
    assert len(spans) >= 2, "each request makes a span"
    for span in spans:
        for value in (span.attributes or {}).values():
            assert SECRET not in str(value)
