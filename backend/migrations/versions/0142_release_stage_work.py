"""Worklogs by stage and the release's open-stage-tasks setting (WP-058b S3; REQ-REL-048).

Expand only, no data step:
- `work_item_worklogs.stage`: a staged record's stage when the time was logged, set by the
  service (lane A's OK; WP-046a S3 builds on it). Existing worklogs keep none.
- `work_item_type_settings.open_stage_tasks_block`: releases, a stage with open tasks cannot be
  left (default on).

The downgrade stops while any worklog has a stage or any tenant turned the setting off (rule 5h).

Revision ID: 0142
Revises: 0140
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0142"
down_revision: str | None = "0140"  # re-pointed at its turn (ready-first with 0141, after 0145)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKLOGS, SETTINGS = "work_item_worklogs", "work_item_type_settings"
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {WORKLOGS} WHERE stage IS NOT NULL)
            OR EXISTS (SELECT 1 FROM {SETTINGS} WHERE NOT open_stage_tasks_block) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has worklogs by stage or the stage-task setting off (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def upgrade() -> None:
    """The worklog's stage and the release setting."""
    op.add_column(WORKLOGS, sa.Column("stage", sa.String(40), nullable=True))
    op.add_column(
        SETTINGS,
        sa.Column("open_stage_tasks_block", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    """Back to before (stops while a worklog has a stage or the setting is off)."""
    op.execute(GUARD)
    op.drop_column(SETTINGS, "open_stage_tasks_block")
    op.drop_column(WORKLOGS, "stage")
