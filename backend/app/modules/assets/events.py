"""Event contracts published by the assets module (WP-049a; docs/architecture/events.md).

Payloads carry IDs, codes and changed field *names* only, never names, prices or descriptions
(architecture.md §8.2). Consumers that need more read it through the module's service.
"""

import uuid
from typing import ClassVar, Literal

from app.shared.events import DomainEvent

CatalogueKind = Literal["product_type", "state", "life_cycle", "settings"]
CatalogueAction = Literal["created", "updated", "deleted"]


class CatalogueChanged(DomainEvent):
    """A product type, state, life cycle or the asset settings changed (admin set-up)."""

    event_type: ClassVar[str] = "assets.catalogue.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "asset_catalogue"

    kind: CatalogueKind
    item_id: uuid.UUID | None = None  # None for the settings
    action: CatalogueAction
    changed_fields: list[str]


class ProductChanged(DomainEvent):
    """A product was created, changed or moved to the trash (REQ-AST-005)."""

    event_type: ClassVar[str] = "assets.product.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "asset_product"

    product_id: uuid.UUID
    product_type_id: uuid.UUID
    action: CatalogueAction
    changed_fields: list[str]


AssetAction = Literal["created", "updated", "deleted", "restored"]


class AssetChanged(DomainEvent):
    """An asset was added, changed, moved to the trash or restored (REQ-AST-007).

    `site_id` is the asset's site after the change, so live lists at that site hear of it.
    """

    event_type: ClassVar[str] = "assets.asset.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "asset"

    asset_id: uuid.UUID
    action: AssetAction
    changed_fields: list[str]
    site_id: uuid.UUID | None = None


class AssetHolderChanged(DomainEvent):
    """An asset changed hands (WP-049a s4; REQ-AST-024 AC3): the people before and after.

    IDs only: their "My assets" lists refresh live; staff screens follow `asset.changed`.
    """

    event_type: ClassVar[str] = "assets.holder.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "asset"

    asset_id: uuid.UUID
    people: list[uuid.UUID]


class AcknowledgementChanged(DomainEvent):
    """An acknowledgement was asked for, accepted or disputed (REQ-AST-023)."""

    event_type: ClassVar[str] = "assets.acknowledgement.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "asset_acknowledgement"

    acknowledgement_id: uuid.UUID
    asset_id: uuid.UUID
    user_id: uuid.UUID
    status: Literal["pending", "accepted", "disputed"]


class AssetGroupChanged(DomainEvent):
    """A group was added, changed, removed, or gained or lost members (REQ-AST-028)."""

    event_type: ClassVar[str] = "assets.group.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "asset_group"

    group_id: uuid.UUID
    change: Literal["created", "updated", "deleted", "members"]


LoanChange = Literal["created", "returned", "closed", "due", "overdue"]


class AssetLoanChanged(DomainEvent):
    """A loan was made, partly returned, closed, or came due or overdue (REQ-AST-030, 031, 059)."""

    event_type: ClassVar[str] = "assets.loan.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "asset_loan"

    loan_id: uuid.UUID
    borrower_id: uuid.UUID
    created_by: uuid.UUID | None
    change: LoanChange


class WarrantyEnding(DomainEvent):
    """An asset's warranty ends within the tenant's notice days (REQ-AST-059 AC2), once per date."""

    event_type: ClassVar[str] = "assets.warranty.ending"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "asset"

    asset_id: uuid.UUID


EVENTS: tuple[type[DomainEvent], ...] = (
    CatalogueChanged,
    ProductChanged,
    AssetChanged,
    AssetHolderChanged,
    AcknowledgementChanged,
    AssetGroupChanged,
    AssetLoanChanged,
    WarrantyEnding,
)
