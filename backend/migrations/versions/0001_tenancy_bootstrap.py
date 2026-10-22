"""Tenancy bootstrap: tenants (platform) and display_id_sequences (tenant-scoped).

Revision ID: 0001
Revises:
Created: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.shared.db.rls import APP_ROLE, CURRENT_TENANT_SQL, MIGRATOR_ROLE
from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$"
PREFIX_PATTERN = r"^[A-Z]{2,6}$"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name=op.f("ck_tenants_slug_format")),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name=op.f("ck_tenants_status_code")
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_tenants_name_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    # Platform table: RLS keyed on the row's own id (it *is* the tenant). The app reads only its
    # own tenant and cannot write; provisioning runs as the migrator role.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenants_self_select ON tenants FOR SELECT TO {APP_ROLE} "
        f"USING (id = {CURRENT_TENANT_SQL})"
    )
    op.execute(
        f"CREATE POLICY tenants_platform_admin ON tenants FOR ALL TO {MIGRATOR_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    grant_app("tenants", ("SELECT",))

    op.create_table(
        "display_id_sequences",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("last_value", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"prefix ~ '{PREFIX_PATTERN}'", name=op.f("ck_display_id_sequences_prefix_format")
        ),
        sa.CheckConstraint(
            "last_value > 0", name=op.f("ck_display_id_sequences_last_value_positive")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_display_id_sequences_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "prefix", name=op.f("pk_display_id_sequences")),
    )
    enable_tenant_rls("display_id_sequences")
    # Counters only move forward: no DELETE for the application.
    grant_app("display_id_sequences", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_table("display_id_sequences")  # drops its policies too
    op.drop_table("tenants")
