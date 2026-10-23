"""App factory and lifespan (architecture.md §6.4; WP-004).

`create_app()` wires the cross-cutting pieces (settings, logging, errors, middleware, tracing)
and mounts whatever modules the registry discovers under app/modules/. Adding a module never
requires editing this file.

Run locally: `make backend-dev` (uvicorn with reload on 127.0.0.1:8000).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import valkey.asyncio
from fastapi import APIRouter, FastAPI

from app import __version__
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import ProblemDetail, install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.modules import ModuleRegistry, discover_modules
from app.core.telemetry import setup_tracing
from app.shared.api.listing import CursorCodec
from app.shared.api.openapi import add_filter_schema
from app.shared.api.ratelimit import RATE_LIMITER_STATE, RateLimiter, SettingsPolicyProvider
from app.shared.events import EventRegistry, install_registry
from app.shared.realtime import (
    CENTRIFUGO_STATE,
    REALTIME_STATE,
    CentrifugoClient,
    RealtimeRegistry,
)

API_V1_PREFIX = "/api/v1"
OPENAPI_URL = f"{API_V1_PREFIX}/openapi.json"
DOCS_URL = f"{API_V1_PREFIX}/docs"

log = get_logger(__name__)


def create_app(settings: Settings | None = None, registry: ModuleRegistry | None = None) -> FastAPI:
    """Build the Core API. Tests pass their own settings and, if needed, a module registry."""
    settings = settings or get_settings()
    discovered = registry is None
    registry = registry or ModuleRegistry.from_specs(discover_modules())
    # Fails at startup if any module breaks the event naming/versioning rules. Only the real module
    # set becomes the process registry; a test's hand-made registry is validated, not installed.
    events = EventRegistry.from_modules(registry.modules)
    if discovered:
        install_registry(events)
    configure_logging(settings)
    docs = settings.effective_api_docs_enabled

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Created here, not at import, so the pool belongs to the server's event loop.
        app.state.db = Database.from_settings(settings)
        valkey_client = _start_rate_limiter(app, settings)
        centrifugo = CentrifugoClient.from_settings(settings)
        setattr(app.state, CENTRIFUGO_STATE, centrifugo)
        await registry.start(app)
        log.info(
            "startup_complete",
            profile=settings.profile,
            version=__version__,
            modules=[m.name for m in registry.modules],
        )
        try:
            yield
        finally:
            await registry.stop(app)
            if valkey_client is not None:
                await valkey_client.aclose()
            if centrifugo is not None:
                await centrifugo.aclose()
            if app.state.db is not None:
                await app.state.db.dispose()
            if tracer_provider is not None:
                tracer_provider.shutdown()
            log.info("shutdown_complete")

    app = FastAPI(
        title="SupportX v2 Core API",
        version=__version__,
        openapi_url=OPENAPI_URL if docs else None,
        docs_url=DOCS_URL if docs else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.modules = registry
    # Channel specs and fan-out routes of every module (WP-011); invalid declarations fail here.
    setattr(app.state, REALTIME_STATE, RealtimeRegistry.build(registry.modules))
    setattr(app.state, CENTRIFUGO_STATE, None)  # set in the lifespan when configured
    app.state.cursor_codec = CursorCodec.from_settings(settings)

    install_error_handlers(app)
    # Last added runs first: security headers wrap everything, including the 500 responses that
    # RequestContextMiddleware produces for unhandled exceptions.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        docs_paths=(DOCS_URL,) if docs else (),
        hsts=settings.profile == "production",
    )

    # Every route documents the shared error body (RFC 9457) for unexpected failures.
    api_v1 = APIRouter(
        prefix=API_V1_PREFIX,
        responses={500: {"model": ProblemDetail, "description": "Unexpected server error."}},
    )
    registry.include_routers(api_v1)
    app.include_router(api_v1)

    tracer_provider = setup_tracing(app, settings)
    _publish_shared_schemas(app)
    return app


def _start_rate_limiter(app: FastAPI, settings: Settings) -> Any:  # noqa: ANN401 - valkey client, untyped library
    """Rate limiter on Valkey (WP-008); off when disabled or Valkey is not configured."""
    setattr(app.state, RATE_LIMITER_STATE, None)
    if not settings.rate_limit_enabled or settings.valkey_url is None:
        return None
    client = valkey.asyncio.from_url(settings.valkey_url.get_secret_value())  # type: ignore[no-untyped-call]  # valkey-py ships no annotation for from_url
    limiter = RateLimiter(
        client, prefix=settings.valkey_key_prefix, provider=SettingsPolicyProvider(settings)
    )
    setattr(app.state, RATE_LIMITER_STATE, limiter)
    return client


def _publish_shared_schemas(app: FastAPI) -> None:
    """Add the filter DSL schema to the OpenAPI document (app/shared/api/openapi.py)."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = add_filter_schema(generate())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]  # FastAPI's documented customisation hook
