"""A deactivated owner's service accounts are handed over (WP-057 S4a; REQ-SEC-036 AC3).

When a person is deactivated, each service account they answered for is flagged (it shows
`needs_new_owner`, computed from the owner's state) and the tenant's administrators are told
once per account, in the app and by e-mail, required and locked: someone must pick a new owner.
The account keeps working meanwhile; its keys are its own, never the owner's.
"""

import uuid
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.events import ServiceAccountNeedsOwner, UserStatusChanged
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service.break_glass_notifications import tenant_admins
from app.modules.identity_access.service.service_accounts import owned_by
from app.shared.events import ConsumerSpec, EventEnvelope, record_event
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

RECORD_TYPE = "service_account"
TENANT_ADMINS = "tenant_admins"
NEEDS_OWNER = "service_account.needs_owner"
LINK = "/admin/service-accounts"


async def on_status_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a deactivated person's service accounts each need a new owner."""
    assert session is not None  # noqa: S101 - transactional consumer
    change = UserStatusChanged.model_validate(envelope.payload)
    if change.status != "disabled":
        return
    for account in await owned_by(session, change.user_id):
        await record_event(
            session,
            ServiceAccountNeedsOwner(
                service_account_id=account.id, previous_owner_id=change.user_id
            ),
            aggregate_id=account.id,
            aggregate_version=account.version,
        )


OWNER_LEFT = ConsumerSpec(
    name="identity_access__service_account_handover",
    event_types=(UserStatusChanged.event_type,),
    handler=on_status_changed,
)

_VARIABLES = (
    Variable("record.title", "notification_variable.service_account.name"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


class ServiceAccountNotifications:
    """The notification source of service accounts that need a new owner."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "users"
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            NEEDS_OWNER,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(TENANT_ADMINS,), notify_actor=True),
            required=True,
            locked=True,
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (TENANT_ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (ServiceAccountNeedsOwner.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notice per account."""
        return (NEEDS_OWNER,) if envelope.event_type == ServiceAccountNeedsOwner.event_type else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The account by name, and the administrators now."""
        del event_code
        notice = ServiceAccountNeedsOwner.model_validate(envelope.payload)
        account = await session.get(User, notice.service_account_id)
        if account is None or account.deleted_at is not None:
            return None
        values: dict[str, VariableValue] = {
            "record.title": account.display_name,
            "record.link": LINK,
        }
        return RecordContext(
            record_id=account.id,
            display_id=account.display_name,
            link=LINK,
            variables=values,
            public_variables=values,
            relatives={TENANT_ADMINS: frozenset(await tenant_admins(session))},
            conditions={},
            urgent=False,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for the tenant's administrators (checked at send time), nobody else."""
        del record_id
        return (
            RecordAccess.FULL if user_id in set(await tenant_admins(session)) else RecordAccess.NONE
        )


SOURCE = ServiceAccountNotifications()


def register() -> None:
    """Make the hand-over notify (idempotent; called when identity_access is imported)."""
    register_record_source(SOURCE)
