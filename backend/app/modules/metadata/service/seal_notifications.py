"""Admins hear when sealing a sensitive field's values pauses for want of keys (WP-057 S3b-2b).

One notice per outage (lane B): the job stops with the field's state unchanged and tries again
by itself; the admins who can change custom fields are told once, in the app and by e-mail,
urgent, required and locked (as the sign-in expiry alerts are). The message names the field
and links to its settings: never a value.
"""

import uuid
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.identity_access import worker_policy
from app.modules.metadata.events import CustomFieldSealPaused
from app.modules.metadata.infra.models import CustomField
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RECORD_TYPE = "custom_field"
FIELD_ADMINS = "custom_field_admins"
PAUSED = "custom_field.seal_paused"
RIGHTS = ("settings.manage", "config.service_desk")  # who may change custom fields (the routes)
ADMINS_LIMIT = 200
LINK = "/admin/custom-fields"

_VARIABLES = (
    Variable("record.title", "notification_variable.custom_field.name"),
    Variable("notice.direction", "notification_variable.custom_field.direction"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


async def _admins(session: AsyncSession) -> frozenset[uuid.UUID]:
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    found: set[uuid.UUID] = set()
    for right in RIGHTS:
        found |= {
            user_id
            for user_id, _ in await worker_policy().holders(
                session, tenant, right, limit=ADMINS_LIMIT
            )
        }
    return frozenset(found)


class SealPausedNotifications:
    """The notification source of a paused re-seal job."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "users"
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            PAUSED,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(FIELD_ADMINS,), notify_actor=True),
            required=True,
            locked=True,
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (FIELD_ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (CustomFieldSealPaused.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notice per pause event (made once per outage)."""
        return (PAUSED,) if envelope.event_type == CustomFieldSealPaused.event_type else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The field by its name, which way it was going, and the admins now."""
        del event_code
        notice = CustomFieldSealPaused.model_validate(envelope.payload)
        field = await session.get(CustomField, notice.custom_field_id)
        if field is None or field.deleted_at is not None:
            return None
        name = (field.labels or {}).get("en") or field.key
        values: dict[str, VariableValue] = {
            "record.title": name,
            "notice.direction": LabelRef(f"notice.custom_field.seal_{notice.seal_state}"),
            "record.link": LINK,
        }
        return RecordContext(
            record_id=field.id,
            display_id=name,
            link=LINK,
            variables=values,
            public_variables=values,
            relatives={FIELD_ADMINS: await _admins(session)},
            conditions={},
            urgent=True,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for those who may change custom fields (checked at send time), nobody else."""
        del record_id
        return RecordAccess.FULL if user_id in await _admins(session) else RecordAccess.NONE


SOURCE = SealPausedNotifications()


def register() -> None:
    """Make the pause notify (idempotent; called when metadata is imported)."""
    register_record_source(SOURCE)
