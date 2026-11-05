"""Event contracts of the service catalog (WP-030, WP-031). IDs, field names, counts (§8.2)."""

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


class CatalogSettingsChanged(DomainEvent):
    """The tenant's catalog settings changed (WP-031)."""

    event_type: ClassVar[str] = "service_catalog.settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "catalog_settings"

    changed_fields: list[str]


class StarterCatalogSeeded(DomainEvent):
    """The starter catalog was added to the tenant (D-138): counts only."""

    event_type: ClassVar[str] = "service_catalog.starter.seeded"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "catalog_settings"

    categories: int
    items: int


EVENTS: list[type[DomainEvent]] = [
    CatalogItemChanged,
    ServiceCategoryChanged,
    CatalogSettingsChanged,
    StarterCatalogSeeded,
]

__all__ = [
    "EVENTS",
    "CatalogItemChanged",
    "CatalogSettingsChanged",
    "ServiceCategoryChanged",
    "StarterCatalogSeeded",
]
