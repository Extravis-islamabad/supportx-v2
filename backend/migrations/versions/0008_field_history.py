"""Field history: one row per changed field of every save (architecture.md §7.4; WP-012).

Tenant-scoped (RLS). Append-only for the application: supportx_app may INSERT and SELECT, never
UPDATE or DELETE, so a record's history cannot be rewritten through the API. Partitioning by
month (§7.3) is a later step; the index already leads with tenant and record.

Revision ID: 0008
Revises: 0007
Created: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        sa.Column("change_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("field", sa.String(length=80), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actor_type", sa.String(length=10), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('created', 'updated', 'status', 'deleted', 'restored')",
            name=op.f("ck_field_changes_kind_code"),
        ),
        sa.CheckConstraint(
            "source IN ('ui', 'api', 'rule', 'workflow', 'ai_agent', 'system', 'import')",
            name=op.f("ck_field_changes_source_code"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR char_length(reason) <= 500",
            name=op.f("ck_field_changes_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_field_changes_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_changes")),
    )
    op.create_index(
        op.f("ix_field_changes_tenant_id_record_type_record_id_record_version"),
        "field_changes",
        ["tenant_id", "record_type", "record_id", "record_version"],
    )
    enable_tenant_rls("field_changes")
    grant_app("field_changes", ("SELECT", "INSERT"))


def downgrade() -> None:
    op.drop_table("field_changes")
