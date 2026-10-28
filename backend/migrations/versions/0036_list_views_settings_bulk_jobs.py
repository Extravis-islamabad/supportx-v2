"""Saved views, list settings and bulk jobs (WP-020d; REQ-INC-104, 106, 110, 119, 120).

- work_item_views: a user's saved view (the list API's filter and sort, columns), private,
  shared with chosen support groups, or shared with everyone;
- work_item_list_settings: one user's columns, sort and page size per view;
- work_item_bulk_jobs: a bulk change of up to 1,000 frozen records with a result per record;
- field_changes.batch_id: the job that made a person's change on their behalf, so each
  record's history names the bulk job (REQ-INC-120 AC4).

All tenant-scoped with RLS and actor audit. Additive and reversible.

Revision ID: 0036
Revises: 0035
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("field_changes", sa.Column("batch_id", sa.UUID(), nullable=True))
    op.create_table(
        "work_item_bulk_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column(
            "changes", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("record_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("done_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "results", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "action IN ('edit', 'assign', 'take', 'resolve', 'close')",
            name=op.f("ck_work_item_bulk_jobs_action_code"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name=op.f("ck_work_item_bulk_jobs_status_code"),
        ),
        sa.CheckConstraint(
            "type IN ('incident', 'service_request', 'problem', 'change', 'release')",
            name=op.f("ck_work_item_bulk_jobs_type_code"),
        ),
        sa.CheckConstraint(
            "cardinality(record_ids) BETWEEN 1 AND 1000",
            name=op.f("ck_work_item_bulk_jobs_record_limit"),
        ),
        sa.CheckConstraint(
            "processed BETWEEN 0 AND total", name=op.f("ck_work_item_bulk_jobs_processed_range")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_work_item_bulk_jobs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_bulk_jobs")),
    )
    op.create_index(
        "ix_wibj_tenant_creator_created",
        "work_item_bulk_jobs",
        ["tenant_id", "created_by", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_wibj_tenant_pending",
        "work_item_bulk_jobs",
        ["tenant_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued', 'running') AND deleted_at IS NULL"),
    )
    enable_tenant_rls("work_item_bulk_jobs")
    enable_actor_audit("work_item_bulk_jobs")
    grant_app("work_item_bulk_jobs", ("SELECT", "INSERT", "UPDATE"))
    op.create_table(
        "work_item_list_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("view_key", sa.String(length=60), nullable=False),
        sa.Column(
            "columns", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("sort", sa.String(length=200), nullable=True),
        sa.Column("page_size", sa.Integer(), server_default="50", nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('incident', 'service_request', 'problem', 'change', 'release')",
            name=op.f("ck_work_item_list_settings_type_code"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(columns) <= 40",
            name=op.f("ck_work_item_list_settings_columns_limit"),
        ),
        sa.CheckConstraint(
            "page_size IN (25, 50, 100)", name=op.f("ck_work_item_list_settings_page_size_choice")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_wils_user"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_work_item_list_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_list_settings")),
    )
    op.create_index(
        "uq_wils_tenant_user_type_view",
        "work_item_list_settings",
        ["tenant_id", "user_id", "type", "view_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("work_item_list_settings")
    enable_actor_audit("work_item_list_settings")
    grant_app("work_item_list_settings", ("SELECT", "INSERT", "UPDATE"))
    op.create_table(
        "work_item_views",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("visibility", sa.String(length=10), nullable=False),
        sa.Column("group_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False),
        sa.Column("filter", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "columns", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("sort", sa.String(length=200), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('incident', 'service_request', 'problem', 'change', 'release')",
            name=op.f("ck_work_item_views_type_code"),
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'groups', 'everyone')",
            name=op.f("ck_work_item_views_visibility_code"),
        ),
        sa.CheckConstraint(
            "(visibility = 'groups') = (cardinality(group_ids) > 0) "
            "AND cardinality(group_ids) <= 50",
            name=op.f("ck_work_item_views_groups_when_shared_with_groups"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(columns) <= 40", name=op.f("ck_work_item_views_columns_limit")
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 120", name=op.f("ck_work_item_views_name_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_wiv_owner"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_work_item_views_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_views")),
    )
    op.create_index(
        "ix_wiv_tenant_type_shared",
        "work_item_views",
        ["tenant_id", "type"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL AND visibility <> 'private'"),
    )
    op.create_index(
        "uq_wiv_tenant_type_owner_name",
        "work_item_views",
        ["tenant_id", "type", "owner_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("work_item_views")
    enable_actor_audit("work_item_views")
    grant_app("work_item_views", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_index(
        "uq_wiv_tenant_type_owner_name",
        table_name="work_item_views",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_wiv_tenant_type_shared",
        table_name="work_item_views",
        postgresql_where=sa.text("deleted_at IS NULL AND visibility <> 'private'"),
    )
    op.drop_table("work_item_views")
    op.drop_index(
        "uq_wils_tenant_user_type_view",
        table_name="work_item_list_settings",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("work_item_list_settings")
    op.drop_index(
        "ix_wibj_tenant_pending",
        table_name="work_item_bulk_jobs",
        postgresql_where=sa.text("status IN ('queued', 'running') AND deleted_at IS NULL"),
    )
    op.drop_index("ix_wibj_tenant_creator_created", table_name="work_item_bulk_jobs")
    op.drop_table("work_item_bulk_jobs")
    op.drop_column("field_changes", "batch_id")
