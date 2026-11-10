"""Workflow sub-flows and approvals (WP-048b S2; ADR-043 §6; REQ-WF-014, -017; D-146).

Number from the coordinator (0106, WP-048b S2). Expand only, no data step.

Automation (sub-flows, REQ-WF-017):

- `parent_instance_id`: the instance whose sub-flow node started this one; its own tenant's
  (a composite foreign key with tenant_id first).
- `parent_command`: the parent's command that waits for this child; the child's end comes back
  to the parent as that command's result.

work_items (tasks, REQ-WF-015): `work_item_tasks.workflow_instance_id` and `workflow_command`,
the task node that opened a task (by ID only); when its tasks are done the node continues.

work_items (the approval engine, lane A's review):
- `work_item_approvals.workflow_instance_id` and purpose `workflow`: approvals a workflow's
  approval node opened. The instance is named by ID, never by a foreign key into automation's
  table (rule e).
- `work_item_approval_settings`: one row per tenant, the optional chair who breaks an exact
  majority split (D-146). Forced RLS, tenant_id first.

The downgrade drops all of it, and refuses while any tenant has a chair or a workflow approval
(rule 5h).

Revision ID: 0106
Revises: 0126
Created: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0106"
down_revision: str | None = "0126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTINGS = "work_item_approval_settings"
PURPOSE_CHECK = "ck_work_item_approvals_purpose_code"


def upgrade() -> None:
    """Add the parent link."""
    op.add_column("workflow_instances", sa.Column("parent_instance_id", sa.Uuid(), nullable=True))
    op.add_column("workflow_instances", sa.Column("parent_command", sa.String(20), nullable=True))
    op.create_foreign_key(
        "fk_workflow_instances_parent",
        "workflow_instances",
        "workflow_instances",
        ["tenant_id", "parent_instance_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_workflow_instances_parent_pair"),
        "workflow_instances",
        "(parent_instance_id IS NULL) = (parent_command IS NULL)",
    )
    op.create_index(
        "ix_workflow_instances_tenant_parent",
        "workflow_instances",
        ["tenant_id", "parent_instance_id"],
        postgresql_where=sa.text("parent_instance_id IS NOT NULL"),
    )
    _approvals()
    _tasks()


def _approvals() -> None:
    op.add_column(
        "work_item_approvals", sa.Column("workflow_instance_id", sa.Uuid(), nullable=True)
    )
    # The node's command that opened it: its decision continues that very node (several approval
    # nodes of one instance can wait at once, on parallel branches).
    op.add_column(
        "work_item_approvals", sa.Column("workflow_command", sa.String(20), nullable=True)
    )
    op.drop_constraint(op.f(PURPOSE_CHECK), "work_item_approvals", type_="check")
    op.create_check_constraint(
        op.f(PURPOSE_CHECK),
        "work_item_approvals",
        "purpose IN ('record', 'accept_without_fix', 'workflow')",
    )
    op.create_check_constraint(
        op.f("ck_work_item_approvals_workflow_instance"),
        "work_item_approvals",
        "(purpose = 'workflow') = (workflow_instance_id IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_work_item_approvals_workflow_command"),
        "work_item_approvals",
        "(workflow_instance_id IS NULL) = (workflow_command IS NULL)",
    )
    op.create_index(
        "ix_wia_tenant_workflow_instance",
        "work_item_approvals",
        ["tenant_id", "workflow_instance_id"],
        postgresql_where=sa.text("workflow_instance_id IS NOT NULL"),
    )
    op.create_table(
        SETTINGS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("chair_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "chair_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_work_item_approval_settings_chair",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f(f"pk_{SETTINGS}")),
    )
    enable_tenant_rls(SETTINGS)
    enable_actor_audit(SETTINGS)
    grant_app(SETTINGS, ("SELECT", "INSERT", "UPDATE"))


def _tasks() -> None:
    """Tasks a workflow's task node opened (REQ-WF-015): the instance and the node's command."""
    op.add_column("work_item_tasks", sa.Column("workflow_instance_id", sa.Uuid(), nullable=True))
    op.add_column("work_item_tasks", sa.Column("workflow_command", sa.String(20), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_item_tasks_workflow_pair"),
        "work_item_tasks",
        "(workflow_instance_id IS NULL) = (workflow_command IS NULL)",
    )
    op.create_index(
        "ix_wit_tenant_workflow",
        "work_item_tasks",
        ["tenant_id", "workflow_instance_id", "workflow_command"],
        postgresql_where=sa.text("workflow_instance_id IS NOT NULL"),
    )


# Rule 5h: never drop tenants' data. Each tenant is checked with app.tenant_id set, as the tables
# force RLS (a bare SELECT would see nothing and pass).
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM work_item_approval_settings WHERE chair_user_id IS NOT NULL)
           OR EXISTS (SELECT 1 FROM work_item_approvals WHERE purpose = 'workflow')
           OR EXISTS (SELECT 1 FROM work_item_tasks WHERE workflow_instance_id IS NOT NULL) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has a chair or workflow approvals or tasks', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drop the approval parts (refused while any tenant uses them), then the parent link."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_index("ix_wit_tenant_workflow", table_name="work_item_tasks")
    op.drop_constraint(op.f("ck_work_item_tasks_workflow_pair"), "work_item_tasks", type_="check")
    op.drop_column("work_item_tasks", "workflow_command")
    op.drop_column("work_item_tasks", "workflow_instance_id")
    op.drop_table(SETTINGS)
    op.drop_index("ix_wia_tenant_workflow_instance", table_name="work_item_approvals")
    op.drop_constraint(
        op.f("ck_work_item_approvals_workflow_command"), "work_item_approvals", type_="check"
    )
    op.drop_constraint(
        op.f("ck_work_item_approvals_workflow_instance"), "work_item_approvals", type_="check"
    )
    op.drop_constraint(op.f(PURPOSE_CHECK), "work_item_approvals", type_="check")
    op.create_check_constraint(
        op.f(PURPOSE_CHECK), "work_item_approvals", "purpose IN ('record', 'accept_without_fix')"
    )
    op.drop_column("work_item_approvals", "workflow_command")
    op.drop_column("work_item_approvals", "workflow_instance_id")
    op.drop_index("ix_workflow_instances_tenant_parent", table_name="workflow_instances")
    op.drop_constraint(
        op.f("ck_workflow_instances_parent_pair"), "workflow_instances", type_="check"
    )
    op.drop_constraint("fk_workflow_instances_parent", "workflow_instances", type_="foreignkey")
    op.drop_column("workflow_instances", "parent_command")
    op.drop_column("workflow_instances", "parent_instance_id")
