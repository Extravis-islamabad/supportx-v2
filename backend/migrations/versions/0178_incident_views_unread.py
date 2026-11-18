"""Incident views, unread markers and the shared-view audit (WP-046b S3a; D-176), 0178.

Expand only, no data step:
- `work_item_view_favourites`: a person's starred saved views, so they show first in the
  picker. Tenant first in the primary key, RLS forced. Personal: un-starring removes the row
  (a link row, as task dependencies in 0141), and removing a view removes its stars.
- `work_item_reads`: the version of a record someone last opened, for unread markers. Tenant
  first in the primary key, RLS forced; personal, moved forward only, removed with the person.

- `work_item_views.unshared_at`, `unshared_field`: when the shared-view audit (D-176) made a
  view private and the filter field that caused it, for the administrators' report.

No data step: who sees a shared view is decided on every read from this release on, and the
audit job (every six hours, through the service, with history, events and the owner's notice)
makes the offending ones private on its first run. The clean-up completes when that run ends.

The downgrade drops both tables and the two columns: stars and read markers are conveniences,
rebuilt by use. Views the audit made private stay private (nothing says what they were shared
with before, so nothing is restored).

Revision ID: 0178
Revises: 0177
Created: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import disable_tenant_rls, enable_tenant_rls, grant_app

revision: str = "0178"
# Placeholder until its queue turn: main's head then (0176 → 0175 → 0177 → 0178 as agreed).
down_revision: str | None = "0177"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FAVOURITES = "work_item_view_favourites"
READS = "work_item_reads"


def upgrade() -> None:
    """Add both tables and the audit's two columns."""
    op.create_table(
        FAVOURITES,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("view_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{FAVOURITES}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_wivf_user"
        ),
        sa.ForeignKeyConstraint(
            ["view_id"],
            ["work_item_views.id"],
            name=op.f(f"fk_{FAVOURITES}_view_id_work_item_views"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "view_id", name=op.f(f"pk_{FAVOURITES}")),
    )
    op.create_index(
        "ix_work_item_view_favourites_tenant_view", FAVOURITES, ["tenant_id", "view_id"]
    )
    enable_tenant_rls(FAVOURITES)
    grant_app(FAVOURITES, ("SELECT", "INSERT", "DELETE"))
    op.create_table(
        READS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("seen_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{READS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_wir_user"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wir_work_item",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "work_item_id", name=op.f(f"pk_{READS}")),
    )
    enable_tenant_rls(READS)
    grant_app(READS, ("SELECT", "INSERT", "UPDATE", "DELETE"))
    op.add_column(
        "work_item_views", sa.Column("unshared_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("work_item_views", sa.Column("unshared_field", sa.String(80), nullable=True))


def downgrade() -> None:
    """Drop both tables and the two columns (views made private stay private)."""
    op.drop_column("work_item_views", "unshared_field")
    op.drop_column("work_item_views", "unshared_at")
    disable_tenant_rls(READS)
    op.drop_table(READS)
    disable_tenant_rls(FAVOURITES)
    op.drop_table(FAVOURITES)
