"""Users (identity_access) and the actor-audit trigger function.

Revision ID: 0002
Revises: 0001
Created: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.shared.db.rls import ACTOR_AUDIT_FUNCTION
from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(ACTOR_AUDIT_FUNCTION)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("external_subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("locale", sa.String(), server_default="en", nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("user_type", sa.String(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("locale IN ('en', 'ar', 'ur')", name=op.f("ck_users_locale_code")),
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_users_status_code")),
        sa.CheckConstraint(
            "user_type IN ('technician', 'requester')", name=op.f("ck_users_user_type_code")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_users_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("tenant_id", "email", name=op.f("uq_users_tenant_id_email")),
        sa.UniqueConstraint(
            "tenant_id", "external_subject", name=op.f("uq_users_tenant_id_external_subject")
        ),
    )
    enable_tenant_rls("users")
    enable_actor_audit("users")
    # Users are disabled, never deleted by the app (soft delete / GDPR erasure jobs only).
    grant_app("users", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_table("users")
    op.execute("DROP FUNCTION supportx_stamp_actor()")
