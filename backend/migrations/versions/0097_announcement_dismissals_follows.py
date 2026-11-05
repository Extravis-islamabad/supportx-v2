"""A person's own state on announcements (WP-032 D7; REQ-PRT-009 AC2, AC3).

- announcement_dismissals: who dismissed which banner, so it stays dismissed on every device.
- announcement_follows: who follows which announcement, to hear when it is updated or ends.

Both are keyed (tenant_id, announcement_id, user_id), RLS, with same-tenant composite foreign
keys to the announcement and the person (cascade: the row means nothing without either).
Expand only, no data step.

Revision ID: 0097
Revises: 0096
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0097"
down_revision: str | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("announcement_dismissals", "announcement_follows")


def _table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("announcement_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{name}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "announcement_id"],
            ["announcements.tenant_id", "announcements.id"],
            ondelete="CASCADE",
            name=f"fk_{name}_announcement",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name=f"fk_{name}_user",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "announcement_id", "user_id", name=op.f(f"pk_{name}")),
    )
    op.create_index(f"ix_{name}_tenant_user", name, ["tenant_id", "user_id"])
    enable_tenant_rls(name)
    grant_app(name, ("SELECT", "INSERT", "DELETE"))


def upgrade() -> None:
    """The two tables, RLS and the app role's grants."""
    for name in TABLES:
        _table(name)


def downgrade() -> None:
    """Remove both (dismissed banners show again; follows end)."""
    for name in reversed(TABLES):
        op.drop_table(name)
