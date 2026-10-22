from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.types import Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.middleware import (
    API_CSP,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.request_context import accept_request_id, current_request_id
from app.main import create_app


@pytest.fixture
def app(settings_factory: Callable[..., Settings]) -> FastAPI:
    return create_app(settings_factory())


async def test_request_id_is_generated_and_echoed(
    app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(app) as client:
        first = await client.get("/api/v1/health")
        second = await client.get("/api/v1/health")

    first_id = first.headers["x-request-id"]
    assert len(first_id) == 36
    assert first_id != second.headers["x-request-id"]


async def test_safe_client_request_id_is_kept(
    app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(app) as client:
        response = await client.get("/api/v1/health", headers={"X-Request-ID": "lb-7f3a:42"})
    assert response.headers["x-request-id"] == "lb-7f3a:42"


@pytest.mark.parametrize("unsafe", ["", "a b", "x" * 129, "id\nforged=1", "<script>"])
def test_unsafe_client_request_ids_are_replaced(unsafe: str) -> None:
    accepted = accept_request_id(unsafe)
    assert accepted != unsafe
    assert len(accepted) == 36


async def test_security_headers_on_every_response(
    app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(app) as client:
        ok = await client.get("/api/v1/health")
        missing = await client.get("/api/v1/missing")

    for response in (ok, missing):
        assert response.headers["content-security-policy"] == API_CSP
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"
        assert "strict-transport-security" not in response.headers


async def test_hsts_only_in_production(
    settings_factory: Callable[..., Settings], run_app: Callable[[FastAPI], Any]
) -> None:
    production = settings_factory(
        profile="production",
        database_url="postgresql://u:p@db/x",
        valkey_url="valkey://:p@kv:6379/0",
        nats_url="nats://bus:4222",
    )
    async with run_app(create_app(production)) as client:
        response = await client.get("/api/v1/health")
    assert response.headers["strict-transport-security"].startswith("max-age=")


async def test_request_id_is_bound_during_the_request_and_cleared_after(
    app: FastAPI, run_app: Callable[[FastAPI], Any], caplog: pytest.LogCaptureFixture
) -> None:
    async with run_app(app) as client:
        response = await client.get("/api/v1/health", headers={"X-Request-ID": "trace-me"})

    access = [r.msg for r in caplog.records if r.name == "app.access"]
    assert isinstance(access[-1], dict)
    assert access[-1]["request_id"] == "trace-me"
    assert access[-1]["tenant_id"] is None
    assert access[-1]["status"] == response.status_code
    assert current_request_id() is None


async def _lifespan_app(scope: Scope, _receive: Receive, send: Send) -> None:
    assert scope["type"] == "lifespan"
    await send({"type": "lifespan.startup.complete"})


@pytest.mark.parametrize("middleware", [RequestContextMiddleware, SecurityHeadersMiddleware])
async def test_non_http_scopes_pass_through(middleware: Callable[[Any], Any]) -> None:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "lifespan.startup"}  # pragma: no cover - never awaited

    async def send(message: Message) -> None:
        sent.append(message)

    await middleware(_lifespan_app)({"type": "lifespan"}, receive, send)
    assert sent == [{"type": "lifespan.startup.complete"}]


async def test_exception_after_response_started_is_reraised() -> None:
    async def half_sent(_scope: Scope, _receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        msg = "stream broke"
        raise RuntimeError(msg)

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(_message: Message) -> None:
        return None

    scope: Scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    with pytest.raises(RuntimeError, match="stream broke"):
        await RequestContextMiddleware(half_sent)(scope, receive, send)
