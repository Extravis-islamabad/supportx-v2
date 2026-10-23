"""Announcements module (WP-012, ADR-024): announcements, audience links, module settings.

All tenant-scoped with RLS. Announcements are soft-deleted only (no DELETE grant); the audience
link rows are replaced on edit (DELETE granted). Same-tenant composite foreign keys to users,
sites and support groups.

Revision ID: 0009
Revises: 0008
Created: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _link_table(name: str, unit_column: str, unit_table: str) -> None:
    op.create_table(
        name,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("announcement_id", sa.Uuid(), nullable=False),
        sa.Column(unit_column, sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{name}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "announcement_id"],
            ["announcements.tenant_id", "announcements.id"],
            name=f"fk_{name}_announcement",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", unit_column],
            [f"{unit_table}.tenant_id", f"{unit_table}.id"],
            name=f"fk_{name}_{unit_column.removesuffix('_id')}",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "announcement_id", unit_column, name=op.f(f"pk_{name}")
        ),
    )
    op.create_index(
        f"ix_{name}_tenant_{unit_column.removesuffix('_id')}", name, ["tenant_id", unit_column]
    )
    enable_tenant_rls(name)
    grant_app(name, ("SELECT", "INSERT", "DELETE"))


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("display_id", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), server_default="info", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("audience", sa.String(length=20), server_default="everyone", nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("show_as_banner", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("publish_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
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
            "length(btrim(title)) BETWEEN 1 AND 200", name=op.f("ck_announcements_title_length")
        ),
        sa.CheckConstraint(
            "length(btrim(body)) BETWEEN 1 AND 20000", name=op.f("ck_announcements_body_length")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name=op.f("ck_announcements_status_code"),
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name=op.f("ck_announcements_severity_code"),
        ),
        sa.CheckConstraint(
            "audience IN ('everyone', 'sites', 'groups')",
            name=op.f("ck_announcements_audience_code"),
        ),
        sa.CheckConstraint(
            "publish_until IS NULL OR publish_from IS NULL OR publish_until > publish_from",
            name=op.f("ck_announcements_window_order"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_announcements_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_announcements_owner",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_announcements")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_announcements_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "display_id", name="uq_announcements_tenant_id_display_id"
        ),
    )
    op.create_index(
        "ix_announcements_tenant_updated", "announcements", ["tenant_id", "updated_at", "id"]
    )
    op.create_index(
        "ix_announcements_tenant_status_updated",
        "announcements",
        ["tenant_id", "status", "updated_at", "id"],
    )
    op.create_index("ix_announcements_tenant_owner", "announcements", ["tenant_id", "owner_id"])
    op.create_index(
        "ix_announcements_tenant_published",
        "announcements",
        ["tenant_id", "publish_from", "publish_until"],
        postgresql_where=sa.text("status = 'published' AND deleted_at IS NULL"),
    )
    enable_tenant_rls("announcements")
    enable_actor_audit("announcements")
    grant_app("announcements", ("SELECT", "INSERT", "UPDATE"))  # soft delete only

    _link_table("announcement_sites", "site_id", "sites")
    _link_table("announcement_groups", "group_id", "support_groups")

    op.create_table(
        "announcement_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("require_second_publisher", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_announcement_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_announcement_settings")),
    )
    enable_tenant_rls("announcement_settings")
    grant_app("announcement_settings", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    for table in (
        "announcement_settings",
        "announcement_groups",
        "announcement_sites",
        "announcements",
    ):
        op.drop_table(table)
