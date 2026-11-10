"""People acknowledge the assets they are given (WP-049a s4; REQ-AST-023).

`asset_acknowledgements`: one per holding of an asset whose product type asks for it, for the
person who now holds it. Pending until they accept or dispute it (with a comment), with when
and through which channel. A dispute never changes the holding or its history.

The downgrade refuses while any tenant has an acknowledgement (rule 5h).

Revision ID: 0112
Revises: 0111
Created: 2026-11-06
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0112"
down_revision: str | None = "0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("pending", "accepted", "disputed")
CHANNELS = ("portal", "console", "mail")


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR {column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "asset_acknowledgements",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{v}'" for v in STATUSES) + ")",
            name=op.f("ck_asset_acknowledgements_status"),
        ),
        sa.CheckConstraint(
            _in("channel", CHANNELS), name=op.f("ck_asset_acknowledgements_channel")
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (answered_at IS NULL)",
            name=op.f("ck_asset_acknowledgements_answered"),
        ),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment) BETWEEN 1 AND 2000",
            name=op.f("ck_asset_acknowledgements_comment"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_asset_acknowledgements_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_acknowledgements_asset",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["asset_assignments.id"],
            name="fk_asset_acknowledgements_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_acknowledgements_user",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_acknowledgements")),
    )
    op.create_index(
        "uq_asset_acknowledgements_assignment",
        "asset_acknowledgements",
        ["tenant_id", "assignment_id"],
        unique=True,
    )
    op.create_index(
        "ix_asset_acknowledgements_user",
        "asset_acknowledgements",
        ["tenant_id", "user_id", "status"],
    )
    enable_tenant_rls("asset_acknowledgements")
    grant_app("asset_acknowledgements", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_acknowledgements")


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM asset_acknowledgements) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has acknowledgements (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the table only while no tenant has an acknowledgement; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table("asset_acknowledgements")
