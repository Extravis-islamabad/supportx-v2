"""Service request fulfilment (WP-047a S5; REQ-SR-047, -048, -049, -050, -056), 0204.

Expand only, no data step. `work_item_tasks` gains:

- `plan_key`: the plan step a task came from, by its key, so a step's `waits_for` finds the tasks
  it waits for (REQ-SR-047) and a changed answer finds the conditional task again (REQ-SR-048).
- `fields`: the step's own field definitions (REQ-SR-049), shape-checked by the service;
  `field_values`: what the owner filled in (an object).
- `kind`: `task`, or `asset_handover` (REQ-SR-056: completing it hands over an asset).
- `task_only`: this task alone opens task-only access to its owner, whoever they are
  (REQ-SR-050; the coordinator's condition 1), independent of the type's D-112 setting.
- `needs_review`: a conditional task no longer wanted but kept because work was done on it
  (worklogs or values; the coordinator's condition 3), for a person to decide.

Reversible; RLS unchanged (an existing table).

Revision ID: 0204
Revises: 0197
Created: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0204"
# Re-pointed at its queue turn onto main's head then (0203 when WP-047a S4 lands).
down_revision: str | None = "0197"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASKS = "work_item_tasks"


def upgrade() -> None:
    """The task's plan step, fields, values, kind and access."""
    op.add_column(TASKS, sa.Column("plan_key", sa.String(40), nullable=True))
    op.add_column(TASKS, sa.Column("fields", postgresql.JSONB(), nullable=True))
    op.add_column(
        TASKS,
        sa.Column(
            "field_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(TASKS, sa.Column("kind", sa.String(20), server_default="task", nullable=False))
    op.add_column(
        TASKS, sa.Column("task_only", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column(
        TASKS, sa.Column("needs_review", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_work_item_tasks_kind_code"), TASKS, "kind IN ('task', 'asset_handover')"
    )
    op.create_check_constraint(
        op.f("ck_work_item_tasks_field_values_object"),
        TASKS,
        "jsonb_typeof(field_values) = 'object'",
    )
    op.create_check_constraint(
        op.f("ck_work_item_tasks_fields_array"),
        TASKS,
        "fields IS NULL OR jsonb_typeof(fields) = 'array'",
    )


def downgrade() -> None:
    """Back to before (the columns hold only what S5 added)."""
    op.drop_constraint(op.f("ck_work_item_tasks_fields_array"), TASKS, type_="check")
    op.drop_constraint(op.f("ck_work_item_tasks_field_values_object"), TASKS, type_="check")
    op.drop_constraint(op.f("ck_work_item_tasks_kind_code"), TASKS, type_="check")
    for column in ("needs_review", "task_only", "kind", "field_values", "fields", "plan_key"):
        op.drop_column(TASKS, column)
