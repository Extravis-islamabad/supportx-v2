"""The request body cap (app/core/body_limit.py; lane B, found reviewing #495)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from app.core.body_limit import (
    DEFAULT_MAX_BYTES,
    STREAMED,
    BodyLimitMiddleware,
    RaiseCap,
    body_limit,
)
from app.core.errors import install_error_handlers
from app.main import create_app
from conftest import make_settings
from tooling.route_permissions import api_routes, route_dependencies

CAP = 1000


class Body(BaseModel):
    text: str


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(BodyLimitMiddleware, default_max_bytes=CAP)

    @app.post("/api/v1/json")
    async def json_route(body: Body) -> dict[str, int]:
        return {"length": len(body.text)}

    @app.post("/api/v1/files", dependencies=[Depends(body_limit(5 * CAP))])
    async def streamed(request: Request) -> dict[str, int]:
        size = 0
        async for piece in request.stream():
            size += len(piece)
        return {"size": size}

    return app


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://t")


async def _chunks(total: int) -> AsyncIterator[bytes]:
    sent = 0
    while sent < total:
        piece = b"x" * min(256, total - sent)
        sent += len(piece)
        yield piece


async def test_a_small_json_body_goes_through() -> None:
    async with _client() as client:
        response = await client.post("/api/v1/json", json={"text": "hello"})
    assert response.status_code == 200
    assert response.json() == {"length": 5}


async def test_a_declared_length_over_the_cap_is_refused_before_reading() -> None:
    async with _client() as client:
        response = await client.post("/api/v1/json", json={"text": "x" * (CAP * 2)})
    assert response.status_code == 413
    body: dict[str, Any] = response.json()
    assert (body["code"], body["params"]) == ("payload_too_large", {"max_bytes": CAP})


async def test_a_chunked_body_with_no_length_is_stopped_at_the_cap() -> None:
    async with _client() as client:
        response = await client.post(
            "/api/v1/json",
            content=_chunks(CAP * 3),
            headers={"content-type": "application/json"},
        )
    assert "content-length" not in {k.lower() for k in response.request.headers}
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


async def test_a_streamed_route_raises_its_own_cap_and_keeps_it() -> None:
    async with _client() as client:
        fine = await client.post("/api/v1/files", content=b"x" * (CAP * 3))
        chunked = await client.post("/api/v1/files", content=_chunks(CAP * 4))
        over = await client.post("/api/v1/files", content=_chunks(CAP * 6))
    assert (fine.status_code, fine.json()) == (200, {"size": CAP * 3})
    assert chunked.status_code == 200
    assert over.status_code == 413


def test_every_raised_cap_is_listed_as_streamed_and_nothing_else_is() -> None:
    """A route that raises its cap must be in STREAMED (its declared length waits for the
    route's own cap), and STREAMED names only such routes."""
    app = create_app(make_settings())
    raised: set[str] = set()
    for method, path, dependant, _endpoint in api_routes(app):
        caps = [c for c in route_dependencies(dependant) if isinstance(c, RaiseCap)]
        if caps:
            assert all(c.max_bytes > DEFAULT_MAX_BYTES for c in caps), path
            assert any(method == m and p.match(path) for m, p in STREAMED), (method, path)
            raised.add(f"{method} {path}")
    for method, pattern in STREAMED:
        found = [r for r in raised if r.startswith(method + " ") and pattern.match(r.split(" ")[1])]
        assert found, pattern.pattern


def test_the_production_app_installs_the_cap() -> None:
    app = create_app(make_settings())
    assert any(getattr(m, "cls", None) == BodyLimitMiddleware for m in app.user_middleware)
