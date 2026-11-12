"""Worklog costs, billable time, drafts and personal timers (WP-046a S3; REQ-INC-068..070), 0147.

Expand only, no data step:
- `work_item_worklogs`: `billable`; the cost per hour taken when the time was logged
  (`cost_rate`, a snapshot: a later rate change never rewrites history) and the technician cost
  it gives (`technician_cost`, minutes x rate); `draft` for time a running timer saved when its
  record was resolved or closed (REQ-INC-069 AC2), counted only once confirmed;
- `work_item_worklog_costs` (RLS): a worklog's other costs, in the tenant's base currency, with
  the original amount, currency and the rate the person entered when it was paid in another
  (pending Haider: no automatic exchange rates, D-163 to come);
- `work_item_timers` (RLS): one running timer per person per record (REQ-INC-069), so it
  survives a reload and shows on every screen;
- `work_item_type_settings`: `worklog_block_closed` (refuse worklogs on closed records),
  `worklog_count_nonworking` (non-working hours count), `timer_auto_start` (off by default:
  an unnoticed timer makes wrong worklogs, the coordinator 2026-11-12) (REQ-INC-070).

The downgrade refuses while any tenant uses what it would drop (rule 5h); otherwise it drops it.

Revision ID: 0147
Revises: 0142
Created: 2026-11-12
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0147"
down_revision: str | None = "0142"  # re-pointed at its turn (ready-first after 0144)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKLOGS, COSTS, TIMERS = "work_item_worklogs", "work_item_worklog_costs", "work_item_timers"
SETTINGS = "work_item_type_settings"
MONEY = sa.Numeric(14, 2)
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {COSTS}) OR EXISTS (SELECT 1 FROM {TIMERS})
           OR EXISTS (
               SELECT 1 FROM {WORKLOGS}
               WHERE billable OR draft OR cost_rate IS NOT NULL
           )
           OR EXISTS (
               SELECT 1 FROM {SETTINGS}
               WHERE worklog_block_closed OR NOT worklog_count_nonworking OR timer_auto_start
           )
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has worklog costs or timers (rule 5h)', t;
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


def _entity(name: str, *columns: Any, checks: Sequence[tuple[str, str]] = ()) -> None:  # noqa: ANN401 - SQLAlchemy columns and constraints
    op.create_table(
        name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *columns,
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        *(sa.CheckConstraint(sql, name=op.f(f"ck_{name}_{label}")) for label, sql in checks),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{name}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    enable_tenant_rls(name)
    enable_actor_audit(name)
    grant_app(name, ("SELECT", "INSERT", "UPDATE"))


def _record_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "work_item_id"], ["work_items.tenant_id", "work_items.id"], name=name
    )


def upgrade() -> None:
    """Worklog cost columns, other costs, timers and the worklog settings."""
    op.add_column(
        WORKLOGS, sa.Column("billable", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(WORKLOGS, sa.Column("cost_rate", MONEY, nullable=True))
    op.add_column(WORKLOGS, sa.Column("technician_cost", MONEY, nullable=True))
    op.add_column(
        WORKLOGS, sa.Column("draft", sa.Boolean(), server_default="false", nullable=False)
    )
    op.create_check_constraint(
        op.f(f"ck_{WORKLOGS}_cost_rate_not_negative"),
        WORKLOGS,
        "cost_rate IS NULL OR cost_rate >= 0",
    )
    op.create_check_constraint(
        op.f(f"ck_{WORKLOGS}_cost_with_rate"),
        WORKLOGS,
        "(cost_rate IS NULL) = (technician_cost IS NULL)",
    )
    _entity(
        COSTS,
        sa.Column("worklog_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),  # the base currency
        sa.Column("original_amount", MONEY, nullable=True),
        sa.Column("original_currency", sa.String(3), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(18, 8), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        _record_fk("fk_wiwc_work_item"),
        sa.ForeignKeyConstraint(
            ["worklog_id"], [f"{WORKLOGS}.id"], name=op.f(f"fk_{COSTS}_worklog_id_{WORKLOGS}")
        ),
        checks=[
            ("amount_not_negative", "amount >= 0"),
            ("currency_format", "original_currency IS NULL OR original_currency ~ '^[A-Z]{3}$'"),
            (
                "original_together",
                (
                    "(original_amount IS NULL) = (original_currency IS NULL)"
                    " AND (original_amount IS NULL) = (exchange_rate IS NULL)"
                ),
            ),
            ("rate_positive", "exchange_rate IS NULL OR exchange_rate > 0"),
        ],
    )
    op.create_index(
        "ix_wiwc_tenant_worklog",
        COSTS,
        ["tenant_id", "worklog_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_wiwc_tenant_item",
        COSTS,
        ["tenant_id", "work_item_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    _entity(
        TIMERS,
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.String(500), nullable=True),
        sa.Column("auto_started", sa.Boolean(), server_default="false", nullable=False),
        _record_fk("fk_wit_work_item"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_wit_user"
        ),
    )
    # One running timer per person per record.
    op.create_index(
        "ux_wit_tenant_item_user",
        TIMERS,
        ["tenant_id", "work_item_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_wit_tenant_user",
        TIMERS,
        ["tenant_id", "user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    for name, default in (
        ("worklog_block_closed", "false"),
        ("worklog_count_nonworking", "true"),
        ("timer_auto_start", "false"),
    ):
        op.add_column(
            SETTINGS, sa.Column(name, sa.Boolean(), server_default=default, nullable=False)
        )


def downgrade() -> None:
    """Back to before (refused while any tenant uses the costs, timers or settings)."""
    op.execute(GUARD)
    for name in ("timer_auto_start", "worklog_count_nonworking", "worklog_block_closed"):
        op.drop_column(SETTINGS, name)
    op.drop_table(TIMERS)
    op.drop_table(COSTS)
    op.drop_constraint(op.f(f"ck_{WORKLOGS}_cost_with_rate"), WORKLOGS, type_="check")
    op.drop_constraint(op.f(f"ck_{WORKLOGS}_cost_rate_not_negative"), WORKLOGS, type_="check")
    for name in ("draft", "technician_cost", "cost_rate", "billable"):
        op.drop_column(WORKLOGS, name)
