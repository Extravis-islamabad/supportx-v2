"""A change linked to the record it was made for (WP-045a D6; REQ-CHG-002), number 0115.

Expand only, no data step: `work_item_links.kind` also accepts `change_for` (a change -> the
incident, request, problem or release it was raised for). The check is widened from its live
definition, only this code is added and only it is removed on the way down (as 0104 does), so
lanes adding kinds in either order keep each other's.

The downgrade narrows the check back; while a link of this kind exists the narrowed check
fails and the downgrade stops, keeping the data (rule 5h).

Revision ID: 0115
Revises: 0103
Created: 2026-11-09
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0115"
down_revision: str | None = "0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, CHECK = "work_item_links", "ck_work_item_links_kind_code"
ADDED = ("change_for",)


def _codes_now() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(op.f(CHECK), TABLE, f"kind IN ({listed})")


def upgrade() -> None:
    """`change_for` joins the link kinds."""
    now = _codes_now()
    _recheck([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Back to the kinds before (stops while a change_for link exists)."""
    _recheck([c for c in _codes_now() if c not in ADDED])
