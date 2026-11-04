"""Ending a person's sessions from a worker (WP-040 session 2: directory leavers, REQ-INT-064).

The API ends sessions through its AuthService (`auth.end_sessions`). A worker has no request and
no AuthService, so this builds the two parts it needs from settings: the session store's "ended"
marker in Valkey (their next request gets 401) and a Centrifugo disconnect (their live screens
close). Both are best effort after the commit; signing in again is refused by the database row
either way.
"""

import uuid
from collections.abc import Awaitable, Callable

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.valkey import client as valkey_client
from app.modules.identity_access.infra.crypto import SessionCipher
from app.modules.identity_access.infra.store import SessionStore, ValkeyKeyValue
from app.modules.identity_access.service.auth import MAX_SESSION, user_key
from app.shared.clock import system_clock
from app.shared.realtime import SESSION_ENDED, CentrifugoClient, CentrifugoError, realtime_user

log = get_logger(__name__)

TenantSessionEnder = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]


def worker_session_ender(settings: Settings) -> TenantSessionEnder | None:
    """`end(tenant_id, user_id)`, or None where sessions are not configured (tests, dev)."""
    if settings.valkey_url is None or settings.session_secret is None:
        return None
    secret = settings.session_secret.get_secret_value()

    async def end(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        kv = valkey_client(settings)
        try:
            store = SessionStore(ValkeyKeyValue(kv), SessionCipher(secret))
            await store.end_user_sessions(
                user_key(str(tenant_id), str(user_id)), system_clock.now(), MAX_SESSION
            )
        finally:
            await kv.aclose()
        realtime = CentrifugoClient.from_settings(settings)
        if realtime is None:
            return
        try:
            await realtime.disconnect(
                realtime_user(tenant_id, user_id), SESSION_ENDED, "access ended"
            )
        except CentrifugoError:
            log.warning("realtime_disconnect_failed", exc_info=True)
        finally:
            await realtime.aclose()

    return end
