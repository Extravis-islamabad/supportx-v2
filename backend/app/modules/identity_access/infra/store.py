"""Server-side storage for BFF sessions and pending logins (Valkey, encrypted).

Keys are SHA-256 hashes of the cookie/state values, so a Valkey dump reveals neither usable
session IDs nor tokens (the values are AES-GCM encrypted).
"""

import hashlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from app.modules.identity_access.infra.crypto import SessionCipher

if TYPE_CHECKING:
    import valkey.asyncio

SESSION_PREFIX = "sx:session:"
LOGIN_PREFIX = "sx:login:"
LOCK_PREFIX = "sx:session-lock:"
# A person's sessions started before this moment are over (deactivation, sign-in turned off).
ENDED_PREFIX = "sx:sessions-ended:"


def _hashed(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode()).hexdigest()


class KeyValue(Protocol):
    """The few Valkey operations the store needs (fake in unit tests)."""

    async def get(self, key: str) -> bytes | None: ...  # noqa: D102 - mirrors Valkey
    async def getdel(self, key: str) -> bytes | None: ...  # noqa: D102
    async def set(self, key: str, value: bytes, *, px: int, nx: bool = False) -> bool | None: ...  # noqa: D102
    async def delete(self, key: str) -> int: ...  # noqa: D102


class ValkeyKeyValue:
    """`KeyValue` over valkey-py."""

    def __init__(self, client: "valkey.asyncio.Valkey") -> None:
        self._client = client

    async def get(self, key: str) -> bytes | None:  # noqa: D102 - see KeyValue
        value: bytes | None = await self._client.get(key)
        return value

    async def getdel(self, key: str) -> bytes | None:  # noqa: D102
        value: bytes | None = await self._client.getdel(key)
        return value

    async def set(self, key: str, value: bytes, *, px: int, nx: bool = False) -> bool | None:  # noqa: D102
        result: bool | None = await self._client.set(key, value, px=px, nx=nx)
        return result

    async def delete(self, key: str) -> int:  # noqa: D102
        deleted: int = await self._client.delete(key)
        return deleted


class SessionStore:
    """Encrypted session and login-state records with TTLs."""

    def __init__(self, kv: KeyValue, cipher: SessionCipher) -> None:
        self._kv = kv
        self._cipher = cipher

    async def put_session(self, session_id: str, data: dict[str, Any], ttl: timedelta) -> None:
        """Store (or replace) a session record until `ttl` elapses."""
        key = _hashed(SESSION_PREFIX, session_id)
        await self._kv.set(key, self._cipher.encrypt(data, bound_to=key), px=_ms(ttl))

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """The session record, or None if unknown, expired or undecryptable."""
        key = _hashed(SESSION_PREFIX, session_id)
        blob = await self._kv.get(key)
        return self._cipher.decrypt(blob, bound_to=key) if blob else None

    async def delete_session(self, session_id: str) -> None:
        """Forget a session (logout, rotation, expiry)."""
        await self._kv.delete(_hashed(SESSION_PREFIX, session_id))

    async def put_login(self, state: str, data: dict[str, Any], ttl: timedelta) -> None:
        """Remember a pending login (PKCE verifier, nonce, returnTo) under its state value."""
        key = _hashed(LOGIN_PREFIX, state)
        await self._kv.set(key, self._cipher.encrypt(data, bound_to=key), px=_ms(ttl))

    async def take_login(self, state: str) -> dict[str, Any] | None:
        """Fetch and delete a pending login: each state is usable exactly once."""
        key = _hashed(LOGIN_PREFIX, state)
        blob = await self._kv.getdel(key)
        return self._cipher.decrypt(blob, bound_to=key) if blob else None

    async def end_user_sessions(self, user_key: str, at: datetime, ttl: timedelta) -> None:
        """Mark every session of a person begun up to `at` as ended (kept for `ttl`)."""
        await self._kv.set(_hashed(ENDED_PREFIX, user_key), at.isoformat().encode(), px=_ms(ttl))

    async def user_sessions_ended(self, user_key: str) -> datetime | None:
        """When a person's sessions were last ended, or None."""
        blob = await self._kv.get(_hashed(ENDED_PREFIX, user_key))
        return datetime.fromisoformat(blob.decode()) if blob else None

    async def lock(self, session_id: str, ttl: timedelta) -> bool:
        """Short exclusive lock (token refresh), True if acquired."""
        return bool(
            await self._kv.set(_hashed(LOCK_PREFIX, session_id), b"1", px=_ms(ttl), nx=True)
        )

    async def unlock(self, session_id: str) -> None:
        """Release `lock`."""
        await self._kv.delete(_hashed(LOCK_PREFIX, session_id))


def _ms(ttl: timedelta) -> int:
    return max(1, int(ttl.total_seconds() * 1000))
