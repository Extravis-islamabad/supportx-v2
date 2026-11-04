"""Two portal settings (WP-028), both off by default.

- identity_settings.people_edit_contact (REQ-PRT-013 AC2, lane B review on #178): on, a person
  changes their own phone and mobile in My account (portal and console), unless a directory
  keeps them; off, the fields are read-only and the API refuses.
- work_item_type_settings.portal_show_due_time (REQ-INC-147, plan D5): requesters see the
  expected resolution time of their records.

Expand only, no data step. The downgrade drops both columns.

Numbered 0058 to stay clear of open branches (0054 WP-025, 0055 WP-040/041); re-pointed after
main's head before merge (one Alembic head, docs/LANES.md).

Revision ID: 0058
Revises: 0050
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add both settings, off for every tenant."""
    op.add_column(
        "identity_settings",
        sa.Column("people_edit_contact", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "work_item_type_settings",
        sa.Column("portal_show_due_time", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    """Drop both settings (the contact details themselves stay)."""
    op.drop_column("work_item_type_settings", "portal_show_due_time")
    op.drop_column("identity_settings", "people_edit_contact")
