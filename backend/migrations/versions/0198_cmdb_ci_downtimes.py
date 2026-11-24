"""cmdb_ci_downtimes: each CI's downtimes (WP-053 S5b, REQ-CMDB-020; the coordinator's 0198).

- One row per (downtime, CI). A synced row (source change, release or incident) is keyed by
  the work_items downtime it mirrors (`source_downtime_id`, unique per CI while live) and kept
  in step by `work_items.downtime.changed`; `source_version` drops a replayed or out-of-order
  event. A `manual` row is recorded on the CI by hand and names no source downtime.
- `state` (scheduled, active, completed) is moved by the one-minute sweep as time passes; its
  partial index holds only the rows still to move.
- Tenant first, RLS forced (migrations/helpers.py only), soft delete, actor audit. No foreign
  key to work_items' tables (the modules stay apart, §6.1); the CI's is tenant-scoped.

The downgrade refuses while any tenant has a downtime (rule 5h), per tenant with app.tenant_id
set.

Revision ID: 0198
Revises: 0195 (main's head now; re-pointed at its queue turn)
Created: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0198"
down_revision: str | None = "0195"  # main's head now; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "cmdb_ci_downtimes"


def upgrade() -> None:
    """The downtimes table."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ci_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_work_item_id", sa.Uuid(), nullable=True),
        sa.Column("source_downtime_id", sa.Uuid(), nullable=True),
        sa.Column("source_version", sa.BigInteger(), nullable=True),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="scheduled", nullable=False),
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
        sa.CheckConstraint(
            "source IN ('change', 'release', 'incident', 'manual')",
            name=op.f(f"ck_{TABLE}_source_code"),
        ),
        sa.CheckConstraint(
            "state IN ('scheduled', 'active', 'completed')", name=op.f(f"ck_{TABLE}_state_code")
        ),
        sa.CheckConstraint("phase IN ('planned', 'actual')", name=op.f(f"ck_{TABLE}_phase_code")),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at", name=op.f(f"ck_{TABLE}_ends_after_start")
        ),
        sa.CheckConstraint(
            "(source = 'manual') = (source_downtime_id IS NULL)",
            name=op.f(f"ck_{TABLE}_source_ref"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_ci_downtimes_ci",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_cmdb_ci_downtimes_source",
        TABLE,
        ["tenant_id", "source_downtime_id", "ci_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND source_downtime_id IS NOT NULL"),
    )
    op.create_index("ix_cmdb_ci_downtimes_tenant_ci", TABLE, ["tenant_id", "ci_id", "starts_at"])
    op.create_index(
        "ix_cmdb_ci_downtimes_tenant_sweep",
        TABLE,
        ["tenant_id", "state", "starts_at"],
        postgresql_where=sa.text("deleted_at IS NULL AND state <> 'completed'"),
    )
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))  # soft delete only
    enable_actor_audit(TABLE)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE); a fixed statement.
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM cmdb_ci_downtimes) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has CI downtimes (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the table only while no tenant has a downtime."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(TABLE)  # its indexes and policies go with it
