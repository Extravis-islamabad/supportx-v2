"""Resolution, closure, reopen (WP-020f; REQ-INC-051, 090, 093-098, 100).

- work_items.resolution: the fix, rich text (sanitised like the description), asked by Resolve;
- work_items.closure_code: a code of the `closure_code` pick list, asked by Close;
- work_items.follows_id: a requester reply after the reopen window starts a new record that
  follows this one (REQ-INC-098; WP-020e's links take it over);
- work_items.resolution_notified_at: when the requester was told of the resolution. Auto-close
  counts from it and never closes a record whose requester was not told (product owner,
  2026-10-28);
- work_item_type_settings: closure rules (fields required to resolve and to close), open-work
  handling, auto-close (off until a channel can tell requesters), the reopen window;
- work_item_statuses.resume_on_requester_reply: a requester reply moves a paused record back to
  in progress (on for "awaiting requester", REQ-INC-051).

Additive and reversible; the tables keep their RLS.

Revision ID: 0033
Revises: 0032
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("work_items", sa.Column("resolution", sa.Text(), nullable=True))
    op.add_column("work_items", sa.Column("closure_code", sa.String(length=40), nullable=True))
    op.add_column("work_items", sa.Column("follows_id", sa.UUID(), nullable=True))
    op.add_column(
        "work_items",
        sa.Column("resolution_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Auto-close looks for resolved records the requester was told about.
    op.create_index(
        "ix_wi_resolution_notified",
        "work_items",
        ["tenant_id", "resolution_notified_at"],
        postgresql_where=sa.text(
            "status_category = 'resolved' AND resolution_notified_at IS NOT NULL"
        ),
    )

    settings = "work_item_type_settings"
    op.add_column(
        settings,
        sa.Column(
            "resolve_requires",
            postgresql.ARRAY(sa.String(length=60)),
            server_default=sa.text("'{resolution}'"),
            nullable=False,
        ),
    )
    op.add_column(
        settings,
        sa.Column(
            "close_requires",
            postgresql.ARRAY(sa.String(length=60)),
            server_default=sa.text("'{closure_code}'"),
            nullable=False,
        ),
    )
    op.add_column(
        settings,
        sa.Column(
            "open_work",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        settings,
        sa.Column(
            "complete_open_work", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(settings, sa.Column("auto_close_days", sa.Integer(), nullable=True))
    op.add_column(
        settings,
        sa.Column("reopen_window_days", sa.Integer(), server_default=sa.text("7"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_work_item_type_settings_auto_close_days_range"),
        settings,
        "auto_close_days IS NULL OR auto_close_days BETWEEN 1 AND 30",
    )
    op.create_check_constraint(
        op.f("ck_work_item_type_settings_reopen_window_days_range"),
        settings,
        "reopen_window_days BETWEEN 1 AND 30",
    )

    op.add_column(
        "work_item_statuses",
        sa.Column(
            "resume_on_requester_reply",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    # Appendix A: awaiting requester -> in progress on a requester reply (on by default).
    op.execute(
        "UPDATE work_item_statuses SET resume_on_requester_reply = true"
        " WHERE code = 'awaiting_requester'"
    )


def downgrade() -> None:
    op.drop_column("work_item_statuses", "resume_on_requester_reply")
    settings = "work_item_type_settings"
    op.drop_constraint(op.f("ck_work_item_type_settings_reopen_window_days_range"), settings)
    op.drop_constraint(op.f("ck_work_item_type_settings_auto_close_days_range"), settings)
    for column in (
        "reopen_window_days",
        "auto_close_days",
        "complete_open_work",
        "open_work",
        "close_requires",
        "resolve_requires",
    ):
        op.drop_column(settings, column)
    op.drop_index("ix_wi_resolution_notified", table_name="work_items")
    for column in ("resolution_notified_at", "follows_id", "closure_code", "resolution"):
        op.drop_column("work_items", column)
