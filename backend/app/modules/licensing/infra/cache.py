"""Per-tenant entitlement cache in Valkey (WP-009).

Two keys per tenant:

    <prefix>ent:<tenant_id>      {"gen": 3, "data": Entitlement.to_dict()}, with a TTL
                                 (SUPPORTX_ENTITLEMENT_CACHE_TTL_SECONDS)
    <prefix>ent:gen:<tenant_id>  generation counter, bumped by every invalidation

The `licensing__invalidate_cache` consumer bumps the generation when `licensing.entitlement.changed`
arrives, so every API process sees a plan change within the event latency. An entry is used only
if its generation is still current: a request that read the old plan just before the change and
writes it back just after the invalidation stores a dead entry instead of resurrecting the old
plan for a whole TTL. The TTL only bounds staleness if an event were lost.

Valkey trouble never decides an entitlement: a failed read falls through to the provider and a
failed write is ignored.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import valkey.exceptions

from app.core.logging import get_logger
from app.modules.licensing.domain.entitlement import Entitlement

log = get_logger(__name__)


def cache_key(prefix: str, tenant_id: uuid.UUID) -> str:
    """Valkey key of one tenant's cached entitlement."""
    return f"{prefix}ent:{tenant_id}"


def generation_key(prefix: str, tenant_id: uuid.UUID) -> str:
    """Valkey key of one tenant's cache generation."""
    return f"{prefix}ent:gen:{tenant_id}"


@dataclass(frozen=True)
class Lookup:
    """A cache read: the entitlement (None on a miss) and the generation to store under."""

    entitlement: Entitlement | None
    generation: int


class EntitlementCache(Protocol):
    """Where loaded entitlements are kept between requests."""

    async def lookup(self, tenant_id: uuid.UUID) -> Lookup:
        """The cached entitlement if current, plus the current generation."""
        ...

    async def put(self, tenant_id: uuid.UUID, entitlement: Entitlement, generation: int) -> None:
        """Store an entitlement loaded while `generation` was current."""
        ...

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Make every stored entry of the tenant stale."""
        ...


class NoCache:
    """No caching (no Valkey configured, or TTL 0)."""

    async def lookup(self, tenant_id: uuid.UUID) -> Lookup:
        """Always a miss."""
        del tenant_id
        return Lookup(None, 0)

    async def put(self, tenant_id: uuid.UUID, entitlement: Entitlement, generation: int) -> None:
        """Nothing to store."""
        del tenant_id, entitlement, generation

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Nothing to drop."""
        del tenant_id


_VALKEY_ERRORS = (valkey.exceptions.ValkeyError, OSError)


class ValkeyEntitlementCache:
    """Shared cache for all API processes of a cell."""

    def __init__(
        self,
        client: Any,  # noqa: ANN401 - valkey.asyncio.Valkey; valkey-py ships no type hints
        *,
        prefix: str,
        ttl_seconds: int,
    ) -> None:
        self.client = client
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds

    async def lookup(self, tenant_id: uuid.UUID) -> Lookup:
        """Cached entitlement if its generation is current; a Valkey error counts as a miss."""
        try:
            raw, gen = await self.client.mget(
                cache_key(self.prefix, tenant_id), generation_key(self.prefix, tenant_id)
            )
        except _VALKEY_ERRORS:
            log.warning("entitlement_cache_unavailable", operation="get")
            return Lookup(None, -1)  # -1: never matches, so nothing is stored either
        generation = int(gen or 0)
        if raw is None:
            return Lookup(None, generation)
        entry = json.loads(raw)
        if entry.get("gen") != generation:
            return Lookup(None, generation)
        return Lookup(Entitlement.from_dict(entry["data"]), generation)

    async def put(self, tenant_id: uuid.UUID, entitlement: Entitlement, generation: int) -> None:
        """Store with the TTL; errors are logged and ignored."""
        if generation < 0:
            return
        entry = {"gen": generation, "data": entitlement.to_dict()}
        try:
            await self.client.set(
                cache_key(self.prefix, tenant_id), json.dumps(entry), ex=self.ttl_seconds
            )
        except _VALKEY_ERRORS:
            log.warning("entitlement_cache_unavailable", operation="put")

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Bump the generation and drop the entry. Errors propagate: the consumer retries."""
        await self.client.incr(generation_key(self.prefix, tenant_id))
        await self.client.delete(cache_key(self.prefix, tenant_id))
