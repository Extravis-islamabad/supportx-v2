"""Roles, plan sections, stage schedules and downtimes (WP-058a s4; REQ-REL-023..028; ADR-041).

Type-generic engine tables (releases now; changes reuse them, shapes checked by lane A against
file 05), number from the coordinator. Expand only, no data step: seeds are made per tenant on
first use. Every table forces RLS; every key carries tenant_id.

- `work_item_role_defs`: a type's named roles (REQ-REL-023, REQ-CHG-035): labels, description,
  `single` (one holder) or several, who may hold it (`eligibility`: permissions, groups, people),
  `system` for seeded ones; retired, never deleted.
- `work_item_role_holders`: who holds a role on a record, a person or a group (REQ-CHG-034);
  exactly one of the two, each at most once per role.
- `work_item_plan_sections`: rich-text plan sections (REQ-REL-025), each with its own version,
  so two people editing different sections both keep their work.
- `work_item_stage_schedules`: per record and stage, scheduled and actual dates, the outcome,
  notes and issues (REQ-REL-026, -028).
- `work_item_downtimes`: planned or actual downtime windows with the affected services and
  configuration items (REQ-REL-027, REQ-CHG-063); no foreign key to them until the CMDB lands.
- `work_item_reasons.list` also accepts `downtime_kind`, widened from its live definition (as
  0092), so lanes landing other lists in either order keep each other's.

The downgrade drops the tables and narrows the list check back (stopping while downtime kinds
exist, keeping the data).

Revision ID: 0095
Revises: 0094
Created: 2026-11-05
"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0095"
down_revision: str | None = "0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = "type IN ('incident', 'service_request', 'problem', 'change', 'release')"
CODE = "^[a-z][a-z0-9_]{1,39}$"
LIST_CHECK = "ck_work_item_reasons_list_code"
ADDED_LISTS = ("downtime_kind",)
DML = ("SELECT", "INSERT", "UPDATE")


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now(name: str) -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(LIST_CHECK), "work_item_reasons", type_="check")
    op.create_check_constraint(op.f(LIST_CHECK), "work_item_reasons", _in("list", codes))


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _work_item_fk(table: str, column: str = "work_item_id") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        ["work_items.id"],
        name=op.f(f"fk_{table}_{column}_work_items"),
        ondelete="CASCADE",
    )


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


def _secure(table: str, grants: Sequence[str] = DML, *, actors: bool = True) -> None:
    enable_tenant_rls(table)
    if actors:
        enable_actor_audit(table)
    grant_app(table, tuple(grants))


def _role_tables() -> None:
    op.create_table(
        "work_item_role_defs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        sa.Column("description", postgresql.JSONB(), nullable=True),
        sa.Column("single", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("eligibility", postgresql.JSONB(), nullable=True),
        sa.Column("system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(TYPES, name=op.f("ck_work_item_role_defs_type_code")),
        sa.CheckConstraint(f"code ~ '{CODE}'", name=op.f("ck_work_item_role_defs_code_format")),
        sa.CheckConstraint(
            "eligibility IS NULL OR jsonb_typeof(eligibility) = 'object'",
            name=op.f("ck_work_item_role_defs_eligibility_object"),
        ),
        _tenant_fk("work_item_role_defs"),
        sa.PrimaryKeyConstraint("tenant_id", "type", "code", name=op.f("pk_work_item_role_defs")),
    )
    _secure("work_item_role_defs", actors=False)

    table = "work_item_role_holders"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (group_id IS NULL)", name=op.f(f"ck_{table}_one_holder")
        ),
        _tenant_fk(table),
        _work_item_fk(table),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type", "role"],
            [
                "work_item_role_defs.tenant_id",
                "work_item_role_defs.type",
                "work_item_role_defs.code",
            ],
            name=op.f(f"fk_{table}_role"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f(f"fk_{table}_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name=op.f(f"fk_{table}_group"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    )
    op.create_index(
        "uq_work_item_role_holders_user",
        table,
        ["tenant_id", "work_item_id", "role", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_work_item_role_holders_group",
        table,
        ["tenant_id", "work_item_id", "role", "group_id"],
        unique=True,
        postgresql_where=sa.text("group_id IS NOT NULL"),
    )
    # "My releases" and the own scope look holders up by person and by group.
    op.create_index("ix_work_item_role_holders_tenant_user", table, ["tenant_id", "user_id"])
    op.create_index("ix_work_item_role_holders_tenant_group", table, ["tenant_id", "group_id"])
    _secure(table, (*DML, "DELETE"))


def _plan_and_schedule_tables() -> None:
    table = "work_item_plan_sections"
    op.create_table(
        table,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("section", sa.String(40), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_stamps(),
        sa.CheckConstraint(f"section ~ '{CODE}'", name=op.f(f"ck_{table}_section_format")),
        _tenant_fk(table),
        _work_item_fk(table),
        sa.PrimaryKeyConstraint("tenant_id", "work_item_id", "section", name=op.f(f"pk_{table}")),
    )
    _secure(table)

    table = "work_item_stage_schedules"
    op.create_table(
        table,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("outcome_notes", sa.Text(), nullable=True),
        sa.Column("issues", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('passed', 'failed', 'partly_done')",
            name=op.f(f"ck_{table}_outcome_code"),
        ),
        sa.CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end >= scheduled_start",
            name=op.f(f"ck_{table}_scheduled_order"),
        ),
        sa.CheckConstraint(
            "actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start",
            name=op.f(f"ck_{table}_actual_order"),
        ),
        _tenant_fk(table),
        _work_item_fk(table),
        sa.PrimaryKeyConstraint("tenant_id", "work_item_id", "stage", name=op.f(f"pk_{table}")),
    )
    # REQ-REL-026 AC3 "behind schedule": the current stage's scheduled end, by tenant.
    op.create_index(
        "ix_work_item_stage_schedules_tenant_end",
        table,
        ["tenant_id", "scheduled_end"],
        postgresql_where=sa.text("scheduled_end IS NOT NULL"),
    )
    _secure(table)


def _downtime_table() -> None:
    table = "work_item_downtimes"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(10), server_default="planned", nullable=False),
        sa.Column("kind", sa.String(40), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("service_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("ci_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("source_work_item_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint("phase IN ('planned', 'actual')", name=op.f(f"ck_{table}_phase_code")),
        sa.CheckConstraint("ends_at >= starts_at", name=op.f(f"ck_{table}_order")),
        _tenant_fk(table),
        _work_item_fk(table),
        sa.ForeignKeyConstraint(
            ["source_work_item_id"],
            ["work_items.id"],
            name=op.f(f"fk_{table}_source_work_item_id_work_items"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    )
    op.create_index(
        "ix_work_item_downtimes_tenant_item", table, ["tenant_id", "work_item_id", "starts_at"]
    )
    # Per-service and per-CI downtime reports (REQ-CHG-063).
    op.create_index(
        "ix_work_item_downtimes_service_ids", table, ["service_ids"], postgresql_using="gin"
    )
    op.create_index("ix_work_item_downtimes_ci_ids", table, ["ci_ids"], postgresql_using="gin")
    _secure(table)


def upgrade() -> None:
    """The five tables and the downtime kind list."""
    _role_tables()
    _plan_and_schedule_tables()
    _downtime_table()
    now = _codes_now(LIST_CHECK)
    _recheck([*now, *(c for c in ADDED_LISTS if c not in now)])


def downgrade() -> None:
    """Drop them again (stops while downtime kinds exist)."""
    _recheck([c for c in _codes_now(LIST_CHECK) if c not in ADDED_LISTS])
    for table in (
        "work_item_downtimes",
        "work_item_stage_schedules",
        "work_item_plan_sections",
        "work_item_role_holders",
        "work_item_role_defs",
    ):
        op.drop_table(table)
