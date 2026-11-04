"""The work-item stage engine (WP-058a; ADR-041; REQ-WI-026, REQ-REL-014..017).

Expand only, for staged types (releases now, changes later). Incidents and service requests are
untouched: their rows keep NULL in every new column.

- `work_item_stages` (RLS): a type's ordered stages.
- `work_item_statuses` + `stage` (the stage that owns it), `completing` (exactly one per stage;
  reaching it moves on to the next stage) and `set_by` (`person` or `system`: approval outcomes).
- `work_item_stage_paths` (RLS) and `work_item_path_stages` (RLS): the stages a record takes, in
  order, some optional, with a nullable life cycle version (REQ-CHG-030).
- `work_item_status_transitions` (RLS): every listed move, from status to status, optionally per
  path and version, with a reason mode, an extra permission and the fields it asks for.
- `work_items` + `stage`, `stage_path`, `lifecycle_version`.
- `work_item_stage_entries` (RLS): each time a record enters a stage; never rewritten except for
  when it left.

All composite foreign keys carry tenant_id. Seeds are made per tenant on first use, from the
type's declaration (no data step here). The downgrade drops it all.

Revision ID: 0090
Revises: 0069
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0090"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = "type IN ('incident', 'service_request', 'problem', 'change', 'release')"
CODE = "^[a-z][a-z0-9_]{1,39}$"


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "work_item_stages",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        sa.Column("system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(TYPES, name=op.f("ck_work_item_stages_type_code")),
        sa.CheckConstraint(f"code ~ '{CODE}'", name=op.f("ck_work_item_stages_code_format")),
        _tenant_fk("work_item_stages"),
        sa.PrimaryKeyConstraint("tenant_id", "type", "code", name=op.f("pk_work_item_stages")),
    )
    enable_tenant_rls("work_item_stages")
    grant_app("work_item_stages", ("SELECT", "INSERT", "UPDATE"))

    op.add_column("work_item_statuses", sa.Column("stage", sa.String(40), nullable=True))
    op.add_column(
        "work_item_statuses",
        sa.Column("completing", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "work_item_statuses",
        sa.Column("set_by", sa.String(10), server_default="person", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_work_item_statuses_set_by_code"),
        "work_item_statuses",
        "set_by IN ('person', 'system')",
    )
    op.create_foreign_key(
        op.f("fk_work_item_statuses_stage"),
        "work_item_statuses",
        "work_item_stages",
        ["tenant_id", "type", "stage"],
        ["tenant_id", "type", "code"],
    )
    # At most one completing status per stage (the service also refuses none).
    op.create_index(
        "uq_work_item_statuses_one_completing",
        "work_item_statuses",
        ["tenant_id", "type", "stage"],
        unique=True,
        postgresql_where=sa.text("completing"),
    )

    op.create_table(
        "work_item_stage_paths",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("lifecycle_version", sa.Integer(), nullable=True),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        sa.Column("system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(TYPES, name=op.f("ck_work_item_stage_paths_type_code")),
        sa.CheckConstraint(f"code ~ '{CODE}'", name=op.f("ck_work_item_stage_paths_code_format")),
        _tenant_fk("work_item_stage_paths"),
        sa.PrimaryKeyConstraint("tenant_id", "type", "code", name=op.f("pk_work_item_stage_paths")),
    )
    enable_tenant_rls("work_item_stage_paths")
    grant_app("work_item_stage_paths", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "work_item_path_stages",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("path", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("optional", sa.Boolean(), server_default="false", nullable=False),
        _tenant_fk("work_item_path_stages"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type", "path"],
            [
                "work_item_stage_paths.tenant_id",
                "work_item_stage_paths.type",
                "work_item_stage_paths.code",
            ],
            name=op.f("fk_work_item_path_stages_path"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type", "stage"],
            ["work_item_stages.tenant_id", "work_item_stages.type", "work_item_stages.code"],
            name=op.f("fk_work_item_path_stages_stage"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "type", "path", "stage", name=op.f("pk_work_item_path_stages")
        ),
    )
    enable_tenant_rls("work_item_path_stages")
    grant_app("work_item_path_stages", ("SELECT", "INSERT", "UPDATE", "DELETE"))

    op.create_table(
        "work_item_status_transitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("path", sa.String(40), nullable=True),
        sa.Column("lifecycle_version", sa.Integer(), nullable=True),
        sa.Column("from_status", sa.String(40), nullable=False),
        sa.Column("to_status", sa.String(40), nullable=False),
        sa.Column("reason_mode", sa.String(10), server_default="none", nullable=False),
        sa.Column("reason_list", sa.String(20), nullable=True),
        sa.Column("permission", sa.String(40), nullable=True),
        sa.Column("required_fields", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(TYPES, name=op.f("ck_work_item_status_transitions_type_code")),
        sa.CheckConstraint(
            "reason_mode IN ('none', 'optional', 'required')",
            name=op.f("ck_work_item_status_transitions_reason_mode_code"),
        ),
        _tenant_fk("work_item_status_transitions"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type", "from_status"],
            ["work_item_statuses.tenant_id", "work_item_statuses.type", "work_item_statuses.code"],
            name=op.f("fk_work_item_status_transitions_from"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type", "to_status"],
            ["work_item_statuses.tenant_id", "work_item_statuses.type", "work_item_statuses.code"],
            name=op.f("fk_work_item_status_transitions_to"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type", "path"],
            [
                "work_item_stage_paths.tenant_id",
                "work_item_stage_paths.type",
                "work_item_stage_paths.code",
            ],
            name=op.f("fk_work_item_status_transitions_path"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_status_transitions")),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_work_item_status_transitions_move ON work_item_status_transitions"
        " (tenant_id, type, coalesce(path, ''), coalesce(lifecycle_version, 0),"
        " from_status, to_status)"
    )
    enable_tenant_rls("work_item_status_transitions")
    grant_app("work_item_status_transitions", ("SELECT", "INSERT", "UPDATE", "DELETE"))

    op.add_column("work_items", sa.Column("stage", sa.String(40), nullable=True))
    op.add_column("work_items", sa.Column("stage_path", sa.String(40), nullable=True))
    op.add_column("work_items", sa.Column("lifecycle_version", sa.Integer(), nullable=True))

    op.create_table(
        "work_item_stage_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("path", sa.String(40), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_code", sa.String(40), nullable=True),
        sa.Column("reason_text", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _tenant_fk("work_item_stage_entries"),
        sa.ForeignKeyConstraint(
            ["work_item_id"],
            ["work_items.id"],
            name=op.f("fk_work_item_stage_entries_work_item_id_work_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_stage_entries")),
    )
    op.create_index(
        "ix_work_item_stage_entries_tenant_item",
        "work_item_stage_entries",
        ["tenant_id", "work_item_id", "entered_at"],
    )
    enable_tenant_rls("work_item_stage_entries")
    enable_actor_audit("work_item_stage_entries")
    grant_app("work_item_stage_entries", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_table("work_item_stage_entries")
    op.drop_column("work_items", "lifecycle_version")
    op.drop_column("work_items", "stage_path")
    op.drop_column("work_items", "stage")
    op.drop_table("work_item_status_transitions")
    op.drop_table("work_item_path_stages")
    op.drop_table("work_item_stage_paths")
    op.drop_index("uq_work_item_statuses_one_completing", table_name="work_item_statuses")
    op.drop_constraint(op.f("fk_work_item_statuses_stage"), "work_item_statuses")
    op.drop_constraint(op.f("ck_work_item_statuses_set_by_code"), "work_item_statuses")
    op.drop_column("work_item_statuses", "set_by")
    op.drop_column("work_item_statuses", "completing")
    op.drop_column("work_item_statuses", "stage")
    op.drop_table("work_item_stages")
