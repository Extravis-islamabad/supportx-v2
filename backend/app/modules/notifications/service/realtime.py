"""Which notification events reach which screens, live (architecture.md §8; REQ-INC-131 AC1).

- the person's own channel: a new entry (the centre fetches it by ID), entries read on another
  device, preferences changed on another device (REQ-NTF-016 AC3);
- the record's channel: a delivery recorded, so the record's notification log refreshes;
- every signed-in user of the tenant: the rules changed (ID-free; only the rules screen reacts).

No new channel kinds: personal, record and broadcast channels already exist with their checks.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.events import (
    DeliveryRecorded,
    NotificationCreated,
    NotificationsRead,
    PreferencesChanged,
    RuleChanged,
)
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import UnknownRecordTypeError, record_source
from app.shared.realtime import (
    Publication,
    RealtimeEffects,
    RealtimeRoute,
    broadcast,
    personal,
    record,
)

CREATED = "notifications.created"
READ = "notifications.read"
PREFERENCES = "notifications.preferences_changed"
DELIVERY = "notifications.delivery_recorded"
RULES = "notifications.rules_changed"


def _user(envelope: EventEnvelope) -> uuid.UUID:
    return uuid.UUID(str(envelope.payload["user_id"]))


async def _own(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    kind = {
        NotificationCreated.event_type: CREATED,
        NotificationsRead.event_type: READ,
        PreferencesChanged.event_type: PREFERENCES,
    }[envelope.event_type]
    ids = (
        (str(envelope.payload["notification_id"]),)
        if envelope.event_type == NotificationCreated.event_type
        else tuple(str(i) for i in envelope.payload.get("notification_ids", ()))
    )
    return RealtimeEffects(
        publications=[Publication(personal(envelope.tenant_id, _user(envelope)), kind, ids=ids)]
    )


async def _delivery(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    try:
        source = record_source(str(envelope.payload["record_type"]))
    except UnknownRecordTypeError:
        return RealtimeEffects()
    channel = record(
        envelope.tenant_id, source.channel_kind, uuid.UUID(str(envelope.payload["record_id"]))
    )
    return RealtimeEffects(publications=[Publication(channel, DELIVERY, coalesce=True)])


async def _rules(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), RULES, coalesce=True)]
    )


ROUTES = [
    RealtimeRoute(
        (
            NotificationCreated.event_type,
            NotificationsRead.event_type,
            PreferencesChanged.event_type,
        ),
        _own,
    ),
    RealtimeRoute((DeliveryRecorded.event_type,), _delivery),
    RealtimeRoute((RuleChanged.event_type,), _rules),
]
