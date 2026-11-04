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


EVENTS: tuple[type[DomainEvent], ...] = (CatalogueChanged, ProductChanged)
