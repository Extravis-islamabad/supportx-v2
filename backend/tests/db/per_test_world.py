"""The per-test incident `world`, under the names tests/db/shared_world exports (the opt-out).

A file on the module app imports `MODULE_LOOP, module_world, shared_world` from
tests.db.shared_world. If it turns flaky there, change that one import to this module: its
tests then build their own app per test again, on their own event loop, as before
(coordinator, 2026-11-10: a flake is reverted at once, never left in).
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from tests.db.test_incidents_api import World, incidents_world
from tooling.db_testing import ThrowawayDatabase

__all__ = ["MODULE_LOOP", "module_world", "shared_world"]

MODULE_LOOP = pytest.mark.per_test_world  # a label only: each test keeps its own event loop


@pytest.fixture
def module_world() -> None:
    """Nothing is shared per module here."""


@pytest_asyncio.fixture(name="world")
async def shared_world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    """A new app and two new organisations for every test (tests/db/test_incidents_api)."""
    async with incidents_world(migrated_db) as built:
        yield built
