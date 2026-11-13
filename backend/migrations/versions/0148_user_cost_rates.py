"""A person's cost per hour, by date (identity_access; REQ-INC-068 for WP-046a S3).

Expand only, no data step:
- `user_cost_rates`: one rate per person and start date, in the tenant's base currency as it was
  when the rate was set. The rate in force at a moment is the latest live one starting at or
  before it. Worklog costs (lane A) snapshot it through identity_access's `cost_rate` port.

Tenant-scoped with RLS forced, actor audit, and no DELETE grant (removal is a soft delete). The
downgrade refuses while any tenant has a rate, per tenant with app.tenant_id set (rule 5h).

Revision ID: 0148
Revises: 0146
Created: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0148"
# Re-pointed onto main's head at the lane's queue turn (the coordinator's order).
down_revision: str | None = "0146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "user_cost_rates"


def upgrade() -> None:
    """Adds the cost rate table."""
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("rate >= 0", name=op.f(f"ck_{TABLE}_rate_not_negative")),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f(f"ck_{TABLE}_currency_code")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_user_cost_rates_user",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_user_cost_rates_start",
        TABLE,
        ["tenant_id", "user_id", "effective_from"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_user_cost_rates_in_force",
        TABLE,
        ["tenant_id", "user_id", sa.text("effective_from DESC")],
    )
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))  # removal is a soft delete
    enable_actor_audit(TABLE)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has cost rates (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def downgrade() -> None:
    """Drops the cost rate table only while no tenant has a rate; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(TABLE)
