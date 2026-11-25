"""CMDB: CI baselines (WP-053 S7b; REQ-CMDB-033).

- `cmdb_ci_baselines`: a CI's attributes saved under a name, its own copy of the CI as it was
  (the shape of a version's snapshot: fields, custom values, relationships) and the CI version it
  was taken at. Kept until deleted (D-172 (6)); soft delete. The app may select, insert and
  update (soft delete and erasure's redaction only), never delete.

Expand only. The downgrade drops the table only while no tenant has a baseline (rule 5h).

Revision ID: 0209
Revises: 0204 (main's head when built; re-pointed to main's head at its queue turn)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0209"
down_revision: str | None = "0204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "cmdb_ci_baselines"
CIS = "cmdb_cis"


def upgrade() -> None:
    """The table, its RLS and the app's rights."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ci_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("from_version", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
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
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f(f"ck_{TABLE}_name_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ci_id"],
            [f"{CIS}.tenant_id", f"{CIS}.id"],
            name="fk_cmdb_ci_baselines_ci",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "ix_cmdb_ci_baselines_tenant_ci", TABLE, ["tenant_id", "ci_id", "created_at", "id"]
    )
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))  # soft delete and redaction only
    enable_actor_audit(TABLE)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has CI baselines (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def downgrade() -> None:
    """Drops the table only while no tenant has a baseline."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(TABLE)  # its index and policies go with it
