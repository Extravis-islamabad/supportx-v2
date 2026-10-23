"""Authorization: roles, role permissions, user roles; sites, support groups, memberships (WP-016).

All tenant-scoped with RLS. Link tables use same-tenant composite foreign keys, so a role or
membership can never point at another tenant's user, role, site or group even though foreign-key
checks bypass row-level security.

Revision ID: 0006
Revises: 0005
Created: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _entity_columns() -> list[sa.Column[Any]]:
    """id, tenant_id and the audit/version columns of a TenantEntity."""
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
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


def _unit_table(name: str) -> None:
    op.create_table(
        name,
        *_entity_columns(),
        sa.Column("name", sa.String(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f(f"ck_{name}_name_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{name}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{name}_tenant_id_id"),
    )
    op.create_index(
        f"uq_{name}_tenant_id_name",
        name,
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(name)
    enable_actor_audit(name)
    grant_app(name, ("SELECT", "INSERT", "UPDATE"))  # soft delete only


def _member_table(name: str, unit_column: str, unit_table: str) -> None:
    op.create_table(
        name,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(unit_column, sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{name}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", unit_column],
            [f"{unit_table}.tenant_id", f"{unit_table}.id"],
            name=f"fk_{name}_{unit_column.removesuffix('_id')}",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name=f"fk_{name}_user"
        ),
        sa.PrimaryKeyConstraint("tenant_id", unit_column, "user_id", name=op.f(f"pk_{name}")),
    )
    op.create_index(f"ix_{name}_tenant_user", name, ["tenant_id", "user_id"])
    enable_tenant_rls(name)
    grant_app(name, ("SELECT", "INSERT", "DELETE"))


def upgrade() -> None:
    op.add_column("users", sa.Column("roles_mapped_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_users_tenant_id_id", "users", ["tenant_id", "id"])

    op.create_table(
        "roles",
        *_entity_columns(),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{1,62}$'", name=op.f("ck_roles_key_format")),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_roles_name_length")
        ),
        sa.CheckConstraint(
            "char_length(description) <= 1000", name=op.f("ck_roles_description_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_roles_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id_id"),
    )
    op.create_index(
        "uq_roles_tenant_id_key",
        "roles",
        ["tenant_id", "key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("roles")
    enable_actor_audit("roles")
    grant_app("roles", ("SELECT", "INSERT", "UPDATE"))  # soft delete only

    op.create_table(
        "role_permissions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("condition", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "scope IN ('all', 'site', 'group', 'own')", name=op.f("ck_role_permissions_scope_code")
        ),
        sa.CheckConstraint(
            "permission ~ '^[a-z][a-z_]*\\.[a-z][a-z_]*$'",
            name=op.f("ck_role_permissions_permission_format"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_role_permissions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_role_permissions_role",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "role_id", "permission", name=op.f("pk_role_permissions")
        ),
    )
    enable_tenant_rls("role_permissions")
    grant_app("role_permissions")

    op.create_table(
        "user_roles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_user_roles_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_user_roles_user"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_user_roles_role"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "role_id", name=op.f("pk_user_roles")),
    )
    op.create_index("ix_user_roles_tenant_role", "user_roles", ["tenant_id", "role_id"])
    enable_tenant_rls("user_roles")
    grant_app("user_roles", ("SELECT", "INSERT", "DELETE"))

    _unit_table("sites")
    _unit_table("support_groups")
    _member_table("site_members", "site_id", "sites")
    _member_table("group_members", "group_id", "support_groups")


def downgrade() -> None:
    for table in (
        "group_members",
        "site_members",
        "support_groups",
        "sites",
        "user_roles",
        "role_permissions",
        "roles",
    ):
        op.drop_table(table)
    op.drop_constraint("uq_users_tenant_id_id", "users", type_="unique")
    op.drop_column("users", "roles_mapped_at")
