"""Every tenant admin hears of vendor support access (D-173 (8); WP-057 S4c-1).

One notification source (record type "support_grant"): a grant made, its engineer's first
sign-in, an extension, its end (expired or ended early), and an account removal still not
confirmed a day later (lane B, once per grant). The people told are the tenant's admins, through
the one notification engine, in-app and by e-mail. Required and locked: nobody can turn them off.
Urgent: never held for a digest. The message names the engineer (the admins granted them) and
links to the vendor support screen; never the reason text, the IP list or anything secret.
"""

import uuid
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.events import SupportGrantChanged
from app.modules.identity_access.infra.models import SupportGrant
from app.modules.identity_access.service.break_glass_notifications import tenant_admins
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RECORD_TYPE = "support_grant"
ADMINS = "tenant_admins"
LINK = "/admin/security/vendor-support"

# The grant's changes that tell the admins, and the notification event each one is.
_EVENTS: dict[str, str] = {
    "created": "support_grant.granted",
    "first_used": "support_grant.first_used",
    "extended": "support_grant.extended",
    "ended": "support_grant.ended",
    "revoked": "support_grant.ended",
    "account_removal_stuck": "support_grant.removal_stuck",
}

_VARIABLES = (
    Variable("record.title", "notification_variable.support_grant.engineer"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


def _event(code: str) -> NotificationEvent:
    return NotificationEvent(
        code,
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=(ADMINS,), notify_actor=True),
        required=True,  # D-173 (8): every admin, always
        locked=True,
    )


class SupportGrantNotifications:
    """The notification source of vendor support grants."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "users"
    events: ClassVar[tuple[NotificationEvent, ...]] = tuple(
        _event(code) for code in dict.fromkeys(_EVENTS.values())
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (SupportGrantChanged.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notification per change the admins hear of (the rest are audit only)."""
        if envelope.event_type != SupportGrantChanged.event_type:
            return ()
        found = _EVENTS.get(str(envelope.payload.get("change")))
        return (found,) if found is not None else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The engineer by name, and the tenant's admins now."""
        del event_code
        grant_id = uuid.UUID(str(envelope.payload["grant_id"]))
        row = await session.get(SupportGrant, grant_id)
        if row is None:
            return None
        values: dict[str, VariableValue] = {"record.title": row.engineer_name, "record.link": LINK}
        return RecordContext(
            record_id=grant_id,
            display_id=row.engineer_name,
            link=LINK,
            variables=values,
            public_variables=values,
            relatives={ADMINS: frozenset(await tenant_admins(session))},
            conditions={},
            urgent=True,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for the tenant's admins (checked at send time), nobody else."""
        del record_id
        return (
            RecordAccess.FULL if user_id in set(await tenant_admins(session)) else RecordAccess.NONE
        )


SOURCE = SupportGrantNotifications()


def register() -> None:
    """Make vendor support grants notify (idempotent; called when identity_access is imported)."""
    register_record_source(SOURCE)
