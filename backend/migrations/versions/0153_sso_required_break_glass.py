"""Single sign-on required, break-glass admins, MFA with SSO (identity_access; WP-057 S1b).

Expand only, no data step (REQ-SEC-009, REQ-SEC-026):
- `identity_settings.sso_required`: off | technicians | everyone. Off by default: nothing
  changes for any tenant until an admin turns it on (and that is refused without a break-glass
  admin, the coordinator's rule).
- `identity_settings.sso_also_require_mfa`: SupportX's own MFA after a single sign-on too. Off by
  default: the identity provider's MFA is trusted (AC1).
- `users.break_glass`: a named admin who keeps a local password with MFA, so the tenant is never
  locked out if its identity provider fails. `users.break_glass_ip_exempt`: also outside the IP
  allow-lists (its own audited setting, lane B's condition 5). Both off by default; only a tenant
  admin sets them (the service), every change audited.
- `sign_in_import_cursor.last_offset`: how many events of `last_time_ms` the Keycloak import
  already read when one millisecond held more than a run takes (lane B: page inside it, never
  skip it, so a burst of failed sign-ins is never dropped). 0 by default.

The downgrade refuses while any tenant uses any of them, per tenant with app.tenant_id set
(rule 5h).

Revision ID: 0153
Revises: 0151
Created: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0153"
# Re-pointed onto main's head at the queue turn (after 0151 and lane A's 0152).
down_revision: str | None = "0151"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTINGS = "identity_settings"
USERS = "users"
CURSOR = "sign_in_import_cursor"
SSO_REQUIRED = ("off", "technicians", "everyone")


def upgrade() -> None:
    """Adds the four columns, off by default."""
    op.add_column(
        SETTINGS,
        sa.Column("sso_required", sa.String(12), server_default="off", nullable=False),
    )
    op.create_check_constraint(
        op.f(f"ck_{SETTINGS}_sso_required_code"),
        SETTINGS,
        "sso_required IN (" + ", ".join(repr(c) for c in SSO_REQUIRED) + ")",
    )
    op.add_column(
        SETTINGS,
        sa.Column("sso_also_require_mfa", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        USERS, sa.Column("break_glass", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(
        USERS,
        sa.Column("break_glass_ip_exempt", sa.Boolean(), server_default="false", nullable=False),
    )
    # An exemption only for a break-glass admin: never on its own.
    op.create_check_constraint(
        op.f(f"ck_{USERS}_break_glass_ip_exempt_needs_break_glass"),
        USERS,
        "break_glass OR NOT break_glass_ip_exempt",
    )
    op.add_column(
        CURSOR, sa.Column("last_offset", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_check_constraint(
        op.f(f"ck_{CURSOR}_last_offset_not_negative"), CURSOR, "last_offset >= 0"
    )


_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM {SETTINGS} WHERE sso_required <> 'off' OR sso_also_require_mfa
        ) OR EXISTS (SELECT 1 FROM {USERS} WHERE break_glass OR break_glass_ip_exempt) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses SSO-required or break-glass', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops the columns only while no tenant uses them; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    # Only where the import was inside one millisecond; it re-reads it (rows are unique).
    op.drop_constraint(op.f(f"ck_{CURSOR}_last_offset_not_negative"), CURSOR, type_="check")
    op.drop_column(CURSOR, "last_offset")
    op.drop_constraint(
        op.f(f"ck_{USERS}_break_glass_ip_exempt_needs_break_glass"), USERS, type_="check"
    )
    op.drop_column(USERS, "break_glass_ip_exempt")
    op.drop_column(USERS, "break_glass")
    op.drop_column(SETTINGS, "sso_also_require_mfa")
    op.drop_constraint(op.f(f"ck_{SETTINGS}_sso_required_code"), SETTINGS, type_="check")
    op.drop_column(SETTINGS, "sso_required")
