"""Approval reminders, escalation and clarification for requests (WP-047a S3a), 0196.

REQ-SR-034, REQ-SR-036 AC2, REQ-SR-037. Expand only, no data step:

- `work_item_type_settings.approval_reminder_after_days` (2), `approval_reminder_count` (3) and
  `approval_reminder_minute` (600, i.e. 10:00): the tenant's reminder schedule for request
  approvals (Appendix A).
- `work_item_approvals.escalated_from_id`: the primary row an escalated row was added next to
  (036 AC2: the primary stays open; the two count as one vote), with `UNIQUE (tenant_id, id)` for
  the tenant-safe self reference. The origin check gains `escalated`, and the route reason check
  gains `no_escalation_target` (the coordinator's condition 2: nobody to escalate to, so the
  administrators, recorded).
- `work_item_approvals.paused_seconds` (0): time spent waiting on a clarification, which pushes
  the reminder plan back (REQ-SR-037 AC3).
- `approval_clarifications` (RLS): a question an approver asked instead of deciding, tied to its
  conversation entries; at most one open per approval.

The downgrade stops while any tenant has an escalated approval, paused time or a clarification
(rule 5h), then drops the table and the columns and narrows the checks back.

Revision ID: 0196
Revises: 0195
Created: 2026-11-24
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0196"
down_revision: str | None = "0195"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVALS, SETTINGS, TABLE = (
    "work_item_approvals",
    "work_item_type_settings",
    "approval_clarifications",
)
ORIGIN_CHECK = "ck_work_item_approvals_origin_code"
REASON_CHECK = "ck_work_item_approvals_reason_code"
PAUSED_CHECK = "ck_work_item_approvals_paused_seconds_positive"
ESCALATED_CHECK = "ck_work_item_approvals_escalated_origin"
UNIQUE = "uq_work_item_approvals_tenant_id_id"
SELF_FK = "fk_wia_escalated_from"
ADDED_ORIGINS = ("escalated",)
ADDED_REASONS = ("no_escalation_target",)
SCHEDULE = (
    ("approval_reminder_after_days", "2"),
    ("approval_reminder_count", "3"),
    ("approval_reminder_minute", "600"),
)

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM {APPROVALS}
            WHERE escalated_from_id IS NOT NULL OR origin = 'escalated' OR paused_seconds > 0
               OR route_reason = 'no_escalation_target'
        ) OR EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has S3a request approvals', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed names, no input


def _codes_now(check: str) -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": check},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(check: str, expression: str) -> None:
    op.drop_constraint(op.f(check), APPROVALS, type_="check")
    op.create_check_constraint(op.f(check), APPROVALS, expression)


def _listed(codes: Sequence[str]) -> str:
    return ", ".join(f"'{c}'" for c in codes)


def _widen(check: str, column: str, added: Sequence[str], *, nullable: bool) -> None:
    codes = _codes_now(check)
    listed = _listed([*codes, *(c for c in added if c not in codes)])
    _recheck(
        check,
        f"{column} IS NULL OR {column} IN ({listed})" if nullable else f"{column} IN ({listed})",
    )


def _narrow(check: str, column: str, added: Sequence[str], *, nullable: bool) -> None:
    listed = _listed([c for c in _codes_now(check) if c not in added])
    _recheck(
        check,
        f"{column} IS NULL OR {column} IN ({listed})" if nullable else f"{column} IN ({listed})",
    )


def _users_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column], ["users.tenant_id", "users.id"], name=op.f(f"fk_{TABLE}_{name}")
    )


def upgrade() -> None:
    """The schedule, the escalation and pause columns, the widened codes and the table."""
    for column, default in SCHEDULE:
        op.add_column(
            SETTINGS,
            sa.Column(column, sa.SmallInteger(), server_default=default, nullable=False),
        )
    op.add_column(APPROVALS, sa.Column("escalated_from_id", sa.Uuid(), nullable=True))
    op.add_column(
        APPROVALS,
        sa.Column("paused_seconds", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_unique_constraint(UNIQUE, APPROVALS, ["tenant_id", "id"])
    op.create_foreign_key(
        SELF_FK,
        APPROVALS,
        APPROVALS,
        ["tenant_id", "escalated_from_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(op.f(PAUSED_CHECK), APPROVALS, "paused_seconds >= 0")
    op.create_check_constraint(
        op.f(ESCALATED_CHECK),
        APPROVALS,
        "escalated_from_id IS NULL OR origin IN ('escalated', 'administrators')",
    )
    _widen(ORIGIN_CHECK, "origin", ADDED_ORIGINS, nullable=False)
    _widen(REASON_CHECK, "route_reason", ADDED_REASONS, nullable=True)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("asked_by", sa.Uuid(), nullable=False),
        sa.Column("addressee", sa.String(20), nullable=False),
        sa.Column("addressee_id", sa.Uuid(), nullable=False),
        sa.Column("question_entry_id", sa.Uuid(), nullable=False),
        sa.Column("answer_entry_id", sa.Uuid(), nullable=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_how", sa.String(20), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name=op.f(f"fk_{TABLE}_work_item"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["work_item_approvals.tenant_id", "work_item_approvals.id"],
            name=op.f(f"fk_{TABLE}_approval"),
            ondelete="RESTRICT",
        ),
        _users_fk("asked_by", "asked_by"),
        _users_fk("addressee_id", "addressee"),
        sa.CheckConstraint(
            "addressee IN ('requester', 'technician')", name=op.f(f"ck_{TABLE}_addressee_code")
        ),
        sa.CheckConstraint(
            "ended_how IS NULL OR ended_how IN ('answered', 'decided', 'closed')",
            name=op.f(f"ck_{TABLE}_ended_code"),
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL) = (ended_how IS NULL)", name=op.f(f"ck_{TABLE}_ended_together")
        ),
        sa.CheckConstraint(
            "(ended_how = 'answered') = (answer_entry_id IS NOT NULL)",
            name=op.f(f"ck_{TABLE}_answered_entry"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        f"uq_{TABLE}_open",
        TABLE,
        ["tenant_id", "approval_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(f"ix_{TABLE}_tenant_item", TABLE, ["tenant_id", "work_item_id"])
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Back to before (stops while an approval was escalated, paused or asked about)."""
    op.execute(GUARD)
    op.drop_index(f"ix_{TABLE}_tenant_item", table_name=TABLE)
    op.drop_index(f"uq_{TABLE}_open", table_name=TABLE)
    op.drop_table(TABLE)
    _narrow(REASON_CHECK, "route_reason", ADDED_REASONS, nullable=True)
    _narrow(ORIGIN_CHECK, "origin", ADDED_ORIGINS, nullable=False)
    op.drop_constraint(op.f(ESCALATED_CHECK), APPROVALS, type_="check")
    op.drop_constraint(op.f(PAUSED_CHECK), APPROVALS, type_="check")
    op.drop_constraint(SELF_FK, APPROVALS, type_="foreignkey")
    op.drop_constraint(UNIQUE, APPROVALS, type_="unique")
    op.drop_column(APPROVALS, "paused_seconds")
    op.drop_column(APPROVALS, "escalated_from_id")
    for column, _default in reversed(SCHEDULE):
        op.drop_column(SETTINGS, column)
