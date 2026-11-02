"""SLA escalation levels and runs; SLA states on records (WP-025 session 3; wp-025-plan.md §3.2).

`sla_escalation_levels` belong to a policy and a target kind, replaced on save like the target
rows (DELETE granted). `sla_escalation_runs` holds one run per target clock and level, unique by
(target, level): a level can never run twice for the same clock (REQ-SLA-022 AC3), whatever
the waker or the safety net do. Runs are never deleted (history).

`work_items` gets each target's state and a breached flag (expand only, nullable or defaulted):
lists, filters and the "about to breach" and "breached" views read them (REQ-SLA-019 AC2,
REQ-SLA-020 AC4).

Revision ID: 0054
Revises: 0047
Created: 2026-11-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0054"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('first_response', 'resolution')"
_STATES = "IN ('running', 'warning', 'paused', 'met', 'breached', 'stopped')"


# Any: a DateTime column, as op.create_table accepts.
def _now(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "sla_escalation_levels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("anchor", sa.String(length=20), nullable=False),
        sa.Column("offset_seconds", sa.Integer(), nullable=False),
        sa.Column("recipients", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("fallback", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("actions", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("notify", sa.Boolean(), server_default="true", nullable=False),
        _now("created_at"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_sla_escalation_levels_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["sla_policies.tenant_id", "sla_policies.id"],
            name="fk_sla_escalation_levels_policy",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(_KINDS, name=op.f("ck_sla_escalation_levels_kind_code")),
        sa.CheckConstraint(
            "anchor IN ('due', 'warning')", name=op.f("ck_sla_escalation_levels_anchor_code")
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 8", name=op.f("ck_sla_escalation_levels_position_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_escalation_levels")),
    )
    op.create_index(
        "uq_sla_escalation_levels_position",
        "sla_escalation_levels",
        ["tenant_id", "policy_id", "kind", "position"],
        unique=True,
    )

    op.create_table(
        "sla_escalation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("level_key", sa.String(length=40), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("level", postgresql.JSONB(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="waiting", nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", postgresql.JSONB(), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_sla_escalation_runs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_id"],
            ["sla_targets.tenant_id", "sla_targets.id"],
            name="fk_sla_escalation_runs_target",
        ),
        sa.CheckConstraint(
            "state IN ('waiting', 'ran', 'cancelled')",
            name=op.f("ck_sla_escalation_runs_state_code"),
        ),
        sa.CheckConstraint(
            "(state = 'ran') = (ran_at IS NOT NULL)", name=op.f("ck_sla_escalation_runs_ran")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_escalation_runs")),
    )
    # Exactly once (REQ-SLA-022 AC3, REQ-SLA-037 AC2): one run per clock and level.
    op.create_index(
        "uq_sla_escalation_runs_level",
        "sla_escalation_runs",
        ["tenant_id", "target_id", "level_key"],
        unique=True,
    )
    # What the waker and the safety net look for: waiting runs by their moment.
    op.create_index(
        "ix_sla_escalation_runs_tenant_due",
        "sla_escalation_runs",
        ["tenant_id", "due_at"],
        postgresql_where=sa.text("state = 'waiting' AND due_at IS NOT NULL"),
    )
    # The safety net also looks for warnings that are due.
    op.create_index(
        "ix_sla_targets_tenant_warning",
        "sla_targets",
        ["tenant_id", "warning_at"],
        postgresql_where=sa.text(
            "state = 'running' AND warned_at IS NULL AND warning_at IS NOT NULL"
        ),
    )
    for table, grants in (
        ("sla_escalation_levels", ("SELECT", "INSERT", "DELETE")),
        ("sla_escalation_runs", ("SELECT", "INSERT", "UPDATE")),
    ):
        enable_tenant_rls(table)
        grant_app(table, grants)

    for kind in ("first_response", "resolution"):
        op.add_column("work_items", sa.Column(f"{kind}_sla_state", sa.String(20), nullable=True))
        op.add_column(
            "work_items",
            sa.Column(f"{kind}_breached", sa.Boolean(), server_default="false", nullable=False),
        )
        op.create_check_constraint(
            f"ck_work_items_{kind}_sla_state_code",
            "work_items",
            f"{kind}_sla_state IS NULL OR {kind}_sla_state {_STATES}",
        )
        op.create_index(
            f"ix_work_items_tenant_{kind}_sla_state",
            "work_items",
            ["tenant_id", f"{kind}_sla_state"],
            postgresql_where=sa.text(f"{kind}_sla_state IN ('warning', 'breached')"),
        )


def downgrade() -> None:
    for kind in ("first_response", "resolution"):
        op.drop_index(f"ix_work_items_tenant_{kind}_sla_state", table_name="work_items")
        op.drop_constraint(f"ck_work_items_{kind}_sla_state_code", "work_items", type_="check")
        op.drop_column("work_items", f"{kind}_breached")
        op.drop_column("work_items", f"{kind}_sla_state")
    op.drop_index("ix_sla_targets_tenant_warning", table_name="sla_targets")
    op.drop_table("sla_escalation_runs")
    op.drop_table("sla_escalation_levels")
