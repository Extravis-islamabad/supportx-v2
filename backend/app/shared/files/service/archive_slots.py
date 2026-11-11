"""At most two archive downloads at once per person (WP-046a S2; lane B's rule).

A sorted set per person in Valkey: each running download holds a member, its random token, with
its expiry as the score. Taking a slot drops expired members, counts what is left, and adds its
token when under the cap; the download gives it back in `finally`. A crashed worker's slot frees
itself at its expiry. Retried commands are safe (app/core/valkey.py): ZADD of the same token, ZREM
of a token already gone and ZREMRANGEBYSCORE of what has expired change nothing a second time. A
race between two takes errs strict, never loose: the count is checked again after adding.

Without Valkey (a single-node install that runs none), there is no cap beyond the rate limit.
"""

import secrets
import time
import uuid
from typing import Any

from app.core.config import Settings
from app.core.valkey import client as valkey_client

MAX_RUNNING = 2
SLOT_SECONDS = 15 * 60  # a slot outlives the longest allowed download, then frees itself
NO_CAP = "no-cap"  # a marker, not a secret: no Valkey, so no slot to give back
_CLIENT: dict[str, Any] = {}


def _key(settings: Settings, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"{settings.valkey_key_prefix}files:archives:{tenant_id}:{user_id}"


def _client(settings: Settings) -> Any:  # noqa: ANN401 - valkey.asyncio.Valkey; valkey-py ships no type hints
    if settings.valkey_url is None:
        return None
    if "client" not in _CLIENT:  # one client per process, as the other Valkey users keep
        _CLIENT["client"] = valkey_client(settings)
    return _CLIENT["client"]


async def take(settings: Settings, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    """A slot's token, or None when the person already has two running."""
    client = _client(settings)
    if client is None:
        return NO_CAP
    key = _key(settings, tenant_id, user_id)
    now = time.time()
    await client.zremrangebyscore(key, "-inf", now)
    if await client.zcard(key) >= MAX_RUNNING:
        return None
    token = secrets.token_hex(16)
    await client.zadd(key, {token: now + SLOT_SECONDS})
    await client.expire(key, SLOT_SECONDS)
    if await client.zcard(key) > MAX_RUNNING:  # two took the last slot at once: this one yields
        await client.zrem(key, token)
        return None
    return token


async def give_back(
    settings: Settings, tenant_id: uuid.UUID, user_id: uuid.UUID, token: str
) -> None:
    """Free a slot (in `finally`)."""
    client = _client(settings)
    if client is None or token == NO_CAP:
        return
    await client.zrem(_key(settings, tenant_id, user_id), token)


__all__ = ["MAX_RUNNING", "give_back", "take"]
