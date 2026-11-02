"""Directory sync from Microsoft Entra ID (WP-040 session 2; REQ-INT-063, REQ-INT-064).

Expand only (D-113), no data step:
- users.directory_source: which directory keeps a synced person (entra | ldap; NULL: SupportX).
- directory_connectors (RLS, FORCE; actor audit): a directory, its sync app, scope and mapping.
- directory_people (RLS, FORCE): which SupportX person each directory person is.
- directory_memberships (RLS, FORCE): directory group members the sync reads (bookkeeping).

The downgrade drops the three sync tables and the column, and keeps every person: synced people
simply become people SupportX keeps (nothing is deleted from users).

Revision ID: 0053
Revises: 0052
Created: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_CHECK = "ck_users_directory_source_code"


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _connector_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "connector_id"],
        ["directory_connectors.tenant_id", "directory_connectors.id"],
        name=f"fk_{table}_connector",
    )


def upgrade() -> None:
    op.add_column("users", sa.Column("directory_source", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        op.f(SOURCE_CHECK),
        "users",
        "directory_source IS NULL OR directory_source IN ('entra', 'ldap')",
    )
    op.create_table(
        "directory_connectors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=20), server_default="entra", nullable=False),
        sa.Column("directory_tenant", sa.String(length=200), nullable=False),
        sa.Column("client_id", sa.String(length=200), nullable=False),
        sa.Column("credential_kind", sa.String(length=20), nullable=False),
        sa.Column("secret_ref", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(length=20), server_default="all_users", nullable=False),
        sa.Column(
            "scope_groups",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "group_mappings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("interval_minutes", sa.Integer(), server_default="30", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("users_delta_link", sa.Text(), nullable=True),
        sa.Column("groups_delta_link", sa.Text(), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("source IN ('entra')", name=op.f("ck_directory_connectors_source_code")),
        sa.CheckConstraint(
            "scope IN ('all_users', 'groups')", name=op.f("ck_directory_connectors_scope_code")
        ),
        sa.CheckConstraint(
            "credential_kind IN ('secret', 'certificate')",
            name=op.f("ck_directory_connectors_credential_kind_code"),
        ),
        sa.CheckConstraint(
            "interval_minutes BETWEEN 15 AND 1440",
            name=op.f("ck_directory_connectors_interval_range"),
        ),
        _tenant_fk("directory_connectors"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "secret_ref"],
            ["connector_secrets.tenant_id", "connector_secrets.id"],
            name="fk_directory_connectors_secret_ref",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_connectors")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_directory_connectors_tenant_id_id"),
    )
    op.create_index(
        "uq_directory_connectors_tenant_name",
        "directory_connectors",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("directory_connectors")
    enable_actor_audit("directory_connectors")
    grant_app("directory_connectors", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "directory_people",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("manager_external_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _tenant_fk("directory_people"),
        _connector_fk("directory_people"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_directory_people_user",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "connector_id", "external_id", name=op.f("pk_directory_people")
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_directory_people_tenant_user"),
    )
    enable_tenant_rls("directory_people")
    grant_app("directory_people", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "directory_memberships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("group_external_id", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        _tenant_fk("directory_memberships"),
        _connector_fk("directory_memberships"),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "connector_id",
            "group_external_id",
            "external_id",
            name=op.f("pk_directory_memberships"),
        ),
    )
    enable_tenant_rls("directory_memberships")
    grant_app("directory_memberships", ("SELECT", "INSERT", "DELETE"))


def downgrade() -> None:
    op.drop_table("directory_memberships")
    op.drop_table("directory_people")
    op.drop_table("directory_connectors")
    op.drop_constraint(op.f(SOURCE_CHECK), "users", type_="check")
    op.drop_column("users", "directory_source")
