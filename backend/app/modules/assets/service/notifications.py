"""Asset notifications on the engine (WP-049a s4; REQ-AST-023 AC1, AC3).

- `asset.ack_requested`: a person was given an asset that asks for acknowledgement; they hear
  of it (in the portal and by mail when mail is set up; the portal works without mail, AC4).
  The holder may be a requester without any asset permission, so they get the public side:
  the asset's tag and name, and a link to their own "My assets".
- `asset.ack_disputed`: they disputed it; the technician who gave it hears of it, with the
  comment (AC3). Staff only.
- `asset.mentioned` (WP-049b s2, REQ-AST-050 after REQ-INC-063): a person mentioned in a note
  on an asset they may see; with the author's name, a link to the asset's notes. Staff only.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound, PermissionDenied
from app.modules.assets.events import (
    AcknowledgementChanged,
    AssetLoanChanged,
    AssetNoteChanged,
    StockLow,
    WarrantyEnding,
)
from app.modules.assets.infra.models import (
    Asset,
    AssetAcknowledgement,
    AssetConsumable,
    AssetConsumableStock,
    AssetLoan,
    AssetNote,
    AssetProduct,
    AssetStockRule,
)
from app.modules.assets.service.assets import MANAGE, RECORD_TYPE, VIEW, _visible
from app.modules.assets.service.realtime import RECORD_KIND
from app.modules.identity_access import subject_for, user_names, worker_policy
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
    # Appendix A: loan due (1 day before) and overdue (once) to the borrower and its creator.
    NotificationEvent(
        "asset.loan_due",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("borrower", "loan_creator")),
    ),
    NotificationEvent(
        "asset.loan_overdue",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("borrower", "loan_creator")),
    ),
    # Appendix A: a warranty ending within 30 days, to the asset managers.
    NotificationEvent(
        "asset.warranty_expiring",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("asset_managers",)),
        public=False,
    ),
    # REQ-AST-035 AC1: stock at or below its minimum, once, to the rule's people.
    NotificationEvent(
        "asset.stock_low",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("stock_watchers",)),
        public=False,
        variables=(
            Variable("stock.quantity", "notification_variable.stock.quantity"),
            Variable("stock.minimum", "notification_variable.stock.minimum"),
        ),
    ),
    NotificationEvent(
        "asset.mentioned",
        NotificationCategory.MENTION,
        EventDefault(enabled=True, recipients=("mentioned",)),
        public=False,
        variables=(Variable("conversation.author", "notification_variable.conversation.author"),),
    ),
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
RECIPIENT_KINDS = (
    "holder",
    "assigned_by",
    "borrower",
    "loan_creator",
    "asset_managers",
    "stock_watchers",
    "mentioned",
)
MANAGERS_LIMIT = 500
VARIABLES = (
    Variable("warranty.ends_on", "notification_variable.warranty.ends_on"),
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
    event_types = (
        AcknowledgementChanged.event_type,
        AssetLoanChanged.event_type,
        WarrantyEnding.event_type,
        StockLow.event_type,
        AssetNoteChanged.event_type,
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """Asked for: the holder hears of it; disputed: the person who gave it."""
        fixed = {
            WarrantyEnding.event_type: ("asset.warranty_expiring",),
            StockLow.event_type: ("asset.stock_low",),
        }
        if envelope.event_type in fixed:
            return fixed[envelope.event_type]
        if envelope.event_type == AssetNoteChanged.event_type:
            return ("asset.mentioned",) if envelope.payload.get("mentioned") else ()
        if envelope.event_type == AssetLoanChanged.event_type:
            change = envelope.payload.get("change")
            return {"due": ("asset.loan_due",), "overdue": ("asset.loan_overdue",)}.get(
                str(change), ()
            )
        status = envelope.payload.get("status")
        if status == "pending":
            return ("asset.ack_requested",)
        if status == "disputed":
            return ("asset.ack_disputed",)
        return ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The asset (and its acknowledgement), or the loan, as it is now."""
        payload = envelope.payload
        if envelope.event_type == AssetLoanChanged.event_type:
            return await self._loan_context(session, event_code, payload)
        if envelope.event_type == WarrantyEnding.event_type:
            return await self._warranty_context(session, event_code, payload)
        if envelope.event_type == StockLow.event_type:
            return await self._stock_context(session, event_code, payload)
        if envelope.event_type == AssetNoteChanged.event_type:
            return await self._note_context(session, event_code, payload)
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

    async def _loan_context(
        self, session: AsyncSession, event_code: str, payload: Mapping[str, object]
    ) -> RecordContext | None:
        loan = await session.get(AssetLoan, uuid.UUID(str(payload["loan_id"])))
        if loan is None or loan.closed_at is not None:
            return None  # returned meanwhile: nothing to tell
        names = await user_names(session, [str(loan.borrower_id)])
        shown: dict[str, VariableValue] = {
            "record.display_id": names.get(str(loan.borrower_id)),
            "record.title": None,
            "record.link": "/assets/loans",
            "holder.name": names.get(str(loan.borrower_id)),
        }
        return RecordContext(
            record_id=loan.id,
            display_id=names.get(str(loan.borrower_id)) or "",
            link="/assets/loans",
            variables=shown,
            public_variables={**shown, "record.link": "/my-assets"},
            relatives={
                "borrower": frozenset({loan.borrower_id}),
                "loan_creator": frozenset({loan.created_by} if loan.created_by else ()),
            },
            conditions={},
            urgent=event_code == "asset.loan_overdue",
            event_code=event_code,
            public_link="/my-assets",
        )

    async def _warranty_context(
        self, session: AsyncSession, event_code: str, payload: Mapping[str, object]
    ) -> RecordContext | None:
        asset = await session.scalar(
            select(Asset).where(
                Asset.id == uuid.UUID(str(payload["asset_id"])), Asset.deleted_at.is_(None)
            )
        )
        if asset is None:
            return None
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        managers = await worker_policy().holders(session, tenant, MANAGE, limit=MANAGERS_LIMIT)
        shown: dict[str, VariableValue] = {
            "record.display_id": asset.tag or asset.name,
            "record.title": asset.name,
            "record.link": f"/assets/{asset.id}",
            "warranty.ends_on": str(asset.warranty_expires_on),
        }
        return RecordContext(
            record_id=asset.id,
            display_id=asset.tag or asset.name,
            link=f"/assets/{asset.id}",
            variables=shown,
            public_variables={},
            relatives={"asset_managers": frozenset(user_id for user_id, _ in managers)},
            conditions={},
            event_code=event_code,
        )

    async def _stock_context(
        self, session: AsyncSession, event_code: str, payload: Mapping[str, object]
    ) -> RecordContext | None:
        """A low stock: the consumable (by product name), its quantity and minimum now."""
        stock = await session.get(AssetConsumableStock, uuid.UUID(str(payload["stock_id"])))
        rule = await session.get(AssetStockRule, uuid.UUID(str(payload["rule_id"])))
        consumable = await session.get(AssetConsumable, uuid.UUID(str(payload["consumable_id"])))
        if stock is None or rule is None or consumable is None or consumable.deleted_at:
            return None
        if stock.low_alerted_at is None:
            return None  # risen above the minimum meanwhile: nothing to tell
        name = await session.scalar(
            select(AssetProduct.name).where(AssetProduct.id == consumable.product_id)
        )
        link = f"/assets/consumables/{consumable.id}"
        shown: dict[str, VariableValue] = {
            "record.display_id": name,
            "record.title": name,
            "record.link": link,
            "stock.quantity": format(stock.quantity.normalize(), "f"),
            "stock.minimum": format(rule.min_quantity.normalize(), "f"),
        }
        watchers = frozenset(uuid.UUID(str(p)) for p in rule.notify_user_ids)
        return RecordContext(
            record_id=stock.id,
            display_id=name or "",
            link=link,
            variables=shown,
            public_variables={},
            relatives={"stock_watchers": watchers},
            conditions={},
            event_code=event_code,
        )

    async def _note_context(
        self, session: AsyncSession, event_code: str, payload: Mapping[str, object]
    ) -> RecordContext | None:
        """A mention in a note: the asset, the note's author; the people mentioned."""
        note = await session.get(AssetNote, uuid.UUID(str(payload["note_id"])))
        asset = await session.scalar(
            select(Asset).where(
                Asset.id == uuid.UUID(str(payload["asset_id"])), Asset.deleted_at.is_(None)
            )
        )
        if note is None or note.deleted_at is not None or asset is None:
            return None  # deleted meanwhile: nothing to tell
        author = str(note.updated_by or note.created_by or "")
        names = await user_names(session, [author] if author else [])
        link = f"/assets/{asset.id}?tab=notes"
        shown: dict[str, VariableValue] = {
            "record.display_id": asset.tag or asset.name,
            "record.title": asset.name,
            "record.link": link,
            "conversation.author": names.get(author),
        }
        mentioned = payload.get("mentioned")
        people = mentioned if isinstance(mentioned, list) else []
        return RecordContext(
            record_id=asset.id,
            display_id=asset.tag or asset.name,
            link=link,
            variables=shown,
            public_variables={},
            relatives={"mentioned": frozenset(uuid.UUID(str(p)) for p in people)},
            conditions={},
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for staff who may see the asset; PUBLIC for the person who holds it."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        if await session.get(AssetConsumableStock, record_id) is not None:  # a low stock
            return RecordAccess.FULL if subject.holds(VIEW) else RecordAccess.NONE
        loan = await session.get(AssetLoan, record_id)
        if loan is not None:  # a loan: staff see it in full, the borrower their own side
            if subject.holds(VIEW):
                return RecordAccess.FULL
            return RecordAccess.PUBLIC if loan.borrower_id == user_id else RecordAccess.NONE
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
