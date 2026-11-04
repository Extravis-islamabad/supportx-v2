"""Announcements for requesters only or technicians only (WP-042, REQ-ADM-077).

Expand only: the audience check also accepts `requesters` and `technicians`. No data step.
The downgrade restores the old check; it fails while any announcement uses a new audience, so
no row is changed silently (rule 5h).

Revision ID: 0068
Revises: 0067
Created: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The naming convention adds the "ck_announcements_" prefix on create; op.f() keeps a full name.
_NAME = "ck_announcements_audience_code"
_OLD = "audience IN ('everyone', 'sites', 'groups')"
_NEW = "audience IN ('everyone', 'sites', 'groups', 'requesters', 'technicians')"


def upgrade() -> None:
    op.drop_constraint(op.f(_NAME), "announcements", type_="check")
    op.create_check_constraint("audience_code", "announcements", _NEW)


def downgrade() -> None:
    op.drop_constraint(op.f(_NAME), "announcements", type_="check")
    op.create_check_constraint("audience_code", "announcements", _OLD)
