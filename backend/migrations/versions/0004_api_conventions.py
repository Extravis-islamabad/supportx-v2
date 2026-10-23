"""Idempotency keys, SupportX-owned user preferences, keyset indexes for the user list (WP-008).

Revision ID: 0004
Revises: 0003
Created: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("route", sa.String(length=300), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_idempotency_keys_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "key", name=op.f("pk_idempotency_keys")),
    )
    enable_tenant_rls("idempotency_keys")
    grant_app("idempotency_keys", ("SELECT", "INSERT", "UPDATE", "DELETE"))

    op.add_column("users", sa.Column("signature", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("time_zone", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_signature_length"), "users", "char_length(signature) <= 2000"
    )
    op.create_index("ix_users_tenant_created", "users", ["tenant_id", "created_at", "id"])
    op.create_index("ix_users_tenant_display_name", "users", ["tenant_id", "display_name", "id"])
    op.create_index("ix_users_tenant_last_login", "users", ["tenant_id", "last_login_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_users_tenant_last_login", table_name="users")
    op.drop_index("ix_users_tenant_display_name", table_name="users")
    op.drop_index("ix_users_tenant_created", table_name="users")
    op.drop_constraint(op.f("ck_users_signature_length"), "users", type_="check")
    op.drop_column("users", "time_zone")
    op.drop_column("users", "signature")
    op.drop_table("idempotency_keys")
