"""The data-key cache and its generation (ADR-050; lane B's conditions, 2026-11-13)."""

import uuid

import pytest

from app.shared.fields.cache import (
    DataKeyCache,
    GenerationsUnavailable,
    destroy_tenant_keys,
)

TENANT = uuid.UUID("00000000-0000-7000-8000-0000000000c1")
KEY = uuid.UUID("00000000-0000-7000-8000-0000000000d1")


class MemoryGenerations:
    """Valkey's tokens, in memory; `down` makes every call fail as an unreachable Valkey."""

    def __init__(self) -> None:
        self.tokens: dict[uuid.UUID, str] = {}
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise GenerationsUnavailable

    async def current(self, tenant_id: uuid.UUID) -> str | None:
        self._check()
        return self.tokens.get(tenant_id)

    async def ensure(self, tenant_id: uuid.UUID) -> str:
        self._check()
        return self.tokens.setdefault(tenant_id, uuid.uuid4().hex)

    async def bump(self, tenant_id: uuid.UUID) -> str:
        self._check()
        self.tokens[tenant_id] = uuid.uuid4().hex
        return self.tokens[tenant_id]


class Loads:
    """A data-key loader that counts its calls."""

    def __init__(self, secret: bytes = b"k" * 32) -> None:
        self.secret = secret
        self.count = 0

    async def __call__(self) -> bytes:
        self.count += 1
        return self.secret


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_a_hit_needs_the_same_generation_and_a_live_ttl() -> None:
    generations, clock, load = MemoryGenerations(), Clock(), Loads()
    cache = DataKeyCache(generations, ttl_seconds=300, monotonic=clock)
    assert await cache.data_key(TENANT, KEY, load) == load.secret
    assert await cache.data_key(TENANT, KEY, load) == load.secret
    assert load.count == 1  # the second came from the cache
    clock.now += 301  # the backstop TTL
    await cache.data_key(TENANT, KEY, load)
    assert load.count == 2


async def test_a_bump_or_a_lost_generation_is_a_miss() -> None:
    generations, load = MemoryGenerations(), Loads()
    cache = DataKeyCache(generations)
    await cache.data_key(TENANT, KEY, load)
    await generations.bump(TENANT)  # an erasure elsewhere
    await cache.data_key(TENANT, KEY, load)
    assert load.count == 2
    generations.tokens.clear()  # Valkey flushed: the key is gone
    await cache.data_key(TENANT, KEY, load)
    assert load.count == 3  # never a hit on a missing generation


async def test_the_generation_is_a_random_token_never_a_counter() -> None:
    generations = MemoryGenerations()
    first = await generations.bump(TENANT)
    second = await generations.bump(TENANT)
    assert first != second
    assert not first.isdigit()
    assert len(first) == 32  # a UUID's hex


async def test_valkey_down_bypasses_the_cache_never_a_stale_hit() -> None:
    generations, load = MemoryGenerations(), Loads()
    cache = DataKeyCache(generations)
    await cache.data_key(TENANT, KEY, load)
    generations.down = True
    await cache.data_key(TENANT, KEY, load)
    await cache.data_key(TENANT, KEY, load)
    assert load.count == 3  # read every time while Valkey does not answer


async def test_the_cache_is_bounded_and_says_nothing_of_its_keys() -> None:
    generations = MemoryGenerations()
    cache = DataKeyCache(generations, max_entries=2)
    for _ in range(5):
        await cache.data_key(TENANT, uuid.uuid4(), Loads(b"secret-material"))
    assert len(cache) == 2
    assert "secret-material" not in repr(cache)


async def test_erasure_moves_the_generation_before_and_after_and_fails_without_valkey() -> None:
    generations = MemoryGenerations()
    seen: list[str | None] = []

    async def destroy() -> None:
        seen.append(generations.tokens.get(TENANT))

    before = await generations.ensure(TENANT)
    await destroy_tenant_keys(generations, TENANT, destroy)
    assert seen[0] is not None
    assert seen[0] != before  # bumped before the destroy
    assert generations.tokens[TENANT] != seen[0]  # and again after it
    generations.down = True
    destroyed = False

    async def never() -> None:
        nonlocal destroyed
        destroyed = True

    with pytest.raises(GenerationsUnavailable):
        await destroy_tenant_keys(generations, TENANT, never)
    assert not destroyed  # not even started: the erasure is not done


async def test_a_failed_bump_after_the_destroy_still_fails_the_erasure() -> None:
    generations = MemoryGenerations()

    async def destroy_then_lose_valkey() -> None:
        generations.down = True

    with pytest.raises(GenerationsUnavailable):
        await destroy_tenant_keys(generations, TENANT, destroy_then_lose_valkey)
