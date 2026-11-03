"""Event contracts of the service catalog (WP-030 s1). IDs and field names only (§8.2)."""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class CatalogItemChanged(DomainEvent):
    """An item was added or changed (names only of the changed fields)."""

    event_type: ClassVar[str] = "service_catalog.item.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "catalog_item"

    item_id: uuid.UUID
    changed_fields: list[str]


class ServiceCategoryChanged(DomainEvent):
    """A category was added or changed."""

    event_type: ClassVar[str] = "service_catalog.category.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "service_category"

    category_id: uuid.UUID
    changed_fields: list[str]


EVENTS: list[type[DomainEvent]] = [CatalogItemChanged, ServiceCategoryChanged]

__all__ = ["EVENTS", "CatalogItemChanged", "ServiceCategoryChanged"]
