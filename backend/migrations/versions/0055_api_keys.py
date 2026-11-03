"""API keys (WP-041, REQ-INT-019, 021; D-128).

Expand only:
- `api_keys` (RLS, FORCE): a key's owner (a person or a service identity), name, scopes, the
  HMAC-SHA-256 of its secret (under a server key kept outside the database), its last four
  characters, expiry, IP allowlist, last use and revocation. The application role may read,
  insert and update; never delete (a revoked key stays, for the audit trail).
- `identity_settings.people_may_create_keys` and `allow_non_expiring_keys`, both off.

No data step. The downgrade drops what this adds (keys made since stop working, as they would
without the table).

Revision ID: 0055
Revises: 0054 (re-pointed onto the head of main when queued)
Created: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(80)), nullable=False),
        sa.Column("secret_hash", sa.LargeBinary(), nullable=False),
        sa.Column("last_four", sa.String(4), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ip_allowlist", postgresql.ARRAY(sa.String(50)), server_default="{}", nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(50), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100", name=op.f("ck_api_keys_name_length")
        ),
        sa.CheckConstraint(
            "cardinality(scopes) BETWEEN 1 AND 200", name=op.f("ck_api_keys_scopes_count")
        ),
        sa.CheckConstraint(
            "cardinality(ip_allowlist) <= 20", name=op.f("ck_api_keys_allowlist_count")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_api_keys_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_api_keys_owner"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
    )
    op.create_index("ix_api_keys_tenant_owner", "api_keys", ["tenant_id", "owner_id", "created_at"])
    enable_tenant_rls("api_keys")
    enable_actor_audit("api_keys")
    grant_app("api_keys", ("SELECT", "INSERT", "UPDATE"))

    for column in ("people_may_create_keys", "allow_non_expiring_keys"):
        op.add_column(
            "identity_settings",
            sa.Column(column, sa.Boolean(), server_default="false", nullable=False),
        )


def downgrade() -> None:
    for column in ("allow_non_expiring_keys", "people_may_create_keys"):
        op.drop_column("identity_settings", column)
    op.drop_table("api_keys")
