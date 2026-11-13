"""The per-process cache of unwrapped data keys, and how erasure empties it everywhere (ADR-050).

Unwrapping a data key costs a query and an AES operation, so `open` keeps them in a bounded LRU
(about 1,000 keys), in memory only: never logged, pickled or put in Valkey. Rotation needs no
invalidation (a data key's value never changes for its ID). Tenant erasure must empty every
process's cache at once, so each entry carries the tenant's **generation** when it was read
(lane B's conditions, 2026-11-13):

1. The generation is a random token in Valkey (`fields:generation:<tenant>`), never a counter:
   a key Valkey lost and recreated can never repeat a value an old entry still holds.
2. Every hit compares its generation with Valkey's; a different or a missing one is a miss.
3. Erasure bumps it before and again after the transaction that destroys the data keys commits
   (`destroy_tenant_keys`): a process that read the old key in between cached it under a
   generation that is gone by the time the erasure is done.
4. Erasure is not done until the last bump succeeds: with Valkey unreachable it raises, and the
   erasure job retries or fails, never reports done while a cache could still hit.
5. Every entry also expires after ENTRY_TTL, a backstop whatever else happens.

Valkey unreachable while opening: the cache is bypassed (the data key is read from the database
each time), never a stale hit.
"""

import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import valkey.exceptions

from app.core.logging import get_logger

log = get_logger(__name__)

MAX_ENTRIES = 1000
ENTRY_TTL_SECONDS = 300.0
_PREFIX = "fields:generation:"


class GenerationsUnavailable(Exception):
    """Valkey did not answer: open bypasses the cache; erasure is not done."""


class Generations(Protocol):
    """Where each tenant's generation token lives (Valkey; a fake in tests)."""

    async def current(self, tenant_id: uuid.UUID) -> str | None:
        """The tenant's token, None when there is none (never set, or Valkey lost it)."""
        ...

    async def ensure(self, tenant_id: uuid.UUID) -> str:
        """The tenant's token, made (a new random one) when there is none."""
        ...

    async def bump(self, tenant_id: uuid.UUID) -> str:
        """A new random token for the tenant: every cached data key of it misses from now on."""
        ...


class ValkeyGenerations:
    """`Generations` in Valkey: one key per tenant holding a random token, kept without expiry."""

    def __init__(self, client: Any) -> None:  # noqa: ANN401 - valkey.asyncio.Valkey (no type hints)
        self._client = client

    async def current(self, tenant_id: uuid.UUID) -> str | None:  # noqa: D102 - see Generations
        try:
            value = await self._client.get(_PREFIX + str(tenant_id))
        except (valkey.exceptions.ValkeyError, OSError) as exc:
            raise GenerationsUnavailable from exc
        return None if value is None else bytes(value).decode()

    async def ensure(self, tenant_id: uuid.UUID) -> str:  # noqa: D102
        token = uuid.uuid4().hex
        try:
            await self._client.set(_PREFIX + str(tenant_id), token, nx=True)
            value = await self._client.get(_PREFIX + str(tenant_id))
        except (valkey.exceptions.ValkeyError, OSError) as exc:
            raise GenerationsUnavailable from exc
        return token if value is None else bytes(value).decode()

    async def bump(self, tenant_id: uuid.UUID) -> str:  # noqa: D102
        token = uuid.uuid4().hex
        try:
            await self._client.set(_PREFIX + str(tenant_id), token)
        except (valkey.exceptions.ValkeyError, OSError) as exc:
            raise GenerationsUnavailable from exc
        return token


@dataclass
class _Entry:
    generation: str
    expires_at: float
    secret: bytes


class DataKeyCache:
    """Unwrapped data keys by (tenant, data key ID), each under the generation it was read in."""

    def __init__(
        self,
        generations: Generations,
        *,
        max_entries: int = MAX_ENTRIES,
        ttl_seconds: float = ENTRY_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._generations = generations
        self._max = max_entries
        self._ttl = ttl_seconds
        self._monotonic = monotonic
        self._entries: OrderedDict[tuple[uuid.UUID, uuid.UUID], _Entry] = OrderedDict()

    def __repr__(self) -> str:
        """How many keys it holds, never the keys."""
        return f"DataKeyCache({len(self._entries)} keys)"  # never the keys themselves

    async def data_key(
        self, tenant_id: uuid.UUID, key_id: uuid.UUID, load: Callable[[], Awaitable[bytes]]
    ) -> bytes:
        """The data key: from the cache while its generation and TTL hold, else `load()`."""
        try:
            generation = await self._generations.current(tenant_id)
            if generation is None:
                generation = await self._generations.ensure(tenant_id)
        except GenerationsUnavailable:
            log.warning("field_key_cache_bypassed", reason="valkey_unavailable")
            return await load()
        now = self._monotonic()
        entry = self._entries.get((tenant_id, key_id))
        if entry is not None and entry.generation == generation and now < entry.expires_at:
            self._entries.move_to_end((tenant_id, key_id))
            return entry.secret
        secret = await load()
        self._entries[(tenant_id, key_id)] = _Entry(generation, now + self._ttl, secret)
        self._entries.move_to_end((tenant_id, key_id))
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)
        return secret

    def __len__(self) -> int:
        """How many keys it holds."""
        return len(self._entries)


async def destroy_tenant_keys(
    generations: Generations, tenant_id: uuid.UUID, destroy: Callable[[], Awaitable[None]]
) -> None:
    """Crypto-shredding of a tenant (ADR-050 item 7) with every cache emptied (lane B 2-4).

    `destroy` deletes the tenant's data keys and commits. The generation moves before it and
    again after it; a GenerationsUnavailable from either bump means the erasure is NOT done
    (the caller's job retries or fails).
    """
    await generations.bump(tenant_id)
    await destroy()
    await generations.bump(tenant_id)
