"""Asset notifications on the engine (WP-049a s4; REQ-AST-023 AC1, AC3).

- `asset.ack_requested`: a person was given an asset that asks for acknowledgement; they hear
  of it (in the portal and by mail when mail is set up; the portal works without mail, AC4).
  The holder may be a requester without any asset permission, so they get the public side:
  the asset's tag and name, and a link to their own "My assets".
- `asset.ack_disputed`: they disputed it; the technician who gave it hears of it, with the
  comment (AC3). Staff only.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound, PermissionDenied
from app.modules.assets.events import AcknowledgementChanged
from app.modules.assets.infra.models import Asset, AssetAcknowledgement
from app.modules.assets.service.assets import RECORD_TYPE, _visible
from app.modules.assets.service.realtime import RECORD_KIND
from app.modules.identity_access import subject_for, user_names
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

EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        "asset.ack_requested",
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=("holder",)),
    ),
    NotificationEvent(
        "asset.ack_disputed",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("assigned_by",)),
        public=False,
        variables=(
            Variable("acknowledgement.comment", "notification_variable.acknowledgement.comment"),
        ),
    ),
)
RECIPIENT_KINDS = ("holder", "assigned_by")
VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("holder.name", "notification_variable.holder.name"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


class AssetNotifications:
    """`RecordSource` for assets."""

    record_type = RECORD_TYPE
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = RECIPIENT_KINDS
    variables = VARIABLES
    conditions: tuple[str, ...] = ()
    event_types = (AcknowledgementChanged.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """Asked for: the holder hears of it; disputed: the person who gave it."""
        status = envelope.payload.get("status")
        if status == "pending":
            return ("asset.ack_requested",)
        if status == "disputed":
            return ("asset.ack_disputed",)
        return ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The asset and its acknowledgement as they are now."""
        payload = envelope.payload
        ack = await session.get(AssetAcknowledgement, uuid.UUID(str(payload["acknowledgement_id"])))
        asset = await session.scalar(
            select(Asset).where(
                Asset.id == uuid.UUID(str(payload["asset_id"])), Asset.deleted_at.is_(None)
            )
        )
        if ack is None or asset is None:
            return None
        names = await user_names(session, [str(ack.user_id)])
        shared: dict[str, VariableValue] = {
            "record.display_id": asset.tag or asset.name,
            "record.title": asset.name,
            "record.link": f"/assets/{asset.id}",
            "holder.name": names.get(str(ack.user_id)),
        }
        if event_code == "asset.ack_disputed":
            shared["acknowledgement.comment"] = ack.comment
        public = {k: v for k, v in shared.items() if k != "acknowledgement.comment"}
        public["record.link"] = "/my-assets"
        return RecordContext(
            record_id=asset.id,
            display_id=asset.tag or asset.name,
            link=f"/assets/{asset.id}",
            variables=shared,
            public_variables=public,
            relatives={
                "holder": frozenset({ack.user_id}),
                "assigned_by": frozenset({ack.created_by} if ack.created_by else ()),
            },
            conditions={},
            event_code=event_code,
            public_link="/my-assets",
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for staff who may see the asset; PUBLIC for the person who holds it."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        try:
            await _visible(session, subject, record_id)
        except (NotFound, PermissionDenied):
            holder = await session.scalar(select(Asset.owner_user_id).where(Asset.id == record_id))
            return RecordAccess.PUBLIC if holder == user_id else RecordAccess.NONE
        return RecordAccess.FULL


SOURCE = AssetNotifications()


def register() -> None:
    """Make assets notify (idempotent; called when the assets module is imported)."""
    register_record_source(SOURCE)
