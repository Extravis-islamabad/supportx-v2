"""Change tasks per stage, the review date, and child changes (WP-045d S1), number 0133.

Expand only, no data step:
- `work_item_tasks.stage`: the stage a staged record's task belongs to (REQ-CHG-088); empty for
  every task made before, and for other types.
- `work_item_change_details`: `review_due_at` (the post-implementation review's date,
  REQ-CHG-091), `review_reminded_at` and `schedule_reminded_at` (when its reminder and the
  implementation window's went, so each goes once; the notices come with S3).
- `work_item_links.kind` also accepts `part_of_change`: a child change or a release -> the
  change it is part of (REQ-CHG-096). The check is widened from its live definition, only this
  code is added and only it is removed on the way down (as 0115 does), so lanes adding kinds in
  either order keep each other's.

The downgrade drops the columns while no task has a stage and no review date or reminder is
set, and narrows the check while no such link exists; otherwise it stops and keeps the data
(rule 5h).

Revision ID: 0133
Revises: 0132
Created: 2026-11-11
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0133"
down_revision: str | None = "0132"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASKS, DETAILS, LINKS = "work_item_tasks", "work_item_change_details", "work_item_links"
CHECK = "ck_work_item_links_kind_code"
ADDED = ("part_of_change",)
REVIEW = ("review_due_at", "review_reminded_at", "schedule_reminded_at")
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TASKS} WHERE stage IS NOT NULL) OR EXISTS (
            SELECT 1 FROM {DETAILS}
            WHERE review_due_at IS NOT NULL OR review_reminded_at IS NOT NULL
                OR schedule_reminded_at IS NOT NULL
        ) OR EXISTS (SELECT 1 FROM {LINKS} WHERE kind = 'part_of_change') THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has stage tasks, review dates or child changes (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def _codes_now() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(CHECK), LINKS, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(op.f(CHECK), LINKS, f"kind IN ({listed})")


def upgrade() -> None:
    """Task stages, the review date and reminders, and `part_of_change` links."""
    op.add_column(TASKS, sa.Column("stage", sa.String(40), nullable=True))
    for column in REVIEW:
        op.add_column(DETAILS, sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    now = _codes_now()
    _recheck([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Back to before (stops while a stage task, a review date or a child change exists)."""
    op.execute(GUARD)
    _recheck([c for c in _codes_now() if c not in ADDED])
    for column in reversed(REVIEW):
        op.drop_column(DETAILS, column)
    op.drop_column(TASKS, "stage")
