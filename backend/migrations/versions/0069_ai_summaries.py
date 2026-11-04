"""Conversation summaries (WP-038, REQ-INC-137).

Expand only:

- `ai_summaries` (RLS, FORCE): the latest summary of a record's conversation, one per record and
  level. The `with_private` level includes private notes and is shown only to staff who may see
  them; `public` leaves them out. Each row keeps the model, when it was made, and the newest
  conversation entry it covers. A newer entry marks it stale, and the record page offers Refresh.
- `ai_settings.summary_sources`: which parts an admin lets summaries read (description, replies,
  public notes, private notes). Nullable, so a changed default never overwrites a tenant's
  choice; the default (description, replies, public notes) applies at read time.

The trigram fallback for possible duplicates (D-134) uses pg_trgm, created by migration 0020.

No data step. The downgrade drops the table and the column.

Revision ID: 0069
Revises: 0075
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0069"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_settings",
        sa.Column("summary_sources", postgresql.ARRAY(sa.String(20)), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_ai_settings_summary_sources_known"),
        "ai_settings",
        "summary_sources IS NULL OR summary_sources <@ "
        "ARRAY['description','replies','public_notes','private_notes']::varchar[]",
    )
    op.create_table(
        "ai_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(40), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("last_entry_id", sa.Uuid(), nullable=True),
        sa.Column("stale", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "level IN ('with_private', 'public')", name=op.f("ck_ai_summaries_level_code")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ai_summaries_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_summaries")),
        sa.UniqueConstraint(
            "tenant_id",
            "record_type",
            "record_id",
            "level",
            name=op.f("uq_ai_summaries_tenant_id_record_type_record_id_level"),
        ),
    )
    enable_tenant_rls("ai_summaries")
    enable_actor_audit("ai_summaries")
    grant_app("ai_summaries", ("SELECT", "INSERT", "UPDATE", "DELETE"))


def downgrade() -> None:
    op.drop_table("ai_summaries")
    op.drop_constraint(op.f("ck_ai_settings_summary_sources_known"), "ai_settings")
    op.drop_column("ai_settings", "summary_sources")
