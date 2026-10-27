"""Reports (WP-035, ADR-033): folders, saved reports, favourites; reads for supportx_report.

All tenant-scoped with RLS. Folders and reports are soft-deleted only (no DELETE grant);
favourites are removed by DELETE. supportx_report (created by tooling/sql/roles.sql) may SELECT
the tables the incident reporting source reads: the incident list query and its scope
(work_items, work_item_followers) and field history (backlog, time in status).

Revision ID: 0027
Revises: 0024
Created: 2026-10-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    enable_actor_audit,
    enable_tenant_rls,
    grant_app,
    grant_report,
    revoke_report,
)

revision: str = "0027"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPORT_READS = ("work_items", "work_item_followers", "field_changes")


def _entity_columns() -> list[sa.Column[Any]]:
    return [
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
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "report_folders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        *_entity_columns(),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 120", name=op.f("ck_report_folders_name_length")
        ),
        _tenant_fk("report_folders"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_report_folders_owner",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_folders")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_report_folders_tenant_id_id"),
    )
    op.create_index(
        "uq_report_folders_tenant_name",
        "report_folders",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("report_folders")
    enable_actor_audit("report_folders")
    grant_app("report_folders", ("SELECT", "INSERT", "UPDATE"))  # soft delete only

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("copied_from", sa.String(length=80), nullable=True),
        *_entity_columns(),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_reports_name_length")
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 1000",
            name=op.f("ck_reports_description_length"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(definition) = 'object'", name=op.f("ck_reports_definition_object")
        ),
        sa.CheckConstraint(
            "pg_column_size(definition) <= 32768", name=op.f("ck_reports_definition_size")
        ),
        _tenant_fk("reports"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_reports_owner"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "folder_id"],
            ["report_folders.tenant_id", "report_folders.id"],
            name="fk_reports_folder",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_reports_tenant_id_id"),
    )
    op.create_index(
        "ix_reports_tenant_owner_private",
        "reports",
        ["tenant_id", "owner_id", "updated_at", "id"],
        postgresql_where=sa.text("folder_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_reports_tenant_folder", "reports", ["tenant_id", "folder_id", "name"])
    enable_tenant_rls("reports")
    enable_actor_audit("reports")
    grant_app("reports", ("SELECT", "INSERT", "UPDATE"))  # soft delete only

    op.create_table(
        "report_favourites",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("report_ref", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(report_ref) BETWEEN 1 AND 100",
            name=op.f("ck_report_favourites_ref_length"),
        ),
        _tenant_fk("report_favourites"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_report_favourites_user",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "user_id", "report_ref", name=op.f("pk_report_favourites")
        ),
    )
    enable_tenant_rls("report_favourites")
    grant_app("report_favourites", ("SELECT", "INSERT", "DELETE"))

    for table in REPORT_READS:
        grant_report(table)


def downgrade() -> None:
    for table in REPORT_READS:
        revoke_report(table)
    for table in ("report_favourites", "reports", "report_folders"):
        op.drop_table(table)
