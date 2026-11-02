"""SLA policies and per-record clocks (WP-025 session 2; D-115, wp-025-plan.md §3.2).

Tenant-scoped with RLS. Policies are soft deleted; their target rows are replaced on save
(DELETE granted). `sla_applications` snapshots the targets a record started with (D-115 D7), so
editing a policy never rewrites running records. `sla_targets` holds one clock per record,
target and round (a restart after reopen opens a new round, REQ-SLA-029); `sla_pauses` is its
pause history (REQ-SLA-016). Applications, targets and pauses are never deleted (history).
Escalation levels and runs come with session 3.

Revision ID: 0047
Revises: 0044
Created: 2026-11-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0047"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('first_response', 'resolution')"
_RECORD_TYPE = "record_type ~ '^[a-z][a-z_]{1,29}$'"


# Any: these lists mix column types (datetime, uuid, int), as op.create_table accepts.
def _audit(*, deleted: bool = True) -> list[sa.Column[Any]]:
    columns: list[sa.Column[Any]] = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
    ]
    if deleted:
        columns.append(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    return columns


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _ts(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("labels", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("conditions", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("fallback", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        # Which targets the paused category pauses (§2: both by default).
        sa.Column(
            "pausing",
            postgresql.ARRAY(sa.String(length=20)),
            server_default="{first_response,resolution}",
            nullable=False,
        ),
        *_audit(),
        _tenant_fk("sla_policies"),
        sa.CheckConstraint(_RECORD_TYPE, name=op.f("ck_sla_policies_record_type_code")),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_sla_policies_name_length")
        ),
        # The fallback always applies: no conditions, always enabled.
        sa.CheckConstraint(
            "NOT fallback OR (conditions IS NULL AND enabled)",
            name=op.f("ck_sla_policies_fallback_shape"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_policies")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sla_policies_tenant_id_id"),
    )
    op.create_index(
        "uq_sla_policies_tenant_type_fallback",
        "sla_policies",
        ["tenant_id", "record_type"],
        unique=True,
        postgresql_where=sa.text("fallback AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_sla_policies_tenant_type_name",
        "sla_policies",
        ["tenant_id", "record_type", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_sla_policies_tenant_type_position",
        "sla_policies",
        ["tenant_id", "record_type", "position"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "sla_policy_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), server_default="site", nullable=False),
        sa.Column("fixed_calendar_id", sa.Uuid(), nullable=True),
        _tenant_fk("sla_policy_targets"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["sla_policies.tenant_id", "sla_policies.id"],
            name="fk_sla_policy_targets_policy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fixed_calendar_id"],
            ["sla_calendars.tenant_id", "sla_calendars.id"],
            name="fk_sla_policy_targets_calendar",
        ),
        sa.CheckConstraint(_KINDS, name=op.f("ck_sla_policy_targets_kind_code")),
        sa.CheckConstraint(
            "unit IN ('minutes', 'hours', 'business_days')",
            name=op.f("ck_sla_policy_targets_unit_code"),
        ),
        sa.CheckConstraint(
            "source IN ('site', 'group', 'fixed', 'around_the_clock')",
            name=op.f("ck_sla_policy_targets_source_code"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount BETWEEN 1 AND 100000",
            name=op.f("ck_sla_policy_targets_amount_range"),
        ),
        sa.CheckConstraint(
            "(source = 'fixed') = (fixed_calendar_id IS NOT NULL)",
            name=op.f("ck_sla_policy_targets_fixed_calendar"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_policy_targets")),
    )
    op.create_index(
        "uq_sla_policy_targets_row",
        "sla_policy_targets",
        ["tenant_id", "policy_id", "kind", sa.text("coalesce(priority, '*')")],
        unique=True,
    )
    op.create_index(
        "ix_sla_policy_targets_tenant_calendar",
        "sla_policy_targets",
        ["tenant_id", "fixed_calendar_id"],
        postgresql_where=sa.text("fixed_calendar_id IS NOT NULL"),
    )

    op.create_table(
        "sla_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("warning_percent", sa.SmallInteger(), server_default="75", nullable=False),
        sa.Column(
            "priority_rule", sa.String(length=20), server_default="recalculate", nullable=False
        ),
        sa.Column("reopen_rule", sa.String(length=20), server_default="resume", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _tenant_fk("sla_settings"),
        sa.CheckConstraint(_RECORD_TYPE, name=op.f("ck_sla_settings_record_type_code")),
        sa.CheckConstraint(
            "warning_percent BETWEEN 1 AND 99", name=op.f("ck_sla_settings_warning_range")
        ),
        sa.CheckConstraint(
            "priority_rule IN ('recalculate', 'restart')",
            name=op.f("ck_sla_settings_priority_rule_code"),
        ),
        sa.CheckConstraint(
            "reopen_rule IN ('resume', 'restart')", name=op.f("ck_sla_settings_reopen_rule_code")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "record_type", name=op.f("pk_sla_settings")),
    )

    op.create_table(
        "sla_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("policy_version", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current", sa.Boolean(), server_default="true", nullable=False),
        *_audit(deleted=False),
        _tenant_fk("sla_applications"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["sla_policies.tenant_id", "sla_policies.id"],
            name="fk_sla_applications_policy",
        ),
        sa.CheckConstraint(_RECORD_TYPE, name=op.f("ck_sla_applications_record_type_code")),
        sa.CheckConstraint(
            "reason IN ('created', 'condition_changed', 'priority_changed', 'policy_changed')",
            name=op.f("ck_sla_applications_reason_code"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_applications")),
    )
    op.create_index(
        "uq_sla_applications_current",
        "sla_applications",
        ["tenant_id", "record_id"],
        unique=True,
        postgresql_where=sa.text("current"),
    )
    op.create_index(
        "ix_sla_applications_tenant_record",
        "sla_applications",
        ["tenant_id", "record_id", "applied_at"],
    )

    op.create_table(
        "sla_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("round", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=True),
        sa.Column("target_seconds", sa.BigInteger(), nullable=False),
        sa.Column("used_seconds", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("paused_seconds", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        _ts("running_since"),
        _ts("paused_since"),
        _ts("due_at"),
        _ts("warning_at"),
        _ts("met_at"),
        sa.Column("met_how", sa.String(length=20), nullable=True),
        _ts("warned_at"),
        _ts("breached_at"),
        sa.Column("breach_seconds", sa.BigInteger(), nullable=True),
        sa.Column("breach_reason", sa.String(length=20), nullable=True),
        _ts("manual_due_at"),
        sa.Column("manual_by", sa.Uuid(), nullable=True),
        sa.Column("manual_reason", sa.String(length=500), nullable=True),
        _ts("manual_at"),
        *_audit(deleted=False),
        _tenant_fk("sla_targets"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["sla_calendars.tenant_id", "sla_calendars.id"],
            name="fk_sla_targets_calendar",
        ),
        sa.CheckConstraint(_RECORD_TYPE, name=op.f("ck_sla_targets_record_type_code")),
        sa.CheckConstraint(_KINDS, name=op.f("ck_sla_targets_kind_code")),
        sa.CheckConstraint(
            "state IN ('running', 'paused', 'met', 'breached', 'stopped')",
            name=op.f("ck_sla_targets_state_code"),
        ),
        sa.CheckConstraint(
            "met_how IS NULL OR met_how IN ('on_time', 'late', 'at_resolution')",
            name=op.f("ck_sla_targets_met_how_code"),
        ),
        sa.CheckConstraint(
            "breach_reason IS NULL OR breach_reason IN ('time_passed', 'target_changed')",
            name=op.f("ck_sla_targets_breach_reason_code"),
        ),
        sa.CheckConstraint(
            "target_seconds >= 0 AND used_seconds >= 0 AND paused_seconds >= 0",
            name=op.f("ck_sla_targets_seconds_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_targets")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sla_targets_tenant_id_id"),
    )
    op.create_index(
        "uq_sla_targets_round",
        "sla_targets",
        ["tenant_id", "record_id", "kind", "round"],
        unique=True,
    )
    # What the waker and the safety net look for (session 3): open clocks by their due moment.
    op.create_index(
        "ix_sla_targets_tenant_due",
        "sla_targets",
        ["tenant_id", "due_at"],
        postgresql_where=sa.text("state IN ('running', 'breached') AND due_at IS NOT NULL"),
    )

    op.create_table(
        "sla_pauses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        _ts("ended_at"),
        sa.Column("cause", sa.String(length=40), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("business_seconds", sa.BigInteger(), nullable=True),
        sa.Column("calendar_seconds", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _tenant_fk("sla_pauses"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_id"],
            ["sla_targets.tenant_id", "sla_targets.id"],
            name="fk_sla_pauses_target",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name=op.f("ck_sla_pauses_range_order")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_pauses")),
    )
    op.create_index(
        "ix_sla_pauses_tenant_target", "sla_pauses", ["tenant_id", "target_id", "started_at"]
    )

    for table, grants in (
        ("sla_policies", ("SELECT", "INSERT", "UPDATE")),
        ("sla_policy_targets", ("SELECT", "INSERT", "DELETE")),
        ("sla_settings", ("SELECT", "INSERT", "UPDATE")),
        ("sla_applications", ("SELECT", "INSERT", "UPDATE")),
        ("sla_targets", ("SELECT", "INSERT", "UPDATE")),
        ("sla_pauses", ("SELECT", "INSERT", "UPDATE")),
    ):
        enable_tenant_rls(table)
        grant_app(table, grants)
    for table in ("sla_policies", "sla_applications", "sla_targets"):
        enable_actor_audit(table)


def downgrade() -> None:
    for table in (
        "sla_pauses",
        "sla_targets",
        "sla_applications",
        "sla_settings",
        "sla_policy_targets",
        "sla_policies",
    ):
        op.drop_table(table)
