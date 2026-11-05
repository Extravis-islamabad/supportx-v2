"""Visual workflows: definitions, versions, instances and their steps (WP-048b S1; ADR-043).

Automation module tables, number from the coordinator. Expand only, no data step. Every table
forces RLS; every key carries tenant_id first.

- `workflows`: one per name and record type; the draft definition (saved with its problems),
  enabled, the owner, the run-as service identity (ADR-043 §6) and the published version.
- `workflow_versions`: published definitions, immutable, with who published them and when
  (REQ-WF-021, -027).
- `workflow_instances`: one run on one record; PostgreSQL holds its state (tokens, variables,
  failure) and the next wake time, Temporal only wakes it (ADR-043 §3, §5). At most one live
  instance per record and workflow (REQ-WF-010), by a partial unique index. Records are named by
  type and ID, never by a foreign key into another module's table (rule e), so assets join later
  (REQ-WF-031).
- `workflow_steps`: the log of node runs (REQ-WF-023). `(tenant_id, instance_id, seq)` is unique:
  a re-run activity finds its step written and applies nothing (ADR-043 §5).

The downgrade drops the four tables.

Revision ID: 0105
Revises: 0098
Created: 2026-11-05
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0105"
down_revision: str | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORD_TYPES = "record_type IN ('incident', 'service_request', 'problem', 'change', 'release')"
STATUSES = "status IN ('running', 'waiting', 'failed', 'finished', 'cancelled')"
LIVE = "status IN ('running', 'waiting', 'failed')"
DML = ("SELECT", "INSERT", "UPDATE")


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
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


def _object(table: str, column: str, *, nullable: bool = False) -> sa.CheckConstraint:
    rule = f"jsonb_typeof({column}) = 'object'"
    return sa.CheckConstraint(
        f"{column} IS NULL OR {rule}" if nullable else rule,
        name=op.f(f"ck_{table}_{column}_object"),
    )


def _secure(table: str, grants: Sequence[str] = DML, *, actors: bool = True) -> None:
    enable_tenant_rls(table)
    if actors:
        enable_actor_audit(table)
    grant_app(table, tuple(grants))


def _workflows() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("draft", postgresql.JSONB(), nullable=False),
        sa.Column("draft_problems", sa.Integer(), server_default="0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("service_identity_id", sa.Uuid(), nullable=True),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        *_stamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(RECORD_TYPES, name=op.f("ck_workflows_record_type_code")),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_workflows_name_length")
        ),
        sa.CheckConstraint("draft_problems >= 0", name=op.f("ck_workflows_draft_problems")),
        _object("workflows", "draft"),
        _tenant_fk("workflows"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_workflows_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "service_identity_id"],
            ["users.tenant_id", "users.id"],
            name="fk_workflows_service_identity",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_workflows_tenant_id_id"),
    )
    op.create_index(
        "uq_workflows_tenant_type_name",
        "workflows",
        ["tenant_id", "record_type", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    _secure("workflows")

    op.create_table(
        "workflow_versions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("number >= 1", name=op.f("ck_workflow_versions_number")),
        _object("workflow_versions", "definition"),
        _tenant_fk("workflow_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["workflows.tenant_id", "workflows.id"],
            name="fk_workflow_versions_workflow",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "workflow_id", "number", name=op.f("pk_workflow_versions")
        ),
    )
    # Published versions are never changed: the app role may add them, never update them.
    _secure("workflow_versions", ("SELECT", "INSERT"), actors=False)


def _instances() -> None:
    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("record_type", sa.String(20), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("failure", postgresql.JSONB(), nullable=True),
        sa.Column("wake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_how", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        *_stamps(),
        sa.CheckConstraint(RECORD_TYPES, name=op.f("ck_workflow_instances_record_type_code")),
        sa.CheckConstraint(STATUSES, name=op.f("ck_workflow_instances_status_code")),
        sa.CheckConstraint(
            "started_how IN ('template', 'trigger', 'manual', 'sub_flow')",
            name=op.f("ck_workflow_instances_started_how_code"),
        ),
        _object("workflow_instances", "state"),
        _object("workflow_instances", "failure", nullable=True),
        _tenant_fk("workflow_instances"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id", "version_number"],
            [
                "workflow_versions.tenant_id",
                "workflow_versions.workflow_id",
                "workflow_versions.number",
            ],
            name="fk_workflow_instances_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_instances")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_workflow_instances_tenant_id_id"),
    )
    # REQ-WF-010: a record runs at most one live instance of the same workflow.
    op.create_index(
        "uq_workflow_instances_live",
        "workflow_instances",
        ["tenant_id", "workflow_id", "record_id"],
        unique=True,
        postgresql_where=sa.text(LIVE),
    )
    op.create_index(
        "ix_workflow_instances_tenant_record",
        "workflow_instances",
        ["tenant_id", "record_type", "record_id"],
    )
    op.create_index(
        "ix_workflow_instances_tenant_status",
        "workflow_instances",
        ["tenant_id", "status", "workflow_id"],
    )
    # The safety net's sweep: instances due to wake (ADR-043 §5).
    op.create_index(
        "ix_workflow_instances_tenant_wake",
        "workflow_instances",
        ["tenant_id", "wake_at"],
        postgresql_where=sa.text("wake_at IS NOT NULL"),
    )
    _secure("workflow_instances")

    op.create_table(
        "workflow_steps",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(20), nullable=False),
        sa.Column("node", sa.String(40), nullable=False),
        sa.Column("node_type", sa.String(20), nullable=False),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_workflow_steps_seq")),
        _object("workflow_steps", "detail", nullable=True),
        _tenant_fk("workflow_steps"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "instance_id"],
            ["workflow_instances.tenant_id", "workflow_instances.id"],
            name="fk_workflow_steps_instance",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "instance_id", "seq", name=op.f("pk_workflow_steps")),
    )
    # The log is append-only: the app role adds steps, never edits them (REQ-WF-026 keeps it).
    _secure("workflow_steps", ("SELECT", "INSERT"), actors=False)


def upgrade() -> None:
    """The four workflow tables."""
    _workflows()
    _instances()


def downgrade() -> None:
    """Drop them again."""
    for table in ("workflow_steps", "workflow_instances", "workflow_versions", "workflows"):
        op.drop_table(table)
