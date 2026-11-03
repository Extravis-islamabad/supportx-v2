"""The tenant's instance settings (WP-042; REQ-ADM-049, 050, 052).

Expand only:
- `tenant_settings` (RLS, FORCE): one row per tenant, created on first use: defaults for people
  and sites (time zone, week start, date and time formats, country, fiscal year), contact, the
  base currency and the languages offered (English always). The application role may read,
  insert and update; never delete.

No data step. The downgrade drops the table (screens fall back to the built-in defaults).

Revision ID: 0066
Revises: 0061
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0066"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("time_zone", sa.String(64), server_default="UTC", nullable=False),
        sa.Column("week_start", sa.String(10), server_default="monday", nullable=False),
        sa.Column("date_format", sa.String(12), server_default="dd/mm/yyyy", nullable=False),
        sa.Column("time_format", sa.String(4), server_default="24h", nullable=False),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("fiscal_year_start_month", sa.Integer(), server_default="1", nullable=False),
        sa.Column("contact_email", sa.String(320), nullable=True),
        sa.Column("contact_phone", sa.String(40), nullable=True),
        sa.Column("base_currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.String(5)),
            server_default="{en,ar,ur}",
            nullable=False,
        ),
        sa.Column("default_language", sa.String(5), server_default="en", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "fiscal_year_start_month BETWEEN 1 AND 12",
            name=op.f("ck_tenant_settings_fiscal_month_range"),
        ),
        sa.CheckConstraint(
            "'en' = ANY(languages)", name=op.f("ck_tenant_settings_english_offered")
        ),
        sa.CheckConstraint(
            "default_language = ANY(languages)", name=op.f("ck_tenant_settings_default_offered")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_settings")),
    )
    enable_tenant_rls("tenant_settings")
    grant_app("tenant_settings", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_table("tenant_settings")
