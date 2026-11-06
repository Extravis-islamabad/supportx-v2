"""Workflow sub-flows: a child instance names its parent (WP-048b S2; ADR-043 §6; REQ-WF-017).

Number from the coordinator (0106, WP-048b S2). Expand only, no data step: two nullable columns
on `workflow_instances`, and an index to find a parent's children.

- `parent_instance_id`: the instance whose sub-flow node started this one; its own tenant's
  (a composite foreign key with tenant_id first).
- `parent_command`: the parent's command that waits for this child; the child's end comes back
  to the parent as that command's result.

The downgrade drops the index and both columns.

Revision ID: 0106
Revises: 0105
Created: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0106"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def downgrade() -> None:
    """Drop the parent link."""
    op.drop_index("ix_workflow_instances_tenant_parent", table_name="workflow_instances")
    op.drop_constraint(
        op.f("ck_workflow_instances_parent_pair"), "workflow_instances", type_="check"
    )
    op.drop_constraint("fk_workflow_instances_parent", "workflow_instances", type_="foreignkey")
    op.drop_column("workflow_instances", "parent_command")
    op.drop_column("workflow_instances", "parent_instance_id")
