"""Custom field definitions (WP-026; architecture.md §6.6). Tenant-scoped with RLS (migration 0021).

Values live on the records themselves (`work_items.custom`); this table holds what each field
is. Fields are retired, never deleted once used (`first_used_at`), so old values keep their
label and history.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.metadata.domain.fields import (
    ChoiceDisplay,
    CustomFieldEntity,
    FieldType,
    IndexFailure,
    IndexState,
)
from app.shared.db.models import TenantEntity


def _codes(column: str, values: Any) -> str:  # noqa: ANN401 - any StrEnum class
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class CustomField(TenantEntity):
    """One custom field of one entity."""

    __tablename__ = "custom_fields"
    __table_args__ = (
        CheckConstraint(_codes("entity", CustomFieldEntity), name="entity_code"),
        CheckConstraint(_codes("field_type", FieldType), name="field_type_code"),
        CheckConstraint(_codes("display", ChoiceDisplay), name="display_code"),
        CheckConstraint(_codes("index_state", IndexState), name="index_state_code"),
        CheckConstraint(
            "index_error IS NULL OR " + _codes("index_error", IndexFailure), name="index_error_code"
        ),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{1,39}$'", name="key_format"),
        CheckConstraint(
            "seal_state IN ('plain', 'sealing', 'sealed', 'opening')", name="seal_state_code"
        ),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index(
            "uq_custom_fields_tenant_entity_key",
            "tenant_id",
            "entity",
            "key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_custom_fields_tenant_entity_order", "tenant_id", "entity", "sort_order"),
        # Fields scoped to a type and its subtypes (0175; plans/metadata-type-subtree-design).
        Index(
            "ix_custom_fields_tenant_entity_scope",
            "tenant_id",
            "entity",
            "scope_type_id",
            postgresql_where=text("scope_type_id IS NOT NULL"),
        ),
    )

    entity: Mapped[str] = mapped_column(String(30))
    # A type of the owning module (and every type below it), or None for the whole entity
    # (0175). No foreign key: the type tables are another module's; checked through its
    # type-tree port (metadata.register_type_tree).
    scope_type_id: Mapped[uuid.UUID | None]
    key: Mapped[str] = mapped_column(String(40))
    field_type: Mapped[str] = mapped_column(String(20))
    labels: Mapped[dict[str, str]] = mapped_column(JSONB)
    help: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    # Choice fields: [{"code", "labels": {...}, "retired": bool}, ...] in display order.
    choices: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    display: Mapped[str] = mapped_column(String(10), server_default="list")
    # No starting value is SQL NULL, not JSON null (QA C7).
    default_value: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # {"required", "min", "max", "min_length", "max_length", "pattern"}; numbers as strings.
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    currency: Mapped[str | None] = mapped_column(String(3))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    retired_at: Mapped[datetime | None]
    # Set the first time a record saves a value: from then on the field can only be retired.
    first_used_at: Mapped[datetime | None]
    index_state: Mapped[str] = mapped_column(String(10), server_default="none")
    index_error: Mapped[str | None] = mapped_column(String(20))
    index_requested_by: Mapped[uuid.UUID | None]
    # An admin's marks (REQ-ADM-026 AC2, D-171; migration 0162). Marking creates no field access
    # rule; personal data erasure and export read them (lane B).
    personal_data: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sensitive: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Where the stored values stand while the re-seal job follows `sensitive` (WP-057 S3b-2;
    # 0171): plain, sealing, sealed or opening. Filters on a field in between are refused.
    seal_state: Mapped[str] = mapped_column(String(10), server_default="plain")
    seal_cursor: Mapped[uuid.UUID | None]
