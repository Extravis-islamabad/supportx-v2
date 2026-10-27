"""The mail service and invitations (WP-039 session 2; D-089 D3, D-099).

- mail_messages, mail_attachments: the one outgoing mail sender's queue (docs/architecture/
  mail.md); bodies and attachments cleared `mail_content_retention_days` after sending.
- invitations: who was invited to sign in, when, until when, and what became of it
  (REQ-SEC-018..020); Keycloak sends the e-mail.
- identity_settings.invitation_valid_days: how long an invitation link works (7, 1 to 30);
- identity_settings.password_*: the installation's password policy and whether it is applied.

All tenant-scoped with RLS. Reversible.

Revision ID: 0026
Revises: 0027
Created: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0026"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# identity_settings: the installation's password policy (REQ-SEC-005, Appendix A defaults).
PASSWORD_COLUMNS = [
    (name, sa.Column(name, kind, server_default=default, nullable=nullable))
    for name, kind, default, nullable in (
        ("password_min_length", sa.BigInteger(), "12", False),
        ("password_upper", sa.Boolean(), "true", False),
        ("password_lower", sa.Boolean(), "true", False),
        ("password_digits", sa.Boolean(), "true", False),
        ("password_special", sa.Boolean(), "true", False),
        ("password_history", sa.BigInteger(), "5", False),
        ("password_expiry_days", sa.BigInteger(), "0", False),
        ("password_breached_check", sa.Boolean(), "true", False),
        ("password_policy_state", sa.String(length=20), "default", False),
        ("password_policy_error", sa.String(length=60), None, True),
    )
]


def upgrade() -> None:
    op.create_table(
        "mail_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("recipients", postgresql.ARRAY(sa.String(length=320)), nullable=False),
        sa.Column("reply_to", sa.String(length=320), nullable=True),
        sa.Column("sender_name", sa.String(length=120), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=10), server_default="queued", nullable=False),
        sa.Column("attempts", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("failure", sa.String(length=40), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
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
            "language IN ('en', 'ar', 'ur')", name=op.f("ck_mail_messages_language_code")
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'sent', 'failed')", name=op.f("ck_mail_messages_state_code")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_mail_messages_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_messages")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_mail_messages_tenant_id_id")),
    )
    op.create_index(
        "ix_mail_messages_tenant_purge", "mail_messages", ["tenant_id", "purge_after"], unique=False
    )
    op.create_index(
        "ix_mail_messages_tenant_state",
        "mail_messages",
        ["tenant_id", "state", "next_attempt_at"],
        unique=False,
    )
    enable_tenant_rls("mail_messages")
    grant_app("mail_messages", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("mail_messages")
    op.create_table(
        "mail_attachments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["mail_messages.tenant_id", "mail_messages.id"],
            name="fk_mail_attachments_message",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_mail_attachments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_attachments")),
    )
    op.create_index(
        "ix_mail_attachments_tenant_message",
        "mail_attachments",
        ["tenant_id", "message_id"],
        unique=False,
    )
    enable_tenant_rls("mail_attachments")
    grant_app("mail_attachments", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("mail_attachments")
    op.create_table(
        "invitations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("delivery", sa.String(length=20), server_default="email", nullable=False),
        sa.Column("keycloak_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_account", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sends", sa.BigInteger(), server_default="1", nullable=False),
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
            "delivery IN ('email', 'existing_account')", name=op.f("ck_invitations_delivery_code")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked')", name=op.f("ck_invitations_status_code")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_invitations_user"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_invitations_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
    )
    op.create_index(
        "ix_invitations_tenant_created",
        "invitations",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_invitations_tenant_user",
        "invitations",
        ["tenant_id", "user_id", "status"],
        unique=False,
    )
    enable_tenant_rls("invitations")
    grant_app("invitations", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("invitations")
    op.add_column(
        "identity_settings",
        sa.Column("invitation_valid_days", sa.BigInteger(), server_default="7", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_identity_settings_invitation_days_range"),
        "identity_settings",
        "invitation_valid_days BETWEEN 1 AND 30",
    )
    for _, column in PASSWORD_COLUMNS:
        op.add_column("identity_settings", column)
    op.create_check_constraint(
        op.f("ck_identity_settings_password_policy_range"),
        "identity_settings",
        "password_min_length BETWEEN 8 AND 64 AND password_history BETWEEN 0 AND 24"
        " AND password_expiry_days BETWEEN 0 AND 365",
    )
    op.create_check_constraint(
        op.f("ck_identity_settings_password_policy_state"),
        "identity_settings",
        "password_policy_state IN ('default', 'applying', 'applied', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_identity_settings_password_policy_state"), "identity_settings")
    op.drop_constraint(op.f("ck_identity_settings_password_policy_range"), "identity_settings")
    for name, _ in reversed(PASSWORD_COLUMNS):
        op.drop_column("identity_settings", name)
    op.drop_constraint(op.f("ck_identity_settings_invitation_days_range"), "identity_settings")
    op.drop_column("identity_settings", "invitation_valid_days")
    op.drop_index("ix_invitations_tenant_user", table_name="invitations")
    op.drop_index("ix_invitations_tenant_created", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_mail_attachments_tenant_message", table_name="mail_attachments")
    op.drop_table("mail_attachments")
    op.drop_index("ix_mail_messages_tenant_state", table_name="mail_messages")
    op.drop_index("ix_mail_messages_tenant_purge", table_name="mail_messages")
    op.drop_table("mail_messages")
