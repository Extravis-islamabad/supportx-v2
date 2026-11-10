"""Changes' own pick lists (WP-045a; REQ-CHG-005, -011), number from the coordinator (0099-0103).

Expand only, no data step: `work_item_reasons.list` also accepts `change_type` and
`change_reason` (never shared with releases); their seeds are made per tenant on first use.
The check is widened from its live definition, only these codes are added and only they are
removed on the way down (as 0092 does), so lanes adding codes in either order keep each other's.

The downgrade narrows the check back; while a tenant still has change types or reasons the
narrowed check fails and the downgrade stops, keeping the data (rule 5h; lane C's condition).

Revision ID: 0102
Revises: 0101
Created: 2026-11-09
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0102"
down_revision: str | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, CHECK = "work_item_reasons", "ck_work_item_reasons_list_code"
ADDED = ("change_type", "change_reason")


def _codes_now() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(op.f(CHECK), TABLE, f"list IN ({listed})")


def upgrade() -> None:
    """The two change lists join the check."""
    now = _codes_now()
    _recheck([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Back to the check before (stops while change types or reasons exist)."""
    _recheck([c for c in _codes_now() if c not in ADDED])
