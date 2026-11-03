"""People may edit their own contact details (WP-028; REQ-PRT-013 AC2, lane B review on #178).

Expand only, no data step: identity_settings.people_edit_contact, off by default. On, a person
changes their own phone and mobile in My account (portal and console), unless a directory keeps
them; off, the fields are read-only and the API refuses. The downgrade drops the column.

Numbered 0058 to stay clear of open branches (0054 WP-025, 0055 WP-040/041); re-pointed after
main's head before merge (one Alembic head, docs/LANES.md).

Revision ID: 0058
Revises: 0051
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the setting, off for every tenant."""
    op.add_column(
        "identity_settings",
        sa.Column("people_edit_contact", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    """Drop the setting (the contact details themselves stay)."""
    op.drop_column("identity_settings", "people_edit_contact")
