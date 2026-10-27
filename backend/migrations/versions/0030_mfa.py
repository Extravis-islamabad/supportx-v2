"""MFA policy (WP-039 session 3; REQ-SEC-022, 024, 025).

- mfa_policies: the MFA mode of a role in a tenant (off, optional, required); no row means the
  Appendix A default (domain/mfa.py);
- identity_settings.mfa_grace_days: how long a person has to enrol once MFA is required (7, 0 to
  30);
- users.mfa_required_since, users.mfa_enrolled_at: when MFA became required for the person and
  when SupportX last saw their authenticator.

Tenant-scoped with RLS. Reversible.

Revision ID: 0030
Revises: 0026
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0030"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mfa_policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('off', 'optional', 'required')", name=op.f("ck_mfa_policies_mode_code")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_mfa_policies_role"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_mfa_policies_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mfa_policies")),
        sa.UniqueConstraint("tenant_id", "role_id", name="uq_mfa_policies_tenant_role"),
    )
    enable_tenant_rls("mfa_policies")
    grant_app("mfa_policies", ("SELECT", "INSERT", "UPDATE", "DELETE"))
    enable_actor_audit("mfa_policies")
    op.add_column(
        "identity_settings",
        sa.Column("mfa_grace_days", sa.BigInteger(), server_default="7", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_identity_settings_mfa_grace_days_range"),
        "identity_settings",
        "mfa_grace_days BETWEEN 0 AND 30",
    )
    op.add_column("users", sa.Column("mfa_required_since", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "mfa_enrolled_at")
    op.drop_column("users", "mfa_required_since")
    op.drop_constraint(op.f("ck_identity_settings_mfa_grace_days_range"), "identity_settings")
    op.drop_column("identity_settings", "mfa_grace_days")
    op.drop_table("mfa_policies")
