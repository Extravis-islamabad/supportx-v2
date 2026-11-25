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

`catalog_items.workflow_id`: the item's fulfilment workflow (REQ-SR-053), checked by the
service (a workflow of the service request type); and `workflow_instances.started_how` gains
`catalog_item` for a run the item started.

Reversible; RLS unchanged (existing tables).

Revision ID: 0204
Revises: 0202
Created: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0204"
# On main's head 0202 (lane B's #623); re-pointed at its queue turn if main moves on.
down_revision: str | None = "0202"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASKS = "work_item_tasks"
ITEMS = "catalog_items"
INSTANCES = "workflow_instances"
HOW = "started_how_code"  # the model's name; the naming convention adds ck_<table>_
HOW_BEFORE = "started_how IN ('template', 'trigger', 'manual', 'sub_flow')"
HOW_AFTER = "started_how IN ('template', 'trigger', 'manual', 'sub_flow', 'catalog_item')"


# One pass per tenant (business tables force RLS, even for the migrator; see 0023).
BACK_TO_TRIGGER = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE workflow_instances SET started_how = 'trigger'
            WHERE tenant_id = t AND started_how = 'catalog_item';
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


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
    op.add_column(ITEMS, sa.Column("workflow_id", sa.Uuid(), nullable=True))
    op.drop_constraint(op.f(f"ck_{INSTANCES}_{HOW}"), INSTANCES, type_="check")
    op.create_check_constraint(op.f(f"ck_{INSTANCES}_{HOW}"), INSTANCES, HOW_AFTER)


def downgrade() -> None:
    """Back to before (the columns hold only what S5 added).

    A run the item started reads as a trigger's again, so the narrower check holds.
    """
    op.execute(BACK_TO_TRIGGER)
    op.drop_constraint(op.f(f"ck_{INSTANCES}_{HOW}"), INSTANCES, type_="check")
    op.create_check_constraint(op.f(f"ck_{INSTANCES}_{HOW}"), INSTANCES, HOW_BEFORE)
    op.drop_column(ITEMS, "workflow_id")
    op.drop_constraint(op.f("ck_work_item_tasks_fields_array"), TASKS, type_="check")
    op.drop_constraint(op.f("ck_work_item_tasks_field_values_object"), TASKS, type_="check")
    op.drop_constraint(op.f("ck_work_item_tasks_kind_code"), TASKS, type_="check")
    for column in ("needs_review", "task_only", "kind", "field_values", "fields", "plan_key"):
        op.drop_column(TASKS, column)
