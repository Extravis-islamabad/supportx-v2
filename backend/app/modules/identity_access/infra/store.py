"""Server-side storage for BFF sessions and pending logins (Valkey, encrypted).

Keys are SHA-256 hashes of the cookie/state values, so a Valkey dump reveals neither usable
session IDs nor tokens (the values are AES-GCM encrypted).
"""

import hashlib
import secrets
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
# A mobile sign-in's one-time hand-off code (ADR-044): the session it stands for, briefly.
HANDOFF_PREFIX = "sx:handoff:"
LIMIT_PREFIX = "sx:limit:"
# A person's sessions, listed for My account and admins (ADR-044 item 5): one hash per person,
# field = the session's public id, value = its description, encrypted.
INDEX_PREFIX = "sx:user-sessions:"
# Dev-only quick sign-in (D-151): which TOTP time steps a persona's codes were sent for.
QUICK_STEP_PREFIX = "sx:dev-quick-step:"


def _hashed(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode()).hexdigest()


def public_id(session_id: str) -> str:
    """A session's id for lists and revocation: derived from it, but never usable as it."""
    return hashlib.sha256(f"pub:{session_id}".encode()).hexdigest()[:32]


class KeyValue(Protocol):
    """The few Valkey operations the store needs (fake in unit tests)."""

    async def get(self, key: str) -> bytes | None: ...  # noqa: D102 - mirrors Valkey
    async def getdel(self, key: str) -> bytes | None: ...  # noqa: D102
    async def set(  # noqa: D102
        self, key: str, value: bytes, *, px: int, nx: bool = False, xx: bool = False
    ) -> bool | None: ...
    async def delete(self, key: str) -> int: ...  # noqa: D102
    async def count(self, key: str, *, px: int) -> int: ...  # noqa: D102 - one more hit, kept px ms
    async def hset(self, key: str, field: str, value: bytes, *, px: int) -> None: ...  # noqa: D102 - field, then the key's TTL
    async def hgetall(self, key: str) -> dict[str, bytes]: ...  # noqa: D102
    async def hdel(self, key: str, field: str) -> int: ...  # noqa: D102
    async def delete_if(self, key: str, value: bytes) -> bool: ...  # noqa: D102 - only while it holds value


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

    async def set(  # noqa: D102
        self, key: str, value: bytes, *, px: int, nx: bool = False, xx: bool = False
    ) -> bool | None:
        result: bool | None = await self._client.set(key, value, px=px, nx=nx, xx=xx)
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
            # As long as the person's longest-lived session: a shorter one's save never cuts the
            # list's life (lane C's #249 review). NX sets it on a new index; GT only lengthens it
            # (a key without a TTL counts as infinite for GT, so GT alone would never set one).
            pipe.pexpire(key, px, nx=True)
            pipe.pexpire(key, px, gt=True)
            await pipe.execute()

    async def hgetall(self, key: str) -> dict[str, bytes]:  # noqa: D102
        # valkey-py's stubs type it sync-or-async; the asyncio client always returns an awaitable.
        found = await cast("Awaitable[dict[bytes | str, bytes]]", self._client.hgetall(key))
        return {(k.decode() if isinstance(k, bytes) else k): v for k, v in found.items()}

    async def hdel(self, key: str, field: str) -> int:  # noqa: D102
        return await cast("Awaitable[int]", self._client.hdel(key, field))

    async def delete_if(self, key: str, value: bytes) -> bool:  # noqa: D102
        # valkey-py's stubs type eval's result as sync-or-async and its args as str only; the
        # async client returns an awaitable and sends bytes as they are.
        pending = cast("Awaitable[int]", self._client.eval(_DELETE_IF, 1, key, value))  # type: ignore[arg-type]
        return bool(await pending)


# Compare and delete in one step: a lock is released only by the holder that set it.
_DELETE_IF = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


class SessionStore:
    """Encrypted session and login-state records with TTLs."""

    def __init__(self, kv: KeyValue, cipher: SessionCipher) -> None:
        self._kv = kv
        self._cipher = cipher

    async def put_session(
        self,
        session_id: str,
        data: dict[str, Any],
        ttl: timedelta,
        *,
        only_if_present: bool = False,
    ) -> bool:
        """Store (or replace) a session record until `ttl` elapses, and list it for its person.

        `only_if_present` (SET XX): replace the record only if it still exists, and return False
        when it does not. A refresh or a touch must never bring back a session someone signed out
        while the request was in flight (lane C's #451 review).

        Every save (sign-in, refresh, tenant switch) updates the person's list, so "last used"
        is the last save. A deleted or rotated session leaves a stale entry, which the list
        drops when it finds the session gone (`user_sessions`).
        """
        key = _hashed(SESSION_PREFIX, session_id)
        written = await self._kv.set(
            key, self._cipher.encrypt(data, bound_to=key), px=_ms(ttl), xx=only_if_present
        )
        if only_if_present and not written:
            return False  # gone: never listed again either
        tenant, user = data.get("tenant_id"), data.get("user_id")
        if tenant and user:
            index = _hashed(INDEX_PREFIX, f"{tenant}:{user}")
            field = public_id(session_id)
            meta = {
                "key": key,
                # A mobile session signs in through the console or portal client (ADR-044), but
                # the person's list names the phone: its platform is set on mobile sessions only.
                "client": "mobile" if data.get("device_platform") else data.get("client"),
                "created_at": data.get("created_at"),
                "last_seen_at": data.get("last_seen_at"),
                "platform": data.get("device_platform"),
                "app_version": data.get("app_version"),
                # Where it signed in and on what (REQ-SEC-030): shown to its owner and tenant
                # admins only (lane B), sealed like the rest of the entry.
                "ip": data.get("sign_in_ip"),
                "device": data.get("device"),
                "place": data.get("place"),
            }
            sealed = self._cipher.encrypt(meta, bound_to=f"{index}:{field}")
            await self._kv.hset(index, field, sealed, px=_ms(ttl))
        return True

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

    async def keycloak_session_in_use(self, user_key: str, keycloak_session_id: str) -> bool:
        """Whether a live session of this person still holds that Keycloak session (ADR-051).

        The console and portal of one browser share a Keycloak session, and signing in again
        just as Keycloak returns may reuse it: a delayed end must never cut either. A session
        begun before the person's sessions were ended (deactivation) is not live and never counts.
        """
        ended = await self.user_sessions_ended(user_key)
        for _field, meta in await self.user_sessions(user_key):
            key = str(meta.get("key"))
            blob = await self._kv.get(key)
            record = self._cipher.decrypt(blob, bound_to=key) if blob else None
            if record is None or record.get("keycloak_session_id") != keycloak_session_id:
                continue
            if ended is not None and datetime.fromisoformat(record["created_at"]) <= ended:
                continue
            return True
        return False

    async def keycloak_session_ids(self, user_key: str) -> list[str]:
        """The Keycloak session IDs held by a person's live sessions, sorted, each once.

        ADR-052 step 1: each is then ended through ADR-051's path.
        """
        found: set[str] = set()
        for _field, meta in await self.user_sessions(user_key):
            key = str(meta.get("key"))
            blob = await self._kv.get(key)
            record = self._cipher.decrypt(blob, bound_to=key) if blob else None
            session_id = record.get("keycloak_session_id") if record else None
            if session_id:
                found.add(str(session_id))
        return sorted(found)

    async def end_listed_session(self, user_key: str, session: str) -> bool:
        """End one of a person's sessions by its public id; False when it isn't theirs or live."""
        return await self.take_listed_session(user_key, session) is not None

    async def take_listed_session(self, user_key: str, session: str) -> dict[str, Any] | None:
        """End one of a person's sessions by its public id and return its record (WP-057 S2a).

        Only within the person's own index, so another person's id is never found (404). The
        record comes back (empty if it could not be read) so its Keycloak session can be ended
        too; None when it isn't theirs or live.
        """
        index = _hashed(INDEX_PREFIX, user_key)
        for field, meta in await self.user_sessions(user_key):
            if field == session:
                key = str(meta["key"])
                blob = await self._kv.get(key)
                data = self._cipher.decrypt(blob, bound_to=key) if blob else None
                await self._kv.delete(key)
                await self._kv.hdel(index, field)
                return data or {}
        return None

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

    async def claim_totp_step(self, email: str, step: int, ttl: timedelta) -> bool:
        """Claim one TOTP time step for a persona, once (SET NX): never the same code twice."""
        claimed = await self._kv.set(
            _hashed(QUICK_STEP_PREFIX, f"{email.lower()}:{step}"), b"1", px=_ms(ttl), nx=True
        )
        return bool(claimed)

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

    async def put_handoff(self, code: str, data: dict[str, Any], ttl: timedelta) -> None:
        """Remember a mobile hand-off code (the session ID and its challenge), encrypted."""
        key = _hashed(HANDOFF_PREFIX, code)
        await self._kv.set(key, self._cipher.encrypt(data, bound_to=key), px=_ms(ttl))

    async def take_handoff(self, code: str) -> dict[str, Any] | None:
        """Fetch and delete a hand-off code: usable exactly once, even when the exchange fails."""
        key = _hashed(HANDOFF_PREFIX, code)
        blob = await self._kv.getdel(key)
        return self._cipher.decrypt(blob, bound_to=key) if blob else None

    async def peek_login(self, state: str) -> dict[str, Any] | None:
        """Read a pending login without spending it (where a refused callback goes back to)."""
        key = _hashed(LOGIN_PREFIX, state)
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

    async def lock(self, session_id: str, ttl: timedelta) -> str | None:
        """Short exclusive lock (token refresh): the holder's token, or None if another holds it.

        Safe under the Valkey client's retry (app/core/valkey.py): when the first SET NX ran but
        its reply was lost, the retry finds the key, and the key holding this attempt's own token
        means the lock is ours.
        """
        key = _hashed(LOCK_PREFIX, session_id)
        token = secrets.token_hex(16).encode()
        if await self._kv.set(key, token, px=_ms(ttl), nx=True):
            return token.decode()
        return token.decode() if await self._kv.get(key) == token else None

    async def unlock(self, session_id: str, token: str) -> None:
        """Release `lock`, only while this holder still has it (never another's after the TTL)."""
        await self._kv.delete_if(_hashed(LOCK_PREFIX, session_id), token.encode())


def _ms(ttl: timedelta) -> int:
    return max(1, int(ttl.total_seconds() * 1000))
