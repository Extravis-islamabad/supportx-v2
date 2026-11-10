"""One app per test module for the incident `world` (CI speed, coordinator 2026-11-10).

Building the app costs ~1.5 s locally (several on CI), and ~1,000 tests each built one. A file
opts in with:

    from tests.db.shared_world import MODULE_LOOP, module_world, shared_world

with `pytestmark = [..., MODULE_LOOP]`, so its tests run on the module's one event loop
(asyncpg pools belong to the loop that made them). Every test still gets two new
organisations (fresh tenants). What a test sets on `app.state` or in `dependency_overrides`
is put back after it. A file that turns flaky goes back to the per-test `world` in one line:
import the same three names from tests.db.per_test_world instead.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.tenancy import SESSION_RESOLVER_STATE
from app.main import create_app
from conftest import make_settings
from tests.db.test_access_api import fake_session
from tests.db.test_incidents_api import World, make_org
from tests.db.test_rate_limit import valkey_url
from tooling.db_testing import ThrowawayDatabase

__all__ = ["MODULE_LOOP", "module_world", "shared_world"]

MODULE_LOOP = pytest.mark.asyncio(loop_scope="module")


@dataclass
class ModuleWorld:
    """The module's app and client; `World`s are made from it per test."""

    client: AsyncClient
    db: ThrowawayDatabase
    app: FastAPI


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def module_world(migrated_db: ThrowawayDatabase) -> AsyncIterator[ModuleWorld]:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    app: FastAPI = create_app(
        make_settings(
            database_url=migrated_db.app_url,
            valkey_url=url,
            centrifugo_token_secret="incidents-test-secret-" + "x" * 16,
        )
    )
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield ModuleWorld(client, migrated_db, app)


@pytest_asyncio.fixture(name="world", loop_scope="module")
async def shared_world(module_world: ModuleWorld) -> AsyncIterator[World]:
    """Like `world`, on the module's app: new organisations, the app's state restored after."""
    app = module_world.app
    state = dict(app.state._state)  # noqa: SLF001 - Starlette keeps app.state in this dict
    overrides = dict(app.dependency_overrides)
    w = World(module_world.client, module_world.db, app, a=None, b=None)  # type: ignore[arg-type]  # set below
    try:
        w.a = await make_org(w, "Alpha")
        w.b = await make_org(w, "Beta")
        yield w
    finally:
        app.state._state.clear()  # noqa: SLF001 - see above
        app.state._state.update(state)  # noqa: SLF001 - see above
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)
        cache = app.state.policy.cache
        prefix = app.state.settings.valkey_key_prefix
        keys = [k async for k in cache.client.scan_iter(match=f"{prefix}*")]
        if keys:
            await cache.client.delete(*keys)
