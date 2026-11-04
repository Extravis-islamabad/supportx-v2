"""Roles carried by support groups (WP-042, REQ-ADM-015 AC2).

Expand only:
- `group_roles` (RLS, FORCE): a support group's roles; its members hold them while members of
  an active group. A link table like `user_roles`: the application role may read, insert and
  delete links (removing a role from a group is the link going away, audited by the API).

No data step. The downgrade drops the table (members lose the roles they held through groups).

Revision ID: 0061
Revises: 0050 (re-pointed onto the head of main when queued)
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0061"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "group_roles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_group_roles_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_group_roles_role"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "group_id", "role_id", name=op.f("pk_group_roles")),
    )
    op.create_index("ix_group_roles_tenant_role", "group_roles", ["tenant_id", "role_id"])
    enable_tenant_rls("group_roles")
    grant_app("group_roles", ("SELECT", "INSERT", "DELETE"))


def downgrade() -> None:
    op.drop_table("group_roles")
