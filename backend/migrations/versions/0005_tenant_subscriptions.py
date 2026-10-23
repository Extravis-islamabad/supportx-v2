"""Tenant subscriptions: each tenant's plan for the entitlement interface (WP-009).

Platform table (allowlisted in tooling/rls_guard.py): the application reads only its own tenant's
row and cannot write; plans are written by platform tooling as supportx_migrator.

Revision ID: 0005
Revises: 0004
Created: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.shared.db.rls import APP_ROLE, CURRENT_TENANT_SQL, MIGRATOR_ROLE
from migrations.helpers import grant_app

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_subscriptions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("edition", sa.String(), nullable=False),
        sa.Column("features", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column(
            "limits", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("maintenance_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_days", sa.Integer(), server_default="14", nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "edition IN ('essentials', 'professional', 'enterprise')",
            name=op.f("ck_tenant_subscriptions_edition_code"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name=op.f("ck_tenant_subscriptions_status_code")
        ),
        sa.CheckConstraint(
            "grace_days BETWEEN 0 AND 90", name=op.f("ck_tenant_subscriptions_grace_days_range")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(limits) = 'object'", name=op.f("ck_tenant_subscriptions_limits_object")
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > starts_at",
            name=op.f("ck_tenant_subscriptions_term_order"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_subscriptions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_subscriptions")),
    )
    op.execute("ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_subscriptions FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_subscriptions_self_select ON tenant_subscriptions FOR SELECT "
        f"TO {APP_ROLE} USING (tenant_id = {CURRENT_TENANT_SQL})"
    )
    # Platform tooling writes plans for any tenant, but always inside that tenant's context so the
    # entitlement.changed event lands in the right tenant's outbox (service/subscriptions.py).
    op.execute(
        f"CREATE POLICY tenant_subscriptions_platform_admin ON tenant_subscriptions FOR ALL "
        f"TO {MIGRATOR_ROLE} USING (true) WITH CHECK (true)"
    )
    grant_app("tenant_subscriptions", ("SELECT",))


def downgrade() -> None:
    op.drop_table("tenant_subscriptions")  # drops its policies too
