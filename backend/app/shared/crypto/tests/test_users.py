"""The "who still uses key X" hook (ADR-048): refuses only when a registered user counts items."""

from collections.abc import Iterator

import pytest

from app.shared.crypto import (
    KeyStillInUseError,
    key_users,
    refuse_if_still_used,
    register_key_user,
    unregister_key_user,
)

RING = "test-ring"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    for name in key_users(RING):
        unregister_key_user(RING, name)


async def test_with_no_registered_user_nothing_refuses() -> None:
    await refuse_if_still_used(RING, ["k1", "k2"])


async def test_a_user_counting_items_under_a_removed_key_refuses() -> None:
    counts = {"k1": 3}

    async def fake(key_id: str) -> int:
        return counts.get(key_id, 0)

    register_key_user(RING, "fake_fields", fake)
    await refuse_if_still_used(RING, ["k0"])  # nothing under k0
    with pytest.raises(KeyStillInUseError) as refused:
        await refuse_if_still_used(RING, ["k0", "k1"])
    assert refused.value.code == "test-ring_key_still_in_use"
    assert (refused.value.key_id, refused.value.user, refused.value.count) == (
        "k1",
        "fake_fields",
        3,
    )
    assert "'k1'" in str(refused.value)


async def test_other_rings_users_are_not_asked() -> None:
    async def always(key_id: str) -> int:
        del key_id
        return 1

    register_key_user("other-ring", "x", always)
    try:
        await refuse_if_still_used(RING, ["k1"])
    finally:
        unregister_key_user("other-ring", "x")
