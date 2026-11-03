"""The AI gateway's settings and call log (WP-037, REQ-AI-027, 031).

Expand only:
- `ai_settings` (RLS, FORCE): one row per tenant: the master switch, switched-off features, masking
  for local calls and how long call text is kept. Created on first use.
- `ai_calls` (RLS, FORCE): one row per AI call. The application role may read, insert and update
  (the outcome, and the purge job clearing text after the retention period); never delete.

No data step. The downgrade drops both tables.

Revision ID: 0056
Revises: 0054 (re-pointed onto the head of main when queued; lane C's 0055 may come first)
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0056"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "disabled_features",
            postgresql.ARRAY(sa.String(40)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("mask_local", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("log_retention_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "log_retention_days BETWEEN 1 AND 365",
            name=op.f("ck_ai_settings_log_retention_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ai_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_ai_settings")),
    )
    enable_tenant_rls("ai_settings")
    grant_app("ai_settings", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("feature", sa.String(40), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("record_type", sa.String(40), nullable=True),
        sa.Column("record_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("masked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("masked_values", sa.Integer(), server_default="0", nullable=False),
        sa.Column("masked_input", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("tools", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("sources", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("guardrail_events", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("outcome", sa.String(10), nullable=True),
        sa.Column("text_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ok', 'failed', 'refused')", name=op.f("ck_ai_calls_status_code")
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('accepted', 'edited', 'discarded')",
            name=op.f("ck_ai_calls_outcome_code"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ai_calls_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_calls")),
    )
    op.create_index("ix_ai_calls_tenant_created", "ai_calls", ["tenant_id", "created_at"])
    op.create_index(
        "ix_ai_calls_tenant_feature", "ai_calls", ["tenant_id", "feature", "created_at"]
    )
    enable_tenant_rls("ai_calls")
    enable_actor_audit("ai_calls")
    grant_app("ai_calls", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_table("ai_calls")
    op.drop_table("ai_settings")
