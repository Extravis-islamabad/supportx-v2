"""Personal theme, text size and regional formats (WP-042; REQ-ADM-058, 059, 062).

Expand only: five nullable columns on `users` (theme_mode, text_scale, week_start, date_format,
time_format), each with a check. NULL means "not chosen": the default is applied when read (the
browser's theme, 100 %, the site's or tenant's formats), so a changed default never overwrites
a person's own choice. No data step. The downgrade drops the columns.

Revision ID: 0067
Revises: 0066
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS = {
    "theme_mode_code": (
        "theme_mode IS NULL OR theme_mode IN ('light', 'dark', 'high_contrast', 'system')"
    ),
    "text_scale_range": (
        "text_scale IS NULL OR (text_scale BETWEEN 90 AND 150 AND text_scale % 10 = 0)"
    ),
    "week_start_code": "week_start IS NULL OR week_start IN ('monday', 'sunday', 'saturday')",
    "date_format_code": (
        "date_format IS NULL"
        " OR date_format IN ('dd/mm/yyyy', 'mm/dd/yyyy', 'yyyy-mm-dd', 'dd.mm.yyyy')"
    ),
    "time_format_code": "time_format IS NULL OR time_format IN ('24h', '12h')",
}


def upgrade() -> None:
    op.add_column("users", sa.Column("theme_mode", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("text_scale", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("week_start", sa.String(10), nullable=True))
    op.add_column("users", sa.Column("date_format", sa.String(12), nullable=True))
    op.add_column("users", sa.Column("time_format", sa.String(4), nullable=True))
    for name, condition in _CHECKS.items():
        op.create_check_constraint(name, "users", condition)


def downgrade() -> None:
    for column in ("time_format", "date_format", "week_start", "text_scale", "theme_mode"):
        op.drop_column("users", column)  # their checks go with them
