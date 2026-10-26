"""Custom fields (WP-026; architecture.md §6.6; D-087).

- custom_fields: definitions per tenant and entity (metadata module). RLS; the app may read,
  insert and update, never delete (removing sets deleted_at; a used field is only retired).
- work_items.custom: the values (typed JSONB by key), GIN index (jsonb_path_ops) for filters.
- work_items.custom_text: their free text, written by the app on every save, for search.

Promoted fields get their own expression indexes from the migration job
(`python -m tooling.custom_field_indexes`), not from a migration: they are tenant data.

Additive (expand only; reversible).

Revision ID: 0021
Revises: 0019
Created: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0021"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIELD_TYPES = (
    "text",
    "long_text",
    "integer",
    "decimal",
    "currency",
    "date",
    "datetime",
    "choice",
    "multi_choice",
    "yes_no",
    "email",
    "phone",
    "url",
    "person",
)


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def upgrade() -> None:
    op.create_table(
        "custom_fields",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("entity", sa.String(length=30), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("field_type", sa.String(length=20), nullable=False),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("help", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "choices", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("display", sa.String(length=10), server_default="list", nullable=False),
        sa.Column("default_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "validation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_state", sa.String(length=10), server_default="none", nullable=False),
        sa.Column("index_error", sa.String(length=500), nullable=True),
        sa.Column("index_requested_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_custom_fields_currency_format"),
        ),
        sa.CheckConstraint(
            "display IN ('list', 'radio')", name=op.f("ck_custom_fields_display_code")
        ),
        sa.CheckConstraint("entity IN ('incident')", name=op.f("ck_custom_fields_entity_code")),
        sa.CheckConstraint(
            _in("field_type", FIELD_TYPES), name=op.f("ck_custom_fields_field_type_code")
        ),
        sa.CheckConstraint(
            "index_state IN ('none', 'requested', 'active', 'failed')",
            name=op.f("ck_custom_fields_index_state_code"),
        ),
        sa.CheckConstraint(
            "key ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_custom_fields_key_format")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_custom_fields_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_fields")),
    )
    op.create_index(
        "ix_custom_fields_tenant_entity_order",
        "custom_fields",
        ["tenant_id", "entity", "sort_order"],
        unique=False,
    )
    op.create_index(
        "uq_custom_fields_tenant_entity_key",
        "custom_fields",
        ["tenant_id", "entity", "key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("custom_fields")
    grant_app("custom_fields", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("custom_fields")

    op.add_column(
        "work_items",
        sa.Column(
            "custom", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.add_column("work_items", sa.Column("custom_text", sa.Text(), nullable=True))
    op.create_index(
        "ix_wi_custom",
        "work_items",
        ["custom"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"custom": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wi_custom",
        table_name="work_items",
        postgresql_using="gin",
        postgresql_ops={"custom": "jsonb_path_ops"},
    )
    op.drop_column("work_items", "custom_text")
    op.drop_column("work_items", "custom")
    op.drop_index(
        "uq_custom_fields_tenant_entity_key",
        table_name="custom_fields",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_custom_fields_tenant_entity_order", table_name="custom_fields")
    op.drop_table("custom_fields")
