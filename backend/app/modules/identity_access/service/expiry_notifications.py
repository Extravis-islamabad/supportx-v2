"""Tenant admins hear before a sign-in certificate or secret runs out (REQ-SEC-011; WP-057 S2b-2).

One notification source (record type "sign_in_secret"): the provider is the record; the tenant's
admins are told, in the app and by e-mail, urgent, required and locked (#480): an admin cannot
switch it off or redirect it. The message names the provider, what runs out, how many days are
left (or that it has run out) and the date, and links to Sign-in and security.
"""

import uuid
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.events import SignInSecretExpiring
from app.modules.identity_access.infra.models import SsoProvider
from app.modules.identity_access.service.break_glass_notifications import tenant_admins
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

RECORD_TYPE = "sign_in_secret"
TENANT_ADMINS = "tenant_admins"
EXPIRING = "sign_in_secret.expiring"
LINK = "/admin/security"

_VARIABLES = (
    Variable("record.title", "notification_variable.sign_in_secret.provider"),
    Variable("notice.item", "notification_variable.sign_in_secret.item"),
    Variable("notice.left", "notification_variable.sign_in_secret.left"),
    Variable("notice.expires", "notification_variable.sign_in_secret.expires"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


class SignInSecretNotifications:
    """The notification source of certificate and client secret expiry."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "users"
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            EXPIRING,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(TENANT_ADMINS,), notify_actor=True),
            required=True,  # people cannot switch it off
            locked=True,  # nor can an admin change or reset its rule (#480)
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (TENANT_ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (SignInSecretExpiring.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notice per alert."""
        return (EXPIRING,) if envelope.event_type == SignInSecretExpiring.event_type else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The provider, what runs out and when, and the tenant's admins now."""
        del event_code
        alert = SignInSecretExpiring.model_validate(envelope.payload)
        provider = await session.get(SsoProvider, alert.provider_id)
        if provider is None:
            return None
        left: VariableValue = (
            LabelRef("notice.sign_in_secret.expired")
            if alert.days_left == 0
            else LabelRef(f"notice.sign_in_secret.days_{alert.days_left}")
        )
        values: dict[str, VariableValue] = {
            "record.title": provider.display_name,
            "notice.item": LabelRef(f"notice.sign_in_secret.item_{alert.item}"),
            "notice.left": left,
            "notice.expires": alert.expires_at,
            "record.link": LINK,
        }
        return RecordContext(
            record_id=provider.id,
            display_id=provider.display_name,
            link=LINK,
            variables=values,
            public_variables=values,
            relatives={TENANT_ADMINS: frozenset(await tenant_admins(session))},
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


SOURCE = SignInSecretNotifications()


def register() -> None:
    """Make expiry alerts notify (idempotent; called when identity_access is imported)."""
    register_record_source(SOURCE)
