"""Dashboards (WP-036; parity file 09 REQ-DSH-*): user-made dashboards and dashboard choices.

Tenant-scoped with RLS. A dashboard is one versioned document (widgets, places, filter
defaults); built-in dashboards are code. Preferences are one row per person (home and
favourites); role defaults one row per role.

Revision ID: 0034
Revises: 0033
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "names", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("shared", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("copied_from", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 120", name=op.f("ck_dashboards_name_length")
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 1000",
            name=op.f("ck_dashboards_description_length"),
        ),
        sa.CheckConstraint("jsonb_typeof(body) = 'object'", name=op.f("ck_dashboards_body_object")),
        sa.CheckConstraint("pg_column_size(body) <= 262144", name=op.f("ck_dashboards_body_size")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_dashboards_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_dashboards_owner"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboards")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_dashboards_tenant_id_id"),
    )
    op.create_index("ix_dashboards_tenant_owner", "dashboards", ["tenant_id", "owner_id", "name"])
    op.create_index(
        "ix_dashboards_tenant_shared",
        "dashboards",
        ["tenant_id", "name"],
        postgresql_where=sa.text("shared AND deleted_at IS NULL"),
    )
    enable_tenant_rls("dashboards")
    enable_actor_audit("dashboards")
    grant_app("dashboards", ("SELECT", "INSERT", "UPDATE"))  # soft delete only

    op.create_table(
        "dashboard_preferences",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("home_ref", sa.String(length=100), nullable=True),
        sa.Column(
            "favourites",
            postgresql.ARRAY(sa.String(length=100)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "home_ref IS NULL OR char_length(home_ref) BETWEEN 1 AND 100",
            name=op.f("ck_dashboard_preferences_home_ref_length"),
        ),
        sa.CheckConstraint(
            "cardinality(favourites) <= 200",
            name=op.f("ck_dashboard_preferences_favourites_count"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_dashboard_preferences_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_dashboard_preferences_user",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name=op.f("pk_dashboard_preferences")),
    )
    enable_tenant_rls("dashboard_preferences")
    grant_app("dashboard_preferences", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "dashboard_role_defaults",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role_key", sa.String(length=63), nullable=False),
        sa.Column("dashboard_ref", sa.String(length=100), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(dashboard_ref) BETWEEN 1 AND 100",
            name=op.f("ck_dashboard_role_defaults_dashboard_ref_length"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_dashboard_role_defaults_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "role_key ~ '^[a-z][a-z0-9_]{1,62}$'",
            name=op.f("ck_dashboard_role_defaults_role_key_format"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "role_key", name=op.f("pk_dashboard_role_defaults")),
    )
    enable_tenant_rls("dashboard_role_defaults")
    grant_app("dashboard_role_defaults", ("SELECT", "INSERT", "UPDATE", "DELETE"))


def downgrade() -> None:
    op.drop_table("dashboard_role_defaults")
    op.drop_table("dashboard_preferences")
    op.drop_table("dashboards")
