"""App factory, middleware and router registration (architecture.md §6.4)."""

from fastapi import APIRouter, FastAPI

from app import __version__
from app.core import health

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Build the Core API application."""
    app = FastAPI(
        title="SupportX v2 Core API",
        version=__version__,
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        docs_url=f"{API_V1_PREFIX}/docs",
        redoc_url=None,
    )

    api_v1 = APIRouter(prefix=API_V1_PREFIX)
    api_v1.include_router(health.router)
    app.include_router(api_v1)

    return app
