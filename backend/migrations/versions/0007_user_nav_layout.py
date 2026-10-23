"""Users: navigation layout preference (WP-011).

Top bar (default), side bar or compact side bar: a per-user preference stored server-side so it
follows the user to every device. Additive with a default (expand only; reversible).

Revision ID: 0007
Revises: 0006
Created: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LAYOUTS = ("top", "side", "side_compact")


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("nav_layout", sa.String(), server_default="top", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_users_nav_layout_code"),
        "users",
        "nav_layout IN (" + ", ".join(f"'{code}'" for code in LAYOUTS) + ")",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_nav_layout_code"), "users", type_="check")
    op.drop_column("users", "nav_layout")
