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
Revises: 0075
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_transitions"
NAME = "ck_work_item_transitions_action_code"
BEFORE = (
    "start_work",
    "wait_requester",
    "wait_third_party",
    "resume",
    "resolve",
    "close",
    "reopen",
    "cancel",
    "undo_cancel",
    "assign",
    "unassign",
    "approve",
    "reject",
)
AFTER = (*BEFORE, "investigate", "confirm_root_cause", "await_fix", "hold")


ENTITY_CHECK = "ck_custom_fields_entity_code"
ENTITIES_BEFORE = ("incident", "service_request")


def _check(actions: Sequence[str]) -> str:
    return "action IN (" + ", ".join(f"'{a}'" for a in actions) + ")"


def _entities(codes: Sequence[str]) -> str:
    return "entity IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def upgrade() -> None:
    """The column and the wider action list."""
    op.add_column(
        "work_items", sa.Column("status_before_pause", sa.String(length=40), nullable=True)
    )
    op.drop_constraint(op.f(NAME), TABLE, type_="check")
    op.create_check_constraint(op.f(NAME), TABLE, _check(AFTER))
    op.drop_constraint(op.f(ENTITY_CHECK), "custom_fields", type_="check")
    op.create_check_constraint(
        op.f(ENTITY_CHECK), "custom_fields", _entities((*ENTITIES_BEFORE, "problem"))
    )


def downgrade() -> None:
    """Back to the incident and service request actions and entities."""
    op.drop_constraint(op.f(ENTITY_CHECK), "custom_fields", type_="check")
    op.create_check_constraint(op.f(ENTITY_CHECK), "custom_fields", _entities(ENTITIES_BEFORE))
    op.drop_constraint(op.f(NAME), TABLE, type_="check")
    op.create_check_constraint(op.f(NAME), TABLE, _check(BEFORE))
    op.drop_column("work_items", "status_before_pause")
