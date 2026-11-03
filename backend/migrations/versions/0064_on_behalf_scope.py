"""Whom a requester may raise a request for (WP-030 s1; REQ-SR-011).

Expand only: work_item_type_settings.on_behalf_scope, one of same_department, same_site,
all_requesters, all_users (their own direct reports always count); default same_department,
the narrowest. Checked by the service when a requester raises a record for someone else.

Revision ID: 0064
Revises: 0063
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPES = ("same_department", "same_site", "all_requesters", "all_users")


def upgrade() -> None:
    """Add the setting with its check."""
    op.add_column(
        "work_item_type_settings",
        sa.Column(
            "on_behalf_scope",
            sa.String(length=20),
            server_default="same_department",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_work_item_type_settings_on_behalf_scope_code"),
        "work_item_type_settings",
        "on_behalf_scope IN (" + ", ".join(f"'{s}'" for s in SCOPES) + ")",
    )


def downgrade() -> None:
    """Drop the setting."""
    op.drop_constraint(
        op.f("ck_work_item_type_settings_on_behalf_scope_code"),
        "work_item_type_settings",
        type_="check",
    )
    op.drop_column("work_item_type_settings", "on_behalf_scope")
