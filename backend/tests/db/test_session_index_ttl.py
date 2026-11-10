"""A person's session index lives as long as their longest-lived session (lane C's #249 review).

Against a real Valkey: the fake key-value store has no TTLs. A new index gets its expiry (NX), a
longer session's save lengthens it, and a shorter session's save never cuts it (GT).
"""

from typing import Any

import pytest

from app.modules.identity_access.infra.store import ValkeyKeyValue
from tests.db.test_rate_limit import prefix, valkey_client

pytestmark = [pytest.mark.db, pytest.mark.valkey]
__all__ = ["prefix", "valkey_client"]  # fixtures, used by name

HOUR = 3_600_000


async def test_a_shorter_session_never_shortens_the_list(
    valkey_client: tuple[Any, str], prefix: str
) -> None:
    client, _ = valkey_client
    store = ValkeyKeyValue(client)
    index = f"{prefix}index"
    await store.hset(index, "long", b"1", px=8 * HOUR)
    first = await client.pttl(index)
    assert 7 * HOUR < first <= 8 * HOUR  # a new index gets its expiry
    await store.hset(index, "short", b"2", px=HOUR)
    assert await client.pttl(index) > 7 * HOUR  # the short one's save leaves it as it was
    await store.hset(index, "longer", b"3", px=12 * HOUR)
    assert await client.pttl(index) > 11 * HOUR  # a longer one lengthens it
