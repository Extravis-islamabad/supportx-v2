"""The portal's own settings (WP-032 D8; D-143; REQ-PRT-031, -003).

- work_item_portal_settings: one row per tenant (RLS). The one search box's sources and their
  order (items, articles, announcements, requests by default), whether requesters may edit their
  profile, and whether they get reminders. Settings with a home elsewhere stay there.

Expand only, no data step: a tenant without a row reads the defaults.

Revision ID: 0096
Revises: 0092
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0096"
down_revision: str | None = "0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_portal_settings"


def upgrade() -> None:
    """The table, its RLS and the app role's grants."""
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "search_sources",
            postgresql.ARRAY(sa.String(length=20)),
            server_default="{items,articles,announcements,requests}",
            nullable=False,
        ),
        sa.Column("profile_editing", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("requester_reminders", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "search_sources <@ ARRAY['items', 'articles', 'announcements', 'requests']::varchar[]",
            name=op.f(f"ck_{TABLE}_search_sources_known"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f(f"pk_{TABLE}")),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Remove the table (its settings return to the defaults)."""
    op.drop_table(TABLE)
