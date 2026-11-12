"""Task details, task templates, task dependencies (WP-046a S1; REQ-INC-040, 073..076), 0141.

Expand only, no data step:
- `work_item_tasks`: a task type, scheduled and actual start and end (an end never before its
  start), estimated minutes, percent complete (0-100), an extra cost, and a reminder some
  minutes before the scheduled start with when it went (claimed once by the sweep);
- `work_item_task_templates` (RLS): an admin's task template per work item type, its ordered
  task specs (one task or a set of up to 20), disabled when no longer offered;
- `work_item_task_dependencies` (RLS): a task waits for another task of the same record;
- `work_item_templates.tasks`: the tasks a record template creates, each with an optional
  condition (REQ-INC-040);
- `work_item_type_settings.task_dependency_mode`: an open predecessor blocks (default) or warns;
- link kind `caused_by_change` (an incident caused by a change, REQ-CHG-116's "changes that
  caused incidents") and bulk actions `cancel` and `delete` (the change list, REQ-CHG-101).

The downgrade refuses while any tenant uses what it would drop (rule 5h); otherwise it drops it.

Revision ID: 0141
Revises: 0145
Created: 2026-11-11
"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0141"
down_revision: str | None = "0145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASKS, TEMPLATES, DEPENDENCIES = (
    "work_item_tasks",
    "work_item_task_templates",
    "work_item_task_dependencies",
)
RECORD_TEMPLATES = "work_item_templates"
SETTINGS = "work_item_type_settings"
TASK_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("task_type", sa.String(40)),
    ("scheduled_start", sa.DateTime(timezone=True)),
    ("scheduled_end", sa.DateTime(timezone=True)),
    ("actual_start", sa.DateTime(timezone=True)),
    ("actual_end", sa.DateTime(timezone=True)),
    ("estimated_minutes", sa.Integer()),
    ("percent_complete", sa.SmallInteger()),
    ("extra_cost", sa.Numeric(12, 2)),
    ("remind_before_minutes", sa.Integer()),
    ("reminded_at", sa.DateTime(timezone=True)),
)
TASK_CHECKS = {
    "scheduled_order": "scheduled_end IS NULL OR scheduled_start IS NULL"
    " OR scheduled_end >= scheduled_start",
    "actual_order": "actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start",
    "estimate_range": "estimated_minutes IS NULL OR estimated_minutes BETWEEN 0 AND 525600",
    "percent_range": "percent_complete IS NULL OR percent_complete BETWEEN 0 AND 100",
    "cost_range": "extra_cost IS NULL OR extra_cost >= 0",
    "reminder_range": "remind_before_minutes IS NULL OR remind_before_minutes BETWEEN 0 AND 10080",
}
LINK_CHECK = "ck_work_item_links_kind_code"
BULK_CHECK = "ck_work_item_bulk_jobs_action_code"
WIDENED = {
    (LINK_CHECK, "work_item_links", "kind"): ("caused_by_change",),
    (BULK_CHECK, "work_item_bulk_jobs", "action"): ("cancel", "delete"),
}
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TEMPLATES})
           OR EXISTS (SELECT 1 FROM {DEPENDENCIES})
           OR EXISTS (SELECT 1 FROM {RECORD_TEMPLATES} WHERE tasks <> '[]'::jsonb)
           OR EXISTS (
               SELECT 1 FROM {TASKS} WHERE task_type IS NOT NULL OR scheduled_start IS NOT NULL
               OR scheduled_end IS NOT NULL OR actual_start IS NOT NULL OR actual_end IS NOT NULL
               OR estimated_minutes IS NOT NULL OR percent_complete IS NOT NULL
               OR extra_cost IS NOT NULL OR remind_before_minutes IS NOT NULL
           )
           OR EXISTS (SELECT 1 FROM work_item_links WHERE kind = 'caused_by_change')
           OR EXISTS (SELECT 1 FROM work_item_bulk_jobs WHERE action IN ('cancel', 'delete'))
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses task details, templates,'
                ' dependencies, change-caused links or change bulk jobs (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def _stamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now(name: str) -> list[str]:
    """The codes a `col IN (...)` check allows now, in their order (lane C's 0092 pattern)."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _replace(name: str, table: str, column: str, codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, _in(column, codes))


def upgrade() -> None:
    """The task details, the two tables, the record templates' tasks and the wider codes."""
    for name, kind in TASK_COLUMNS:
        op.add_column(TASKS, sa.Column(name, kind, nullable=True))
    for name, condition in TASK_CHECKS.items():
        op.create_check_constraint(op.f(f"ck_{TASKS}_{name}"), TASKS, condition)
    op.create_table(
        TEMPLATES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column(
            "tasks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            "jsonb_typeof(tasks) = 'array' AND jsonb_array_length(tasks) BETWEEN 1 AND 20",
            name=op.f(f"ck_{TEMPLATES}_tasks_count"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TEMPLATES}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TEMPLATES}")),
    )
    op.create_index(
        "ix_work_item_task_templates_tenant_type",
        TEMPLATES,
        ["tenant_id", "type"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(TEMPLATES)
    enable_actor_audit(TEMPLATES)
    grant_app(TEMPLATES, ("SELECT", "INSERT", "UPDATE"))
    op.create_table(
        DEPENDENCIES,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("task_id <> depends_on_id", name=op.f(f"ck_{DEPENDENCIES}_not_self")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{DEPENDENCIES}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_witd_work_item",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], [f"{TASKS}.id"], name=op.f(f"fk_{DEPENDENCIES}_task_id_{TASKS}")
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_id"],
            [f"{TASKS}.id"],
            name=op.f(f"fk_{DEPENDENCIES}_depends_on_id_{TASKS}"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "task_id", "depends_on_id", name=op.f(f"pk_{DEPENDENCIES}")
        ),
    )
    op.create_index(
        "ix_work_item_task_dependencies_tenant_depends_on",
        DEPENDENCIES,
        ["tenant_id", "depends_on_id"],
    )
    op.create_index(
        "ix_work_item_task_dependencies_tenant_item",
        DEPENDENCIES,
        ["tenant_id", "work_item_id"],
    )
    enable_tenant_rls(DEPENDENCIES)
    grant_app(DEPENDENCIES, ("SELECT", "INSERT", "DELETE"))
    op.add_column(
        RECORD_TEMPLATES,
        sa.Column(
            "tasks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
    )
    op.add_column(
        SETTINGS,
        sa.Column("task_dependency_mode", sa.String(10), server_default="block", nullable=False),
    )
    op.create_check_constraint(
        op.f(f"ck_{SETTINGS}_task_dependency_mode_code"),
        SETTINGS,
        "task_dependency_mode IN ('block', 'warn')",
    )
    for (name, table, column), codes in WIDENED.items():
        now = _codes_now(name)
        _replace(name, table, column, [*now, *(c for c in codes if c not in now)])


def downgrade() -> None:
    """Back to before (stops while any tenant uses what it would drop)."""
    op.execute(GUARD)
    for (name, table, column), codes in WIDENED.items():
        _replace(name, table, column, [c for c in _codes_now(name) if c not in codes])
    op.drop_constraint(op.f(f"ck_{SETTINGS}_task_dependency_mode_code"), SETTINGS, type_="check")
    op.drop_column(SETTINGS, "task_dependency_mode")
    op.drop_column(RECORD_TEMPLATES, "tasks")
    op.drop_index("ix_work_item_task_dependencies_tenant_item", table_name=DEPENDENCIES)
    op.drop_index("ix_work_item_task_dependencies_tenant_depends_on", table_name=DEPENDENCIES)
    op.drop_table(DEPENDENCIES)
    op.drop_index("ix_work_item_task_templates_tenant_type", table_name=TEMPLATES)
    op.drop_table(TEMPLATES)
    for name in reversed(list(TASK_CHECKS)):
        op.drop_constraint(op.f(f"ck_{TASKS}_{name}"), TASKS, type_="check")
    for name, _kind in reversed(TASK_COLUMNS):
        op.drop_column(TASKS, name)
