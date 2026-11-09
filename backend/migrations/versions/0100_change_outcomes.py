"""A change's implementation outcomes (WP-045a S1; REQ-CHG-031), number from the coordinator.

Expand only, no data step: `work_item_stage_schedules.outcome` also accepts `completed` and
`backed_out` (a change's implementation: completed, backed out or failed). The check is widened
from its live definition, only these codes are added and only they are removed on the way down
(as 0092 and 0099 do), so lanes adding other codes in either order keep each other's.

The downgrade narrows the check back; while a stage still records one of these outcomes the
narrowed check fails and the downgrade stops, keeping the data (rule 5h).

Revision ID: 0100
Revises: 0099
Created: 2026-11-09
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0100"
down_revision: str | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, CHECK = "work_item_stage_schedules", "ck_work_item_stage_schedules_outcome_code"
ADDED = ("completed", "backed_out")


def _codes_now() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(op.f(CHECK), TABLE, f"outcome IS NULL OR outcome IN ({listed})")


def upgrade() -> None:
    """The implementation's two outcomes join the check."""
    now = _codes_now()
    _recheck([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Back to the check before (stops while a stage records one of these outcomes)."""
    _recheck([c for c in _codes_now() if c not in ADDED])
