"""Problems on the work-item engine (WP-044a s1; REQ-PRB-001, -023, Appendix A).

- work_items.status_before_pause: where a problem put on hold resumes (Appendix A: "on hold →
  the status it was paused from"), set when a record enters a paused status by `hold`, like
  status_before_cancel for undo_cancel.
- work_item_transitions' action check also accepts the problem actions (investigate,
  confirm_root_cause, await_fix, hold).
- custom_fields may belong to problems (entity `problem`), as to incidents and requests.

Expand only, no data step (0077 maps saved role grants). The downgrade restores the old action
list and drops the column; it refuses while a tenant's life cycle still uses the new actions
(the check would fail), which keeps data intact.

Revision ID: 0076
Revises: 0074
Created: 2026-11-05
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_transitions"
NAME = "ck_work_item_transitions_action_code"
PROBLEM_ACTIONS = ("investigate", "confirm_root_cause", "await_fix", "hold")


ENTITY_CHECK = "ck_custom_fields_entity_code"


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now(name: str) -> list[str]:
    """The codes a `col IN (...)` check allows now, in their order (lane C's 0092 pattern)."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _widen(table: str, column: str, name: str, codes: Sequence[str]) -> None:
    """Add only these codes to the live check: other lanes' codes stay, in either order."""
    now = _codes_now(name)
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(
        op.f(name), table, _in(column, [*now, *(c for c in codes if c not in now)])
    )


def _narrow(table: str, column: str, name: str, codes: Sequence[str]) -> None:
    """Remove only these codes from the live check."""
    now = _codes_now(name)
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, _in(column, [c for c in now if c not in codes]))


def upgrade() -> None:
    """The column and the wider action list."""
    op.add_column(
        "work_items", sa.Column("status_before_pause", sa.String(length=40), nullable=True)
    )
    _widen(TABLE, "action", NAME, PROBLEM_ACTIONS)
    _widen("custom_fields", "entity", ENTITY_CHECK, ("problem",))


def downgrade() -> None:
    """Back to the incident and service request actions and entities."""
    _narrow("custom_fields", "entity", ENTITY_CHECK, ("problem",))
    _narrow(TABLE, "action", NAME, PROBLEM_ACTIONS)
    op.drop_column("work_items", "status_before_pause")
