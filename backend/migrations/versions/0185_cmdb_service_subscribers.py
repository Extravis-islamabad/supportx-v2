"""cmdb_service_subscribers: who a business service serves (WP-053, D-172 (3); the coordinator's 0185).

- One row per (business service CI, kind, ref): `kind` is department, site or group, `ref_id`
  the unit's ID. No foreign key to the three unit tables: a unit removed later stays a row,
  shown as "removed" and counting nobody, so removing a unit never fails on a subscription.
- Impact's affected users are the active people these refs reach, each once (organization's
  audience resolver).
- Tenant first, RLS forced (migrations/helpers.py only), soft delete, actor audit; a live
  (CI, kind, ref) is unique.

The downgrade refuses while any tenant has a subscription (rule 5h), per tenant with
app.tenant_id set.

Revision ID: 0185
Revises: 0182 (main's head at its queue turn: 0186 → 0182 → 0185)
Created: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0185"
down_revision: str | None = "0182"  # main's head at its queue turn (0186 → 0182 → 0185)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "cmdb_service_subscribers"


def upgrade() -> None:
    """The subscriptions table."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ci_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
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
            "kind IN ('department', 'site', 'group')", name=op.f(f"ck_{TABLE}_kind_code")
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
            name="fk_cmdb_service_subscribers_ci",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_cmdb_service_subscribers_live",
        TABLE,
        ["tenant_id", "ci_id", "kind", "ref_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_cmdb_service_subscribers_tenant_ref", TABLE, ["tenant_id", "kind", "ref_id"]
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
        IF EXISTS (SELECT 1 FROM cmdb_service_subscribers) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has service subscribers (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the table only while no tenant has a subscription."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(TABLE)  # its indexes and policies go with it
