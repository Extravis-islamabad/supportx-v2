"""Rate limiting against real Valkey (WP-008).

Valkey: SUPPORTX_TEST_VALKEY_URL, else the dev stack's. Each test uses a random key prefix and
deletes only the keys it created. Skips locally without Valkey; SUPPORTX_REQUIRE_VALKEY_TESTS=1
(CI) turns that into a failure.
"""

import os
import secrets
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
import valkey.asyncio
from httpx import ASGITransport, AsyncClient

from app.core.tenancy import SESSION_RESOLVER_STATE
from app.main import create_app
from app.shared.api.ratelimit import RateLimiter, SettingsPolicyProvider
from conftest import create_tenant, make_settings
from tests.db.test_users_api import fake_session, seed_users
from tooling import db_testing

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = [pytest.mark.db, pytest.mark.valkey]


def valkey_url() -> str | None:
    if url := os.environ.get("SUPPORTX_TEST_VALKEY_URL"):
        return url
    if db_testing.STACK_ENV.is_file():
        env = db_testing._read_env_file(db_testing.STACK_ENV)  # noqa: SLF001 - shared test helper
        return f"valkey://:{env['VALKEY_PASSWORD']}@127.0.0.1:{env['VALKEY_PORT']}/0"
    return None


async def _pings(client: Any) -> bool:  # noqa: ANN401 - untyped valkey client
    try:
        return bool(await client.ping())
    except (OSError, valkey.exceptions.ValkeyError):
        return False


@pytest_asyncio.fixture
async def valkey_client() -> AsyncIterator[tuple[Any, str]]:
    """(client, url) for a reachable Valkey; skips (or fails in CI) without one."""
    url = valkey_url()
    client: Any = valkey.asyncio.from_url(url) if url else None  # type: ignore[no-untyped-call]  # valkey-py ships no hints
    if client is None or not await _pings(client):
        reason = "Valkey is not reachable (make dev-up / SUPPORTX_TEST_VALKEY_URL)"
        if os.environ.get("SUPPORTX_REQUIRE_VALKEY_TESTS") == "1":
            pytest.fail(f"Valkey tests are required here but {reason}")
        pytest.skip(reason)
    assert url is not None
    yield client, url
    await client.aclose()


@pytest_asyncio.fixture
async def prefix(valkey_client: tuple[Any, str]) -> AsyncIterator[str]:
    """A key prefix of our own; its keys are removed afterwards."""
    client, _ = valkey_client
    value = f"test-{secrets.token_hex(4)}:"
    yield value
    async for key in client.scan_iter(match=f"{value}*"):
        await client.delete(key)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_800_000_040.0  # 40 s into a 60 s window

    def __call__(self) -> float:
        return self.now


async def test_user_budget_then_tenant_budget_then_reset(
    valkey_client: tuple[Any, str], prefix: str
) -> None:
    client, _ = valkey_client
    clock = FakeClock()
    limiter = RateLimiter(
        client,
        prefix=prefix,
        provider=SettingsPolicyProvider(
            make_settings(
                rate_limits={"default": {"user": 3, "tenant": 5}}, rate_limit_window_seconds=60
            )
        ),
        clock=clock,
    )
    tenant = uuid.uuid4()
    first = [await limiter.hit("users", tenant, "alice") for _ in range(4)]
    assert [d.allowed for d in first] == [True, True, True, False]
    assert [d.remaining for d in first] == [2, 1, 0, 0]
    assert first[0].reset_seconds == 20
    bob = [await limiter.hit("users", tenant, "bob") for _ in range(2)]
    assert [d.allowed for d in bob] == [True, False]  # tenant budget (5) is used up: 4 + 1
    assert bob[1].limit == 5  # headers report the tighter budget: the tenant's
    other_tenant = await limiter.hit("users", uuid.uuid4(), "alice")
    assert other_tenant.allowed  # tenants do not share budgets
    other_group = await limiter.hit("tickets", tenant, "alice")
    assert other_group.allowed  # route groups do not share budgets
    clock.now += 60
    assert (await limiter.hit("users", tenant, "alice")).allowed  # new window
    ttl = await client.ttl(f"{prefix}rl:users:{int(clock.now // 60)}:t:{tenant}")
    assert 0 < ttl <= 61  # keys expire with their window


@pytest_asyncio.fixture
async def limited_app(
    valkey_client: tuple[Any, str], prefix: str, migrated_db: db_testing.ThrowawayDatabase
) -> AsyncIterator[tuple[AsyncClient, dict[str, str]]]:
    _, url = valkey_client
    tenant = await create_tenant(migrated_db.migrator_url, "Limited")
    (tech,) = await seed_users(migrated_db, tenant, [{"user_type": "technician"}])
    settings = make_settings(
        database_url=migrated_db.app_url,
        valkey_url=url,
        valkey_key_prefix=prefix,
        rate_limits={"default": {"user": 100, "tenant": 1000}, "users": {"user": 3, "tenant": 100}},
    )
    app: FastAPI = create_app(settings)
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, {"X-Test-Tenant": str(tenant), "X-Test-User": str(tech)}


async def test_exhaustion_over_http_gives_429_with_headers(
    limited_app: tuple[AsyncClient, dict[str, str]],
) -> None:
    client, headers = limited_app
    responses = [await client.get("/api/v1/users", headers=headers) for _ in range(4)]
    assert [r.status_code for r in responses] == [200, 200, 200, 429]
    assert [r.headers["ratelimit-remaining"] for r in responses[:3]] == ["2", "1", "0"]
    assert responses[0].headers["ratelimit-limit"] == "3"
    assert responses[0].headers["ratelimit-policy"].startswith("3;w=")
    refused = responses[3]
    assert refused.json()["code"] == "rate_limited"
    assert int(refused.headers["retry-after"]) >= 1
    assert refused.json()["params"]["retry_after_seconds"] == int(refused.headers["retry-after"])
    assert refused.headers["content-type"] == "application/problem+json"


async def test_valkey_outage_fails_open(migrated_db: db_testing.ThrowawayDatabase) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Outage")
    (tech,) = await seed_users(migrated_db, tenant, [{"user_type": "technician"}])
    app: FastAPI = create_app(
        make_settings(database_url=migrated_db.app_url, valkey_url="valkey://127.0.0.1:1/0")
    )
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/users", headers={"X-Test-Tenant": str(tenant), "X-Test-User": str(tech)}
            )
    assert response.status_code == 200
    assert "ratelimit-limit" not in response.headers
