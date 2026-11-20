"""Requester cancel and edit rules (WP-046b S5; REQ-INC-148), 0184.

Expand only, no data step:

- `work_item_type_settings.requester_cancel`: `off` (as every tenant is today: only staff
  cancel), `direct` (the requester cancels, with a reason) or `ask` (the requester asks; staff
  decide). Default `off`, so nothing changes until an admin turns it on (the coordinator's Q3,
  checked against main: requesters hold no `incidents.*` grant and the portal has no cancel).
- `work_item_type_settings.requester_edit_fields`: the fields a requester may change after
  submitting; empty (the default) means read-only apart from replying (AC2).
- `work_item_cancellation_requests`: a requester's ask to cancel (AC1), at most one pending per
  record; decided by the assignee, else the group's members with `incidents.edit`, else the
  type's service desk managers (the coordinator's Q2). RLS, the actor audit, soft delete.

The downgrade drops the table and both columns: asks waiting are dropped with it (rule 5h:
a downgrade is for a stack that never ran S5 for real).

Revision ID: 0184
Revises: 0185
Created: 2026-11-21
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0184"
# main's head now (… 0182 → 0185); re-pointed at its queue turn.
down_revision: str | None = "0185"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTINGS = "work_item_type_settings"
ASKS = "work_item_cancellation_requests"


def _audit_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    """The two settings and the asks table."""
    op.add_column(
        SETTINGS,
        sa.Column("requester_cancel", sa.String(10), server_default="off", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_work_item_type_settings_requester_cancel_code"),
        SETTINGS,
        "requester_cancel IN ('off', 'direct', 'ask')",
    )
    op.add_column(
        SETTINGS,
        sa.Column(
            "requester_edit_fields",
            postgresql.ARRAY(sa.String(80)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_work_item_type_settings_requester_edit_fields_limit"),
        SETTINGS,
        "cardinality(requester_edit_fields) <= 40",
    )
    op.create_table(
        ASKS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("state", sa.String(12), server_default="pending", nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        # Declining says why to the requester (a public reply); approving needs no note.
        sa.Column("decision_note", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ASKS}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{ASKS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wicr_work_item",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by"], ["users.tenant_id", "users.id"], name="fk_wicr_requester"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decided_by"], ["users.tenant_id", "users.id"], name="fk_wicr_decider"
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'declined', 'withdrawn')",
            name=op.f(f"ck_{ASKS}_state_code"),
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 2000", name=op.f(f"ck_{ASKS}_reason_length")
        ),
        # A decided ask names who and when; a pending one names neither.
        sa.CheckConstraint(
            "(state IN ('approved', 'declined')) = (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name=op.f(f"ck_{ASKS}_decided_shape"),
        ),
    )
    op.create_index(
        "ix_work_item_cancellation_requests_tenant_item",
        ASKS,
        ["tenant_id", "work_item_id", "created_at"],
    )
    # At most one pending ask per record (a second is 409 cancellation_already_asked).
    op.create_index(
        "uq_work_item_cancellation_requests_tenant_item_pending",
        ASKS,
        ["tenant_id", "work_item_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending' AND deleted_at IS NULL"),
    )
    enable_tenant_rls(ASKS)
    grant_app(ASKS, ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit(ASKS)


def downgrade() -> None:
    """Drop the table and both columns (their checks go with them)."""
    op.drop_table(ASKS)
    op.drop_column(SETTINGS, "requester_edit_fields")
    op.drop_column(SETTINGS, "requester_cancel")
