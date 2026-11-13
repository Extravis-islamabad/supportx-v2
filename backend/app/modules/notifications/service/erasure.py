"""A person's notifications go when they are erased (GDPR; WP-056, found by lane C).

On `identity_access.user.status_changed` with reason `erasure`, the person's in-app entries
(the account-security ones carry a device and a city) and their delivery rows are deleted, and
they are taken off any rule that names them. Per tenant (the event's tenant session, RLS),
idempotent (deleting what is already gone changes nothing), and only for an erasure: a plain
deactivation keeps the person's history for the admins who look at it.

Their e-mails' content lives in the mail sender's own queue and goes with its retention purge
(`mail_content_retention_days`); nothing here holds it.
"""

import uuid

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.notifications.infra.models import (
    Notification,
    NotificationDelivery,
    NotificationRule,
)
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)
ERASURE = "erasure"


async def forget(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    """Delete the person's deliveries and in-app entries; (deliveries, entries) removed."""
    deliveries = await session.execute(
        delete(NotificationDelivery).where(NotificationDelivery.user_id == user_id)
    )
    entries = await session.execute(delete(Notification).where(Notification.user_id == user_id))
    # Rules that name the person: they are no longer anyone to tell.
    await session.execute(
        update(NotificationRule)
        .where(NotificationRule.user_ids.contains([user_id]))
        .values(user_ids=func.array_remove(NotificationRule.user_ids, user_id))
    )
    return (
        int(getattr(deliveries, "rowcount", 0) or 0),
        int(getattr(entries, "rowcount", 0) or 0),
    )


async def on_user_status_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Only an erasure: a deactivated person's notifications stay for the record."""
    payload = envelope.payload
    if session is None or payload.get("status") != "disabled" or payload.get("reason") != ERASURE:
        return
    removed = await forget(session, uuid.UUID(str(payload["user_id"])))
    # Counts only, never what they said (the person is being forgotten).
    log.info("notifications_erased", deliveries=removed[0], entries=removed[1])


ERASED = ConsumerSpec(
    name="notifications__erasure",
    event_types=("identity_access.user.status_changed",),
    handler=on_user_status_changed,
)
