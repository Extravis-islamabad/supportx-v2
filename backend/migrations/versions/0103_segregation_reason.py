"""An approval routed away for segregation of duties (WP-045a; REQ-CHG-039), from 0099-0103.

Expand only, no data step: `work_item_approvals.route_reason` also accepts
`segregation_of_duties` (a change's implementer is never named as its approver; the approval
administrators decide instead, and the record says why). The check is widened from its live
definition, only this code is added and only it is removed on the way down (as 0098 does), so
lanes adding reasons in either order keep each other's.

The downgrade narrows the check back; while an approval still records this reason the narrowed
check fails and the downgrade stops, keeping the data (rule 5h).

Revision ID: 0103
Revises: 0102
Created: 2026-11-09
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, CHECK = "work_item_approvals", "ck_work_item_approvals_reason_code"
ADDED = ("segregation_of_duties",)


def _codes_now() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(
        op.f(CHECK), TABLE, f"route_reason IS NULL OR route_reason IN ({listed})"
    )


def upgrade() -> None:
    """The segregation reason joins the check."""
    now = _codes_now()
    _recheck([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Back to the check before (stops while an approval records this reason)."""
    _recheck([c for c in _codes_now() if c not in ADDED])
