"""OpenTelemetry tracing and HTTP metrics (architecture.md §15; WP-004, WP-014).

Tracing is always wired so spans exist and their IDs reach the logs. Exporting them is off by
default (`SUPPORTX_TRACE_EXPORTER=none`); `console` prints spans for local debugging. An OTLP
exporter is added when the observability stack lands, without touching call sites.

HTTP server metrics (request duration and count per route) are recorded when
`SUPPORTX_METRICS_EXPORTER=prometheus` and served by app.core.ops_server on the internal port.
"""

import urllib.parse
from typing import Any

from fastapi import FastAPI
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from app import __version__
from app.core.config import Settings

# Probes are hit every few seconds by orchestrators; tracing them is noise. OAuth callbacks
# carry an authorization code and state in the query, which a span would keep (§11: secrets
# never in logs).
EXCLUDED_URLS = "api/v1/health,api/v1/ready,api/v1/auth/callback,api/v1/integrations/oauth/callback"
# A query string's values never reach a span: list filters carry what people searched for, a
# sealed field's value included (ADR-050), and the instrumentation keeps the full URL in
# `http.url` (its own redaction masks only cloud signatures) and the raw query in `url.query`.
# The parameter names stay, for debugging; every value becomes REDACTED.
REDACTED = "REDACTED"


def redacted_query(query_string: bytes | str) -> str:
    """The query with every value replaced, its keys and order kept (`a=REDACTED&b=REDACTED`)."""
    text = query_string.decode("latin-1") if isinstance(query_string, bytes) else query_string
    pairs = urllib.parse.parse_qsl(text, keep_blank_values=True)
    return "&".join(f"{urllib.parse.quote(key, safe='')}={REDACTED}" for key, _ in pairs)


def _redact_server_span(span: Any, scope: dict[str, Any]) -> None:  # noqa: ANN401 - OTel's span
    """Overwrite the URL attributes the instrumentation set with values redacted."""
    query = scope.get("query_string") or b""
    if not query or span is None or not span.is_recording():
        return
    hidden = redacted_query(query)
    scheme = scope.get("scheme", "http")
    host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
    url = f"{scheme}://{host}{scope.get('root_path', '')}{scope.get('path', '')}?{hidden}"
    span.set_attribute("http.url", url)
    span.set_attribute("url.full", url)
    span.set_attribute("url.query", hidden)


def build_tracer_provider(settings: Settings) -> TracerProvider:
    """Tracer provider for this app instance, with an exporter only if one is configured."""
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": __version__,
                "deployment.environment.name": settings.profile,
            }
        )
    )
    if settings.trace_exporter == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    return provider


def build_meter_provider(settings: Settings) -> MeterProvider | None:
    """HTTP metrics for Prometheus, or None when metrics are not exported."""
    if settings.metrics_exporter != "prometheus":
        return None
    return MeterProvider(
        metric_readers=[PrometheusMetricReader()],
        resource=Resource.create(
            {"service.name": settings.service_name, "service.version": __version__}
        ),
    )


def setup_tracing(
    app: FastAPI, settings: Settings
) -> tuple[TracerProvider | None, MeterProvider | None]:
    """Instrument the app with its own tracer (and, if exported, meter) provider.

    The providers are passed explicitly (not set globally) so each create_app() call, e.g. in
    tests, gets an isolated pipeline.
    """
    tracer = build_tracer_provider(settings) if settings.tracing_enabled else None
    meter = build_meter_provider(settings)
    if tracer is None and meter is None:
        return None, None
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer,
        meter_provider=meter,
        excluded_urls=EXCLUDED_URLS,
        server_request_hook=_redact_server_span,
    )
    return tracer, meter
