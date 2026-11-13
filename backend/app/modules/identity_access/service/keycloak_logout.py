"""Ending a Keycloak session in the background after a sign-out it missed (ADR-051).

A sign-out never waits for Keycloak: the SupportX session ends at once (auth.py `logout`). When
Keycloak could not be reached, `keycloak_session.end_pending` went into the outbox with the
sign-out, and this consumer ends that one Keycloak session through the admin API (identity
service account, manage-users) once Keycloak answers. No token is kept anywhere for it.

Retries are the consumer worker's own (nak with backoff, up to MAX_ATTEMPTS). After GIVE_UP_AFTER
it stops and says so in the audit log: by then Keycloak's idle timeout (30 minutes in the shipped
realm) has ended the session anyway, since nothing refreshes it once SupportX's session is gone.
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.audit import WORKER, AuditActorType, AuditOutcome, record
from app.modules.identity_access.events import KeycloakSessionEndPending
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminNotConfigured,
    IdentityAdminRefused,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)
from app.modules.identity_access.service.worker_sessions import (
    KeycloakSessionInUse,
    worker_keycloak_session_in_use,
)
from app.shared.clock import Clock, system_clock
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)

ACTION = "session.keycloak_ended"
GIVE_UP_AFTER = timedelta(hours=1)
# With the worker's default backoff (1 s doubling, capped at 60 s) 100 attempts span about 95
# minutes, so the GIVE_UP_AFTER check, not the dead-letter stream, ends a long outage.
MAX_ATTEMPTS = 100


class SessionEnder(Protocol):
    """The part of Keycloak's admin API this needs (a fake in tests)."""

    async def end_session(self, session_id: str) -> bool:  # noqa: D102 - see KeycloakAdmin
        ...

    async def close(self) -> None:  # noqa: D102 - see KeycloakAdmin
        ...


# Swapped by tests; the identity service account, or None where it is not set up.
admin_factory: Callable[[Settings], SessionEnder | None] = KeycloakAdmin.from_settings
# Whether a live SupportX session still holds the Keycloak session (lane C, #481); swapped by tests.
in_use_factory: Callable[[Settings], KeycloakSessionInUse | None] = worker_keycloak_session_in_use
clock: Clock = system_clock


async def on_end_pending(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: end the Keycloak session a sign-out could not end; audit the outcome.

    Raises (so the worker retries with backoff) while Keycloak is unreachable and the event is
    younger than GIVE_UP_AFTER. Idempotent: the worker's claim skips a repeated event, and a
    session Keycloak no longer has counts as ended.
    """
    assert session is not None  # noqa: S101 - transactional consumer
    pending = KeycloakSessionEndPending.model_validate(envelope.payload)
    settings = get_settings()
    in_use = in_use_factory(settings)
    if in_use is not None and await in_use(
        envelope.tenant_id, pending.user_id, pending.keycloak_session_id
    ):
        # The browser's other app (console or portal) shares it, or the person signed in again
        # just as Keycloak returned and got the same session: ending it would sign them out.
        await _audit(session, pending.user_id, AuditOutcome.DONE, "still_in_use")
        return
    admin = admin_factory(settings)
    if admin is None:  # no identity service account: nothing can end it from here
        log.warning("keycloak_session_end_not_configured", tenant_id=str(envelope.tenant_id))
        await _audit(session, pending.user_id, AuditOutcome.FAILED, "not_configured")
        return
    try:
        ended = await admin.end_session(pending.keycloak_session_id)
    except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
        if clock.now() - envelope.occurred_at < GIVE_UP_AFTER:
            log.info("keycloak_session_end_retry", tenant_id=str(envelope.tenant_id))
            raise
        log.warning("keycloak_session_end_given_up", tenant_id=str(envelope.tenant_id))
        await _audit(session, pending.user_id, AuditOutcome.FAILED, "gave_up")
        return
    except IdentityAdminRefused as refused:  # a 4xx other than 404: retrying cannot help
        log.warning("keycloak_session_end_refused", status=refused.status)
        await _audit(session, pending.user_id, AuditOutcome.FAILED, "refused")
        return
    finally:
        await admin.close()
    await _audit(session, pending.user_id, AuditOutcome.DONE, "ended" if ended else "already_ended")


async def _audit(
    session: AsyncSession, user_id: uuid.UUID, outcome: AuditOutcome, result: str
) -> None:
    """One entry; `details.outcome` picks the screen's wording (audit.decision.*), `result` why."""
    await record(
        session,
        action_code=ACTION,
        facts=WORKER,
        outcome=outcome,
        object_type="user",
        object_id=user_id,
        details={
            "outcome": "ended" if result in ("ended", "already_ended") else "not_ended",
            "result": result,
        },
        actor=(AuditActorType.SYSTEM, None),
        clock=clock,
    )


KEYCLOAK_SESSION_END = ConsumerSpec(
    name="identity_access__keycloak_session_end",
    event_types=(KeycloakSessionEndPending.event_type,),
    handler=on_end_pending,
    max_attempts=MAX_ATTEMPTS,
)
