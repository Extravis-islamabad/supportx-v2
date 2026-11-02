"""Service identities: each connector instance acts in its own name (WP-040 session 2).

Expand only (D-113):
- users: the type `service` (REQ-INT-012), and a check that a service identity can never sign
  in (no subject, no address, `can_sign_in` false).
- connector_identities (RLS, FORCE): which service identity each connector instance acts as.
  No data step: an existing connector gets its identity at its next run.

The downgrade removes the table and keeps every user row: service identities become disabled
requesters that cannot sign in, so history still names who made each change; then the old
checks come back.

Revision ID: 0052
Revises: 0049 (0050 and 0051 are lane C's; down_revision is re-pointed when queued)
Created: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0052"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPE_CHECK = "ck_users_user_type_code"
NO_SIGN_IN = "ck_users_service_no_sign_in"

# Per tenant under FORCE RLS (as in 0023): service identities only, nothing deleted.
RETYPE_SERVICE_USERS = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE users SET user_type = 'requester', status = 'disabled', can_sign_in = false
         WHERE tenant_id = t AND user_type = 'service';
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def upgrade() -> None:
    op.drop_constraint(op.f(TYPE_CHECK), "users", type_="check")
    op.create_check_constraint(
        op.f(TYPE_CHECK), "users", "user_type IN ('technician', 'requester', 'service')"
    )
    op.create_check_constraint(
        op.f(NO_SIGN_IN),
        "users",
        "user_type <> 'service' OR (external_subject IS NULL AND email IS NULL"
        " AND NOT can_sign_in)",
    )
    op.create_table(
        "connector_identities",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_connector_identities_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_connector_identities_user",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "kind", "instance_id", name=op.f("pk_connector_identities")
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_connector_identities_tenant_user"),
    )
    enable_tenant_rls("connector_identities")
    grant_app("connector_identities", ("SELECT", "INSERT"))


def downgrade() -> None:
    op.drop_table("connector_identities")
    op.drop_constraint(op.f(NO_SIGN_IN), "users", type_="check")
    op.execute(RETYPE_SERVICE_USERS)
    op.drop_constraint(op.f(TYPE_CHECK), "users", type_="check")
    op.create_check_constraint(
        op.f(TYPE_CHECK), "users", "user_type IN ('technician', 'requester')"
    )
