"""The tenant's mobile app policy on `identity_settings` (WP-057 S6b, REQ-SEC-047), 0206.

Beside the console and portal session limits, one versioned row (lane B's S6 Q3):
- `mobile_allowed` (on): off refuses the app's sign-in before any session exists (AC1), with
  `mobile_refusal_message`, plain text per language (en, ar, ur keys only; NULL: built-in text).
- `mobile_mfa_required` (off): a mobile sign-in needs a second factor.
- `mobile_device_unlock_required` (off) and `mobile_unlock_after_minutes` (1 to 60, 5): the app
  asks for the device's PIN or biometrics after that long in the background (AC2). Client-
  enforced: the server states the policy, the app applies it.
- `mobile_idle_seconds` and `mobile_absolute_seconds`: NULL (both) follows the web limits of the
  person's app; set, the same bounds as the web's (idle 5 min to a day; absolute from idle to 30
  days).
- `mobile_clear_on_sign_out` (on): the app clears its local data at sign-out (client-enforced).

Defaults change nothing for any tenant, so there is no data step. The downgrade drops the
columns: a tenant that switched the app off would allow it again, so it refuses while any tenant
has `mobile_allowed` off (business tables force RLS: counted per tenant, as 0023 does).

Revision ID: 0206
Revises: 0205 (main's head at its queue turn)
Created: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0206"
down_revision: str | None = "0205"  # main's head at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "identity_settings"
MIN_IDLE, MAX_IDLE, MAX_ABSOLUTE = 300, 86400, 30 * 86400


def upgrade() -> None:
    """The policy's columns and their checks."""
    for name, kind, default in (
        ("mobile_allowed", sa.Boolean(), "true"),
        ("mobile_mfa_required", sa.Boolean(), "false"),
        ("mobile_device_unlock_required", sa.Boolean(), "false"),
        ("mobile_unlock_after_minutes", sa.Integer(), "5"),
        ("mobile_clear_on_sign_out", sa.Boolean(), "true"),
    ):
        op.add_column(TABLE, sa.Column(name, kind, server_default=default, nullable=False))
    op.add_column(TABLE, sa.Column("mobile_refusal_message", postgresql.JSONB(), nullable=True))
    op.add_column(TABLE, sa.Column("mobile_idle_seconds", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("mobile_absolute_seconds", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_identity_settings_mobile_unlock_range"),
        TABLE,
        "mobile_unlock_after_minutes BETWEEN 1 AND 60",
    )
    op.create_check_constraint(
        op.f("ck_identity_settings_mobile_limits"),
        TABLE,
        # Both set in the second branch: BETWEEN on a NULL is NULL, which a check lets through.
        "(mobile_idle_seconds IS NULL AND mobile_absolute_seconds IS NULL) OR ("
        "mobile_idle_seconds IS NOT NULL AND mobile_absolute_seconds IS NOT NULL AND "
        f"mobile_idle_seconds BETWEEN {MIN_IDLE} AND {MAX_IDLE}"
        f" AND mobile_absolute_seconds BETWEEN mobile_idle_seconds AND {MAX_ABSOLUTE})",
    )
    op.create_check_constraint(
        op.f("ck_identity_settings_mobile_message"),
        TABLE,
        "mobile_refusal_message IS NULL OR ("
        "jsonb_typeof(mobile_refusal_message) = 'object'"
        " AND mobile_refusal_message - ARRAY['en', 'ar', 'ur'] = '{}'::jsonb)",
    )


def downgrade() -> None:
    """Drop them; refused while a tenant has switched the app off (it would be allowed again)."""
    bind = op.get_bind()
    tenants = [r[0] for r in bind.execute(sa.text("SELECT id FROM tenants")).fetchall()]
    for tenant in tenants:
        bind.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        off = bind.execute(
            sa.text("SELECT count(*) FROM identity_settings WHERE NOT mobile_allowed")
        ).scalar_one()
        if off:
            bind.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
            msg = (
                f"tenant {tenant} has switched the mobile app off: downgrading past 0206 would "
                "allow it again. Switch it back on first."
            )
            raise RuntimeError(msg)
    bind.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    for name in ("mobile_message", "mobile_limits", "mobile_unlock_range"):
        op.drop_constraint(op.f(f"ck_identity_settings_{name}"), TABLE, type_="check")
    for column in (
        "mobile_absolute_seconds",
        "mobile_idle_seconds",
        "mobile_refusal_message",
        "mobile_clear_on_sign_out",
        "mobile_unlock_after_minutes",
        "mobile_device_unlock_required",
        "mobile_mfa_required",
        "mobile_allowed",
    ):
        op.drop_column(TABLE, column)
