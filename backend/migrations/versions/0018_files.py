"""Files and safe attachments (WP-022, ADR-028, D-082).

Tables (all tenant-scoped with RLS):

- files: one stored file (encrypted object, sniffed type, scan state). The app may read, insert,
  update and delete: rows are deleted only when a file is purged, after its object.
- file_links: where a file is attached (incident, reply or note, editor draft); one per file.
- tenant_data_keys: per-tenant data keys wrapped by the installation key ring. Never deleted by
  the app (offboarding deletes them deliberately: crypto-shredding).
- tenant_storage_usage: bytes and files counted against the `storage_gb` licence limit.
- file_settings: a tenant's size and type rules.

Additive (expand only; reversible).

Revision ID: 0018
Revises: 0017
Created: 2026-10-26
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[datetime]]:
    return [
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
    ]


def _actors() -> list[sa.Column[uuid.UUID]]:
    return [
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
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
        "files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("active_markup", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("scan_signature", sa.String(length=200), nullable=True),
        sa.Column("scan_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_stripped", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("data_key_id", sa.UUID(), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column("stored_size", sa.BigInteger(), nullable=False),
        sa.Column("thumb_key", sa.String(length=300), nullable=True),
        sa.Column("thumb_size", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        *_actors(),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('scanning', 'clean', 'infected', 'scan_failed', 'not_scanned', 'deleted')",
            name=op.f("ck_files_state"),
        ),
        sa.CheckConstraint(
            "source IN ('ui', 'api', 'email', 'portal')", name=op.f("ck_files_source")
        ),
        sa.CheckConstraint("kind IN ('image', 'pdf', 'other')", name=op.f("ck_files_kind")),
        sa.CheckConstraint("size >= 0", name=op.f("ck_files_size")),
        _tenant_fk("files"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_files_tenant_id_id")),
    )
    op.create_index(op.f("ix_files_tenant_id_state"), "files", ["tenant_id", "state"])
    op.create_index(
        op.f("ix_files_tenant_id_purge_after"),
        "files",
        ["tenant_id", "purge_after"],
        postgresql_where=sa.text("purge_after IS NOT NULL"),
    )

    op.create_table(
        "file_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("owner_type", sa.String(length=30), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=True),
        sa.Column("inline", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        *_actors(),
        sa.CheckConstraint(
            "owner_type IN ('work_item', 'conversation_entry', 'draft')",
            name=op.f("ck_file_links_owner_type"),
        ),
        sa.CheckConstraint(
            "(owner_type = 'draft') = (record_id IS NULL)",
            name=op.f("ck_file_links_draft_has_no_record"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["files.tenant_id", "files.id"],
            name=op.f("fk_file_links_tenant_id_files"),
            ondelete="CASCADE",
        ),
        _tenant_fk("file_links"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_links")),
        sa.UniqueConstraint("tenant_id", "file_id", name=op.f("uq_file_links_tenant_id_file_id")),
    )
    op.create_index(
        op.f("ix_file_links_tenant_id_record_type_record_id"),
        "file_links",
        ["tenant_id", "record_type", "record_id"],
    )
    op.create_index(
        op.f("ix_file_links_tenant_id_owner_type_owner_id"),
        "file_links",
        ["tenant_id", "owner_type", "owner_id"],
    )

    op.create_table(
        "tenant_data_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=False),
        sa.Column("wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _tenant_fk("tenant_data_keys"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_data_keys")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_tenant_data_keys_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_tenant_data_keys_tenant_id_created_at"),
        "tenant_data_keys",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "tenant_storage_usage",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("bytes_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("files_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "bytes_used >= 0 AND files_count >= 0",
            name=op.f("ck_tenant_storage_usage_not_negative"),
        ),
        _tenant_fk("tenant_storage_usage"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_storage_usage")),
    )

    op.create_table(
        "file_settings",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("max_file_mb", sa.Integer(), server_default="25", nullable=False),
        sa.Column("max_batch", sa.Integer(), server_default="20", nullable=False),
        sa.Column("blocked_extensions", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        *_timestamps(),
        *_actors(),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "max_file_mb BETWEEN 1 AND 100", name=op.f("ck_file_settings_max_file_mb")
        ),
        sa.CheckConstraint("max_batch BETWEEN 1 AND 50", name=op.f("ck_file_settings_max_batch")),
        _tenant_fk("file_settings"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_file_settings")),
    )

    for table in ("files", "file_links"):
        enable_tenant_rls(table)
        grant_app(table)  # rows are deleted only by the purge, after their objects
        enable_actor_audit(table)
    enable_tenant_rls("tenant_data_keys")
    grant_app("tenant_data_keys", ("SELECT", "INSERT", "UPDATE"))
    enable_tenant_rls("tenant_storage_usage")
    grant_app("tenant_storage_usage", ("SELECT", "INSERT", "UPDATE"))
    enable_tenant_rls("file_settings")
    grant_app("file_settings", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("file_settings")


def downgrade() -> None:
    for table in (
        "file_settings",
        "tenant_storage_usage",
        "tenant_data_keys",
        "file_links",
        "files",
    ):
        op.drop_table(table)
