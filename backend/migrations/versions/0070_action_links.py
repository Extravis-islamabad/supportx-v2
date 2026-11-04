"""Signed one-time action links (WP-030 s3; REQ-NTF-024, REQ-SR-026; lane B's conditions).

One row per link: only the SHA-256 of its token (32 bytes), the recipient, the action, the
object and the object's version, the expiry, and when it was used or revoked. Tenant scoped
with RLS (FORCE) and actor audit; soft delete only (no DELETE grant). Expand only, no data step;
`mail_messages.links` and `notification_deliveries.links` keep the links to make at send
(D-132: never a token in a stored body). The downgrade drops the table and the columns (every
link simply stops working).

Revision ID: 0070
Revises: 0065
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0070"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "action_links"


def upgrade() -> None:
    """Create the table with RLS."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("object_type", sa.String(length=40), nullable=False),
        sa.Column("object_id", sa.UUID(), nullable=False),
        sa.Column("object_version", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_uses", sa.Integer(), server_default="0", nullable=False),
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
            "octet_length(token_digest) = 32", name=op.f(f"ck_{TABLE}_digest_length")
        ),
        sa.CheckConstraint("object_version >= 1", name=op.f(f"ck_{TABLE}_version_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_action_links_tenant_digest", TABLE, ["tenant_id", "token_digest"], unique=True
    )
    op.create_index(
        "ix_action_links_tenant_object", TABLE, ["tenant_id", "object_type", "object_id"]
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))
    # D-132: a queued message or a waiting delivery keeps the links to make at send, never a
    # token (its bodies hold markers where the links go).
    for table in ("mail_messages", "notification_deliveries"):
        op.add_column(table, sa.Column("links", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Drop the table and the columns."""
    for table in ("notification_deliveries", "mail_messages"):
        op.drop_column(table, "links")
    op.drop_table(TABLE)
