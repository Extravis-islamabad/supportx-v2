"""Transition settings (WP-029 part 2; REQ-WF-003, 004).

- transition_settings: per record type and life-cycle action, who may run it, when it is
  offered, its confirmation text and its "after" actions. No row: permission only, as before.

Revision ID: 0028
Revises: 0025
Created: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0028"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transition_settings",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column(
            "roles", postgresql.ARRAY(sa.String(length=80)), server_default="{}", nullable=False
        ),
        sa.Column("group_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column(
            "relatives",
            postgresql.ARRAY(sa.String(length=30)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "after_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "jsonb_typeof(after_actions) = 'array'",
            name=op.f("ck_transition_settings_after_actions_array"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_transition_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "record_type", "action", name=op.f("pk_transition_settings")
        ),
    )
    enable_tenant_rls("transition_settings")
    grant_app("transition_settings", ("SELECT", "INSERT", "UPDATE", "DELETE"))
    enable_actor_audit("transition_settings")


def downgrade() -> None:
    op.drop_table("transition_settings")
