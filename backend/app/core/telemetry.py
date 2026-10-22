"""OpenTelemetry tracing (architecture.md §15; WP-004).

Tracing is always wired so spans exist and their IDs reach the logs. Exporting them is off by
default (`SUPPORTX_TRACE_EXPORTER=none`); `console` prints spans for local debugging. An OTLP
exporter for Tempo is added when the observability stack lands, without touching call sites.
"""

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from app import __version__
from app.core.config import Settings

# Probes are hit every few seconds by orchestrators; tracing them is noise.
EXCLUDED_URLS = "api/v1/health,api/v1/ready"


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


def setup_tracing(app: FastAPI, settings: Settings) -> TracerProvider | None:
    """Instrument the app with its own tracer provider.

    The provider is passed explicitly (not set globally) so each create_app() call, e.g. in
    tests, gets an isolated tracing pipeline.
    """
    if not settings.tracing_enabled:
        return None
    provider = build_tracer_provider(settings)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls=EXCLUDED_URLS)
    return provider
