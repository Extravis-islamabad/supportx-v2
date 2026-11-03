"""Approve and reject: the approval engine's system actions (WP-030, REQ-SR-004).

Expand only, no data step: the transitions table's action check also accepts `approve` and
`reject`, which only the system runs (a service request's final approval or rejection). The
downgrade restores the old list; it refuses while a tenant's life cycle still uses them (the
check would fail), which keeps data intact.

Revision ID: 0059
Revises: 0051
Created: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059"
down_revision: str | None = "0051"
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
)
AFTER = (*BEFORE, "approve", "reject")


def _check(actions: Sequence[str]) -> str:
    return "action IN (" + ", ".join(f"'{a}'" for a in actions) + ")"


def upgrade() -> None:
    """Accept the two system actions."""
    op.drop_constraint(op.f(NAME), TABLE, type_="check")
    op.create_check_constraint(op.f(NAME), TABLE, _check(AFTER))


def downgrade() -> None:
    """Back to the incident actions only."""
    op.drop_constraint(op.f(NAME), TABLE, type_="check")
    op.create_check_constraint(op.f(NAME), TABLE, _check(BEFORE))
