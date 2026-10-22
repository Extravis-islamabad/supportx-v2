"""App factory and lifespan (architecture.md §6.4; WP-004).

`create_app()` wires the cross-cutting pieces (settings, logging, errors, middleware, tracing)
and mounts whatever modules the registry discovers under app/modules/. Adding a module never
requires editing this file.

Run locally: `make backend-dev` (uvicorn with reload on 127.0.0.1:8000).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app import __version__
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import ProblemDetail, install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.modules import ModuleRegistry, discover_modules
from app.core.telemetry import setup_tracing

API_V1_PREFIX = "/api/v1"
OPENAPI_URL = f"{API_V1_PREFIX}/openapi.json"
DOCS_URL = f"{API_V1_PREFIX}/docs"

log = get_logger(__name__)


def create_app(settings: Settings | None = None, registry: ModuleRegistry | None = None) -> FastAPI:
    """Build the Core API. Tests pass their own settings and, if needed, a module registry."""
    settings = settings or get_settings()
    registry = registry or ModuleRegistry.from_specs(discover_modules())
    configure_logging(settings)
    docs = settings.effective_api_docs_enabled

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Created here, not at import, so the pool belongs to the server's event loop.
        app.state.db = Database.from_settings(settings)
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
    app.state.event_handlers = registry.event_handlers()

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
    return app
