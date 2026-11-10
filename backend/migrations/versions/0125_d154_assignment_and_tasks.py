"""D-154 (Haider, 2026-11-10): assignment stays in the group; tasks start the work and say who.

- **a. No role assigns outside a record's group any more.** Someone of another group is assigned
  only by moving the record to their group in the same request, for everyone and all work-item
  types. The engine's `<type>.assign_outside_group` action is gone, so this drops every role
  grant of it, built-in and custom alike. Per tenant with app.tenant_id set (role_permissions
  forces RLS; see 0023, 0077, 0091). Each tenant's count is logged as a NOTICE.
- **c. `work_item_type_settings.first_task_starts_work`** (on): ticking a request's first
  fulfilment task moves a New or Assigned request to In progress.
- **d. `work_item_tasks.done_by`:** who ticked a task done, for "Done by <name>". Tasks done
  before this keep it empty; their history still names who did them.

The downgrade drops the two columns. The dropped grants are not restored: there are no real
customers yet (the coordinator agreed, 2026-11-10), and the permission no longer exists.

Revision ID: 0125
Revises: 0118
Created: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0125"
down_revision: str | None = "0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP = """
DO $$
DECLARE
    t uuid;
    dropped integer;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        -- The action's exact name after the type (LIKE's _ would match any character).
        DELETE FROM role_permissions WHERE split_part(permission, '.', 2) = 'assign_outside_group';
        GET DIAGNOSTICS dropped = ROW_COUNT;
        IF dropped > 0 THEN
            RAISE NOTICE '0125: tenant % lost % assign_outside_group grant(s)', t, dropped;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    """Drops the grants (counted per tenant) and adds the two columns."""
    op.execute(_DROP)
    op.add_column(
        "work_item_type_settings",
        sa.Column("first_task_starts_work", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column("work_item_tasks", sa.Column("done_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_wit_done_by",
        "work_item_tasks",
        "users",
        ["tenant_id", "done_by"],
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    """Drops the two columns; the grants stay dropped (see the module docstring)."""
    op.drop_constraint("fk_wit_done_by", "work_item_tasks", type_="foreignkey")
    op.drop_column("work_item_tasks", "done_by")
    op.drop_column("work_item_type_settings", "first_task_starts_work")
