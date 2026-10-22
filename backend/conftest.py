"""Shared pytest fixtures for app-level tests (tests/) and module tests (app/modules/*/tests/)."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings


def make_settings(**overrides: Any) -> Settings:  # noqa: ANN401 - pydantic validates the values
    """Test-profile settings that never read backend/.env or the developer's environment file."""
    values: dict[str, Any] = {"profile": "test", "tracing_enabled": False, **overrides}
    return Settings.load(env_file=None, **values)


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    """Build test settings with overrides: `settings_factory(log_format="json")`."""
    return make_settings


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Run the app's lifespan (startup/shutdown hooks) around an HTTP client."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def run_app() -> Callable[[FastAPI], Any]:
    """Return `running`, used as `async with run_app(app) as client:`."""
    return running
