"""Vendor support access with consent (WP-057 S4c-1, REQ-SEC-045, D-173), 0179.

A tenant admin grants one named Extravis engineer temporary access. The grant makes a temporary
account in the tenant's own realm, deleted when the grant ends (one mechanism everywhere, rule f).
This adds:

- `support_grants` (tenant-first, RLS): who (the engineer's name and e-mail), why (the reason,
  an optional ticket), what (view, or view and change with its own reason; personal fields
  unmasked or not), from where (an optional IP list), when (starts and ends, never past 72 hours
  in total: `max_end_at`), how the engineer was verified (their e-mail link, or an admin's
  out-of-band confirmation when air-gapped), its state, and the temporary account.
  Held in the database, not only the service:
  - 72 hours at most;
  - "view and change" needs its reason;
  - an out-of-band confirmation names the confirming admin;
  - one open grant per engineer.
- the `vendor_support` user type (the temporary account: no seat, never in people lists).
- `identity_settings.never_allow_vendor_support` (D-173 (9)): while on, no grant can be made.

The app role may insert and update grants, never delete them: the grant and its audit outlive
the account. Expand only.

Revision ID: 0179
Revises: 0173 (main's head while building; re-pointed at its queue turn: 0177, 0175, 0176 first)
Created: 2026-11-18
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0179"
down_revision: str | None = "0173"  # main's head while building; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS = "support_grants"
TYPE_CHECK = "ck_users_user_type_code"
ACCESS = ("view", "view_and_change")
STATES = ("pending_verification", "active", "ended", "revoked")
OPEN_STATES = ("pending_verification", "active")
VERIFICATION = ("email", "out_of_band")
MAX_HOURS = 72


def _codes(column: str, codes: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _audit_columns() -> list[sa.Column[Any]]:
    return [
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
    ]


def upgrade() -> None:
    """The grants table, the vendor_support user type and the opt-out setting."""
    op.drop_constraint(op.f(TYPE_CHECK), "users", type_="check")
    op.create_check_constraint(
        op.f(TYPE_CHECK),
        "users",
        "user_type IN ('technician', 'requester', 'service', 'vendor_support')",
    )
    op.add_column(
        "identity_settings",
        sa.Column(
            "never_allow_vendor_support", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.create_table(
        GRANTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("engineer_name", sa.String(length=200), nullable=False),
        sa.Column("engineer_email", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("ticket_ref", sa.String(length=100), nullable=True),
        sa.Column("access", sa.String(length=20), server_default="view", nullable=False),
        sa.Column("change_reason", sa.String(length=500), nullable=True),
        sa.Column("unmask_personal", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "ip_allowlist",
            postgresql.ARRAY(postgresql.CIDR()),
            server_default=sa.text("'{}'::cidr[]"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state", sa.String(length=30), server_default="pending_verification", nullable=False
        ),
        sa.Column("verification", sa.String(length=20), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmation_note", sa.String(length=500), nullable=True),
        sa.Column("support_user_id", sa.Uuid(), nullable=True),
        sa.Column("first_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by", sa.Uuid(), nullable=True),
        # Set only once Keycloak confirms the account is gone (deleted, or 404): until then the
        # grant has ended (the database refuses the account) but its removal is retried (lane B).
        sa.Column("account_removed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{GRANTS}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{GRANTS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "support_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f(f"fk_{GRANTS}_support_user"),
        ),
        sa.CheckConstraint(_codes("access", ACCESS), name=op.f(f"ck_{GRANTS}_access_code")),
        sa.CheckConstraint(_codes("state", STATES), name=op.f(f"ck_{GRANTS}_state_code")),
        sa.CheckConstraint(
            _codes("verification", VERIFICATION), name=op.f(f"ck_{GRANTS}_verification_code")
        ),
        # D-173 (3): 72 hours at most in total, extensions included.
        sa.CheckConstraint(
            f"ends_at > starts_at AND ends_at <= starts_at + interval '{MAX_HOURS} hours'",
            name=op.f(f"ck_{GRANTS}_window"),
        ),
        # D-173 (6): "view and change" is ticked deliberately, with a reason.
        sa.CheckConstraint(
            "access = 'view' OR change_reason IS NOT NULL",
            name=op.f(f"ck_{GRANTS}_change_reason"),
        ),
        # D-173 (5): without the e-mail link, the confirming admin is recorded.
        sa.CheckConstraint(
            "verification = 'email' OR confirmed_by IS NOT NULL",
            name=op.f(f"ck_{GRANTS}_confirmed_by"),
        ),
    )
    # Lane B (6): one open grant per engineer.
    op.create_index(
        op.f(f"ix_{GRANTS}_tenant_engineer_open"),
        GRANTS,
        ["tenant_id", sa.text("lower(engineer_email)")],
        unique=True,
        postgresql_where=sa.text(_codes("state", OPEN_STATES)),
    )
    op.create_index(
        op.f(f"ix_{GRANTS}_tenant_state_ends"), GRANTS, ["tenant_id", "state", "ends_at"]
    )
    enable_tenant_rls(GRANTS)
    grant_app(
        GRANTS, ("SELECT", "INSERT", "UPDATE")
    )  # never deleted: the record outlives the account
    enable_actor_audit(GRANTS)


def downgrade() -> None:
    """Refuse while any tenant has a grant or a support account; else drop it all."""
    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT audit_tenant_ids()")).scalars().all()
    for tenant in tenants:
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        grants = conn.execute(sa.text(f"SELECT count(*) FROM {GRANTS}")).scalar_one()  # noqa: S608 - fixed name
        accounts = conn.execute(
            sa.text("SELECT count(*) FROM users WHERE user_type = 'vendor_support'")
        ).scalar_one()
        if grants or accounts:
            msg = (
                f"0179 downgrade refused: tenant {tenant} has {grants} support grants and"
                f" {accounts} support accounts; their record would be lost"
            )
            raise RuntimeError(msg)
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_table(GRANTS)
    op.drop_column("identity_settings", "never_allow_vendor_support")
    op.drop_constraint(op.f(TYPE_CHECK), "users", type_="check")
    op.create_check_constraint(
        op.f(TYPE_CHECK), "users", "user_type IN ('technician', 'requester', 'service')"
    )
