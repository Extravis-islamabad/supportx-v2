"""Workflow jobs: bulk retry, cancel and migration of instances (WP-048b S3; REQ-WF-021, -025).

One row per job: the admin's choice of instances (at most 1,000, ADR-043 §9), what to do with
them, and its progress, run by the worker in batches with the progress streamed. A migration's
node mapping and target version ride in `options`.

Expand only: a new table. The downgrade refuses while any tenant has a job (rule 5h); the table
forces RLS, so the check runs per tenant with app.tenant_id set.

Revision ID: 0107
Revises: 0106
Created: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0107"
down_revision: str | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOBS = "workflow_jobs"


def upgrade() -> None:
    """The jobs table, its checks and indexes, RLS and the app's grants."""
    op.create_table(
        JOBS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("instance_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column(
            "options", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("done_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "results", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "kind IN ('retry', 'cancel', 'migrate')", name=op.f("ck_workflow_jobs_kind_code")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name=op.f("ck_workflow_jobs_status_code"),
        ),
        sa.CheckConstraint(
            "cardinality(instance_ids) BETWEEN 1 AND 1000",
            name=op.f("ck_workflow_jobs_instance_limit"),
        ),
        sa.CheckConstraint(
            "processed BETWEEN 0 AND total", name=op.f("ck_workflow_jobs_processed_range")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_workflow_jobs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_id"],
            ["workflows.tenant_id", "workflows.id"],
            name="fk_workflow_jobs_workflow",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_jobs")),
    )
    op.create_index(
        "ix_workflow_jobs_tenant_workflow_created",
        JOBS,
        ["tenant_id", "workflow_id", "created_at"],
    )
    op.create_index(
        "ix_workflow_jobs_tenant_pending",
        JOBS,
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    enable_tenant_rls(JOBS)
    enable_actor_audit(JOBS)
    grant_app(JOBS, ("SELECT", "INSERT", "UPDATE"))


_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM workflow_jobs) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has workflow jobs', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drop the jobs table, refused while any tenant has a job (rule 5h)."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(JOBS)
