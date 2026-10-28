"""Mailboxes and the ledger of fetched mail (WP-024).

Tenant-scoped with RLS. Mailboxes are records (soft delete, audited actors); the ledger is one row
per fetched message, so a message is acted on once even across poller restarts.

Revision ID: 0035
Revises: 0033 (until lane A's 0034, WP-020f, is on main)
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0035"
down_revision: str | None = "0033"  # re-pointed at merge: after WP-020f's 0034
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mailboxes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("protocol", sa.String(length=10), server_default="imap", nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("security", sa.String(length=10), server_default="tls", nullable=False),
        sa.Column("allow_plain", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("username", sa.String(length=320), nullable=False),
        sa.Column("secret_key_id", sa.String(length=32), nullable=True),
        sa.Column("secret_sealed", sa.LargeBinary(), nullable=True),
        sa.Column("folder", sa.String(length=255), server_default="INBOX", nullable=False),
        sa.Column("after_fetch", sa.String(length=10), server_default="mark_read", nullable=False),
        sa.Column("move_to", sa.String(length=255), nullable=True),
        sa.Column("creates", sa.String(length=10), server_default="incident", nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column(
            "unknown_senders",
            sa.String(length=30),
            server_default="create_allowed_domains",
            nullable=False,
        ),
        sa.Column(
            "allowed_domains",
            postgresql.ARRAY(sa.String(length=255)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("state", sa.String(length=12), server_default="not_set_up", nullable=False),
        sa.Column("state_reason", sa.String(length=60), nullable=True),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("protocol IN ('imap')", name=op.f("ck_mailboxes_protocol_code")),
        sa.CheckConstraint(
            "security IN ('tls', 'starttls', 'none')", name=op.f("ck_mailboxes_security_code")
        ),
        sa.CheckConstraint(
            "after_fetch IN ('mark_read', 'move', 'delete')",
            name=op.f("ck_mailboxes_after_fetch_code"),
        ),
        sa.CheckConstraint(
            "creates IN ('incident', 'nothing')", name=op.f("ck_mailboxes_creates_code")
        ),
        sa.CheckConstraint(
            "unknown_senders IN ('create', 'create_allowed_domains', 'reject')",
            name=op.f("ck_mailboxes_unknown_senders_code"),
        ),
        sa.CheckConstraint(
            "state IN ('not_set_up', 'working', 'failing')", name=op.f("ck_mailboxes_state_code")
        ),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name=op.f("ck_mailboxes_port_range")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_mailboxes_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mailboxes")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_mailboxes_tenant_id_id"),
    )
    op.create_index(
        "uq_mailboxes_tenant_address",
        "mailboxes",
        ["tenant_id", "address"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("mailboxes")
    enable_actor_audit("mailboxes")
    grant_app("mailboxes", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "mail_fetched",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("mailbox_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.String(length=500), nullable=False),
        sa.Column("sender", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("outcome", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("record_type", sa.String(length=40), nullable=True),
        sa.Column("record_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "outcome IN ('created', 'replied', 'automatic', 'own_address', 'held', 'rejected',"
            " 'too_large')",
            name=op.f("ck_mail_fetched_outcome_code"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_mail_fetched_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "mailbox_id"],
            ["mailboxes.tenant_id", "mailboxes.id"],
            name="fk_mail_fetched_mailbox",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "mailbox_id", "message_id", name=op.f("pk_mail_fetched")
        ),
    )
    op.create_index(
        "ix_mail_fetched_tenant_sender_created",
        "mail_fetched",
        ["tenant_id", "sender", "created_at"],
    )
    enable_tenant_rls("mail_fetched")
    grant_app("mail_fetched", ("SELECT", "INSERT"))


def downgrade() -> None:
    op.drop_table("mail_fetched")
    op.drop_table("mailboxes")
