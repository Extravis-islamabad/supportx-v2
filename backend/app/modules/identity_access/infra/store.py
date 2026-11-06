"""Server-side storage for BFF sessions and pending logins (Valkey, encrypted).

Keys are SHA-256 hashes of the cookie/state values, so a Valkey dump reveals neither usable
session IDs nor tokens (the values are AES-GCM encrypted).
"""

import hashlib
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast

from app.modules.identity_access.infra.crypto import SessionCipher

if TYPE_CHECKING:
    from collections.abc import Awaitable

    import valkey.asyncio

SESSION_PREFIX = "sx:session:"
LOGIN_PREFIX = "sx:login:"
LOCK_PREFIX = "sx:session-lock:"
# A person's sessions started before this moment are over (deactivation, sign-in turned off).
ENDED_PREFIX = "sx:sessions-ended:"
SSO_TEST_PREFIX = "sx:sso-test:"
LIMIT_PREFIX = "sx:limit:"
# A person's sessions, listed for My account and admins (ADR-044 item 5): one hash per person,
# field = the session's public id, value = its description, encrypted.
INDEX_PREFIX = "sx:user-sessions:"


def _hashed(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode()).hexdigest()


def public_id(session_id: str) -> str:
    """A session's id for lists and revocation: derived from it, but never usable as it."""
    return hashlib.sha256(f"pub:{session_id}".encode()).hexdigest()[:32]


class KeyValue(Protocol):
    """The few Valkey operations the store needs (fake in unit tests)."""

    async def get(self, key: str) -> bytes | None: ...  # noqa: D102 - mirrors Valkey
    async def getdel(self, key: str) -> bytes | None: ...  # noqa: D102
    async def set(self, key: str, value: bytes, *, px: int, nx: bool = False) -> bool | None: ...  # noqa: D102
    async def delete(self, key: str) -> int: ...  # noqa: D102
    async def count(self, key: str, *, px: int) -> int: ...  # noqa: D102 - one more hit, kept px ms
    async def hset(self, key: str, field: str, value: bytes, *, px: int) -> None: ...  # noqa: D102 - field, then the key's TTL
    async def hgetall(self, key: str) -> dict[str, bytes]: ...  # noqa: D102
    async def hdel(self, key: str, field: str) -> int: ...  # noqa: D102


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

    async def count(self, key: str, *, px: int) -> int:  # noqa: D102
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.pexpire(key, px, nx=True)
            hits, _ = await pipe.execute()
        return int(hits)

    async def hset(self, key: str, field: str, value: bytes, *, px: int) -> None:  # noqa: D102
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.hset(key, field, value)  # type: ignore[arg-type]  # valkey-py's stubs say str; bytes are stored as is
            pipe.pexpire(key, px)  # as long as the person's newest session
            await pipe.execute()

    async def hgetall(self, key: str) -> dict[str, bytes]:  # noqa: D102
        # valkey-py's stubs type it sync-or-async; the asyncio client always returns an awaitable.
        found = await cast("Awaitable[dict[bytes | str, bytes]]", self._client.hgetall(key))
        return {(k.decode() if isinstance(k, bytes) else k): v for k, v in found.items()}

    async def hdel(self, key: str, field: str) -> int:  # noqa: D102
        return await cast("Awaitable[int]", self._client.hdel(key, field))


class SessionStore:
    """Encrypted session and login-state records with TTLs."""

    def __init__(self, kv: KeyValue, cipher: SessionCipher) -> None:
        self._kv = kv
        self._cipher = cipher

    async def put_session(self, session_id: str, data: dict[str, Any], ttl: timedelta) -> None:
        """Store (or replace) a session record until `ttl` elapses, and list it for its person.

        Every save (sign-in, refresh, tenant switch) updates the person's list, so "last used"
        is the last save. A deleted or rotated session leaves a stale entry, which the list
        drops when it finds the session gone (`user_sessions`).
        """
        key = _hashed(SESSION_PREFIX, session_id)
        await self._kv.set(key, self._cipher.encrypt(data, bound_to=key), px=_ms(ttl))
        tenant, user = data.get("tenant_id"), data.get("user_id")
        if tenant and user:
            index = _hashed(INDEX_PREFIX, f"{tenant}:{user}")
            field = public_id(session_id)
            meta = {
                "key": key,
                "client": data.get("client"),
                "created_at": data.get("created_at"),
                "last_seen_at": data.get("last_seen_at"),
                "platform": data.get("device_platform"),
                "app_version": data.get("app_version"),
            }
            sealed = self._cipher.encrypt(meta, bound_to=f"{index}:{field}")
            await self._kv.hset(index, field, sealed, px=_ms(ttl))

    async def user_sessions(self, user_key: str) -> list[tuple[str, dict[str, Any]]]:
        """(public id, description) of a person's live sessions; stale entries are removed."""
        index = _hashed(INDEX_PREFIX, user_key)
        found: list[tuple[str, dict[str, Any]]] = []
        for field, sealed in (await self._kv.hgetall(index)).items():
            meta = self._cipher.decrypt(sealed, bound_to=f"{index}:{field}")
            if meta is None or await self._kv.get(str(meta.get("key"))) is None:
                await self._kv.hdel(index, field)  # ended, rotated or expired
                continue
            found.append((field, meta))
        return found

    async def end_listed_session(self, user_key: str, session: str) -> bool:
        """End one of a person's sessions by its public id; False when it isn't theirs or live."""
        index = _hashed(INDEX_PREFIX, user_key)
        for field, meta in await self.user_sessions(user_key):
            if field == session:
                await self._kv.delete(str(meta["key"]))
                await self._kv.hdel(index, field)
                return True
        return False

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

    async def hit(self, scope: str, subject: str, window: timedelta) -> int:
        """Count one more request of `subject` in the current `window`; the count so far."""
        bucket = int(time.time() // window.total_seconds())
        return await self._kv.count(
            _hashed(LIMIT_PREFIX, f"{scope}:{subject}:{bucket}"), px=_ms(window)
        )

    async def put_sso_test(self, test_id: str, data: dict[str, Any], ttl: timedelta) -> None:
        """Keep a single sign-on test's progress and result (WP-039), encrypted: it names people."""
        key = _hashed(SSO_TEST_PREFIX, test_id)
        await self._kv.set(key, self._cipher.encrypt(data, bound_to=key), px=_ms(ttl))

    async def get_sso_test(self, test_id: str) -> dict[str, Any] | None:
        """A test's record, or None when unknown or expired."""
        key = _hashed(SSO_TEST_PREFIX, test_id)
        blob = await self._kv.get(key)
        return self._cipher.decrypt(blob, bound_to=key) if blob else None

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
