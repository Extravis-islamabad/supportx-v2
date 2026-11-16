"""Service accounts with an owner, and the tenant's API key policy (WP-057 S4a), 0174.

REQ-SEC-036, service accounts:
- `users.service_owner_id` is the person answerable for a service account. When that person is
  deactivated, the account is flagged for hand-over (REQ-ADM-011).
- `users.service_description` says what the account is for.
- Both are only for service identities (a check). The owner is a user of the same tenant (a
  composite FK), indexed per tenant.

REQ-SEC-037, the key policy on `identity_settings`:
- `key_max_lifetime_days`: 1 to 366, default 366, today's limit, so nothing changes until an
  admin sets it.
- `keys_require_ip_range`: off by default.
- `key_unused_days`: 7 to 365, default 90. A key unused that long is listed to admins.

The policy applies to new and renewed keys. Keys that break it are flagged and listed, never
revoked (the coordinator, 2026-11-16), so no data step.

The downgrade drops the columns. It refuses per tenant while a service account names an owner,
since that link would be lost silently.

Revision ID: 0174
Revises: 0171 (main's head while building; re-pointed at its queue turn)
Created: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0174"
down_revision: str | None = "0171"  # main's head while building; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The owner and description, and the three key policy settings."""
    op.add_column("users", sa.Column("service_owner_id", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("service_description", sa.String(500), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_service_owner"),
        "users",
        "users",
        ["tenant_id", "service_owner_id"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_users_service_fields"),
        "users",
        "user_type = 'service' OR (service_owner_id IS NULL AND service_description IS NULL)",
    )
    op.create_index(
        op.f("ix_users_tenant_service_owner"),
        "users",
        ["tenant_id", "service_owner_id"],
        postgresql_where=sa.text("service_owner_id IS NOT NULL"),
    )
    op.add_column(
        "identity_settings",
        sa.Column("key_max_lifetime_days", sa.Integer(), server_default="366", nullable=False),
    )
    op.add_column(
        "identity_settings",
        sa.Column("keys_require_ip_range", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "identity_settings",
        sa.Column("key_unused_days", sa.Integer(), server_default="90", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_identity_settings_key_max_lifetime_days"),
        "identity_settings",
        "key_max_lifetime_days BETWEEN 1 AND 366",
    )
    op.create_check_constraint(
        op.f("ck_identity_settings_key_unused_days"),
        "identity_settings",
        "key_unused_days BETWEEN 7 AND 365",
    )


def downgrade() -> None:
    """Refuse while a service account names an owner (in any tenant); else drop the columns."""
    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT audit_tenant_ids()")).scalars().all()
    for tenant in tenants:
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        owned = conn.execute(
            sa.text("SELECT count(*) FROM users WHERE service_owner_id IS NOT NULL")
        ).scalar_one()
        if owned:
            msg = (
                f"0174 downgrade refused: tenant {tenant} has {owned} service accounts with an"
                " owner; that link would be lost"
            )
            raise RuntimeError(msg)
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_constraint(
        op.f("ck_identity_settings_key_unused_days"), "identity_settings", type_="check"
    )
    op.drop_constraint(
        op.f("ck_identity_settings_key_max_lifetime_days"), "identity_settings", type_="check"
    )
    op.drop_column("identity_settings", "key_unused_days")
    op.drop_column("identity_settings", "keys_require_ip_range")
    op.drop_column("identity_settings", "key_max_lifetime_days")
    op.drop_index(op.f("ix_users_tenant_service_owner"), table_name="users")
    op.drop_constraint(op.f("ck_users_service_fields"), "users", type_="check")
    op.drop_constraint(op.f("fk_users_service_owner"), "users", type_="foreignkey")
    op.drop_column("users", "service_description")
    op.drop_column("users", "service_owner_id")
