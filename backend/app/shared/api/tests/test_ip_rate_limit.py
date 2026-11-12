"""Per-address rate limits for routes with nobody signed in (audit row 14), on a fake Valkey."""

from typing import Annotated, Any

import pytest
import valkey.exceptions
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.errors import install_error_handlers
from app.shared.api.ratelimit import (
    RATE_LIMITER_STATE,
    AddressLimit,
    RateLimiter,
    SettingsPolicyProvider,
    ip_rate_limit,
)


class CountingValkey:
    """INCR for every key a script names; one count per key, as both scripts return."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.down = False

    async def eval(self, script: str, keys: int, *args: Any) -> list[int]:  # noqa: ANN401 - Valkey's eval
        del script
        if self.down:
            raise valkey.exceptions.ConnectionError
        found = []
        for key in args[:keys]:
            self.counts[key] = self.counts.get(key, 0) + 1
            found.append(self.counts[key])
        return found


def build(fake: CountingValkey) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    settings = Settings.load(env_file=None, profile="test", tracing_enabled=False)
    limiter = RateLimiter(
        fake, prefix="t:", provider=SettingsPolicyProvider(settings), clock=lambda: 1_800_000_040.0
    )
    setattr(app.state, RATE_LIMITER_STATE, limiter)

    @app.get("/open", dependencies=[Depends(ip_rate_limit("open", 2))])
    async def open_route() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get(
        "/closed", dependencies=[Depends(ip_rate_limit("closed", 2, fail_closed_code="x_down"))]
    )
    async def closed_route() -> dict[str, str]:
        return {"ok": "yes"}

    deferred = ip_rate_limit("deferred", 1, defer=True)

    @app.get("/deferred")
    async def deferred_route(
        limited: Annotated[AddressLimit, Depends(deferred)],
    ) -> dict[str, str]:
        return {"refused": limited.refusal.instance_code if limited.refusal is not None else ""}

    return app


async def get(app: FastAPI, path: str, address: str = "10.0.0.1") -> Any:  # noqa: ANN401 - a response
    transport = ASGITransport(app=app, client=(address, 1234))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_each_address_has_its_own_budget_with_headers() -> None:
    fake = CountingValkey()
    app = build(fake)
    answers = [await get(app, "/open") for _ in range(3)]
    assert [r.status_code for r in answers] == [200, 200, 429]
    assert answers[0].headers["ratelimit-limit"] == "2"
    assert answers[0].headers["ratelimit-remaining"] == "1"
    assert answers[0].headers["ratelimit-reset"] == "20"
    refused = answers[2]
    assert refused.json()["code"] == "rate_limited"
    assert refused.headers["retry-after"] == "20"
    assert (await get(app, "/open", "10.0.0.2")).status_code == 200  # another client
    assert (await get(app, "/closed")).status_code == 200  # another group
    # Its own key space, and no address in any key (personal data).
    assert all(key.startswith("t:rlip:") for key in fake.counts)
    assert not any("10.0.0" in key for key in fake.counts)


async def test_valkey_down_fails_open_unless_the_route_says_closed() -> None:
    fake = CountingValkey()
    fake.down = True
    app = build(fake)
    assert (await get(app, "/open")).status_code == 200
    closed = await get(app, "/closed")
    assert (closed.status_code, closed.json()["code"]) == (503, "x_down")
    assert closed.headers["retry-after"] == "2"


async def test_deferred_refusal_is_returned_to_the_route() -> None:
    app = build(CountingValkey())
    assert (await get(app, "/deferred")).json() == {"refused": ""}
    assert (await get(app, "/deferred")).json() == {"refused": "rate_limited"}


async def test_no_limiter_means_no_limit() -> None:
    app = build(CountingValkey())
    setattr(app.state, RATE_LIMITER_STATE, None)
    assert [(await get(app, "/closed")).status_code for _ in range(3)] == [200, 200, 200]


@pytest.mark.parametrize("name", ["ip_rate_limit.<locals>.dependency"])
def test_the_dependency_names_itself_for_route_walks(name: str) -> None:
    """Route-walk tests find limited routes by the dependency's qualified name."""
    assert ip_rate_limit("g", 1).__qualname__ == name
