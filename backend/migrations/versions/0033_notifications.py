"""Notifications (WP-023): rules, in-app entries, the delivery log and personal preferences.

Tenant-scoped with RLS. In-app entries and delivery rows are a log with a retention period
(Appendix A: 90 and 180 days), removed by the notifications retention schedule; rules are soft
deleted like every record; preferences are one row per person.

Revision ID: 0033
Revises: 0032
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _times() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_code", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("recipients", postgresql.ARRAY(sa.String(length=40)), nullable=False),
        sa.Column("channels", postgresql.ARRAY(sa.String(length=10)), nullable=False),
        sa.Column("user_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("group_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("conditions", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("notify_actor", sa.Boolean(), server_default="false", nullable=False),
        *_times(),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(event_code) BETWEEN 3 AND 80",
            name=op.f("ck_notification_rules_event_code_length"),
        ),
        sa.CheckConstraint(
            "channels <@ ARRAY['in_app', 'email']::varchar[]",
            name=op.f("ck_notification_rules_channel_codes"),
        ),
        sa.CheckConstraint(
            "cardinality(user_ids) <= 50 AND cardinality(group_ids) <= 50",
            name=op.f("ck_notification_rules_named_limit"),
        ),
        _tenant_fk("notification_rules"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_rules")),
        sa.UniqueConstraint("tenant_id", "event_code", name="uq_notification_rules_event"),
    )
    enable_tenant_rls("notification_rules")
    enable_actor_audit("notification_rules")
    grant_app("notification_rules", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_code", sa.String(length=80), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("display_id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("link", sa.String(length=300), nullable=False),
        sa.Column("urgent", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        *_times(),
        _tenant_fk("notifications"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_notifications_user",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notifications_tenant_id_id"),
    )
    op.create_index(
        "ix_notifications_tenant_user_created",
        "notifications",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_index(
        "ix_notifications_tenant_user_unread",
        "notifications",
        ["tenant_id", "user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_index("ix_notifications_tenant_created", "notifications", ["tenant_id", "created_at"])
    enable_tenant_rls("notifications")
    # Entries are written by the consumers worker, marked read by their owner, removed by the
    # retention schedule.
    grant_app("notifications", ("SELECT", "INSERT", "UPDATE", "DELETE"))

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_code", sa.String(length=80), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("display_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("reasons", postgresql.ARRAY(sa.String(length=40)), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("language", sa.String(length=5), nullable=True),
        sa.Column("notification_id", sa.Uuid(), nullable=True),
        sa.Column("mail_id", sa.Uuid(), nullable=True),
        sa.Column("resent_from", sa.Uuid(), nullable=True),
        sa.Column("resent_by", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        *_times(),
        sa.CheckConstraint(
            "channel IN ('in_app', 'email')", name=op.f("ck_notification_deliveries_channel_code")
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'waiting', 'sent', 'failed', 'suppressed')",
            name=op.f("ck_notification_deliveries_state_code"),
        ),
        _tenant_fk("notification_deliveries"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notification_deliveries_tenant_id_id"),
    )
    op.create_index(
        "ix_notification_deliveries_tenant_record",
        "notification_deliveries",
        ["tenant_id", "record_id", "created_at"],
    )
    op.create_index(
        "ix_notification_deliveries_tenant_waiting",
        "notification_deliveries",
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("state = 'waiting'"),
    )
    op.create_index(
        "ix_notification_deliveries_tenant_created",
        "notification_deliveries",
        ["tenant_id", "created_at"],
    )
    enable_tenant_rls("notification_deliveries")
    grant_app("notification_deliveries", ("SELECT", "INSERT", "UPDATE", "DELETE"))

    op.create_table(
        "notification_preferences",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("off", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("do_not_disturb", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        *_times(),
        _tenant_fk("notification_preferences"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_notification_preferences_user",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name=op.f("pk_notification_preferences")),
    )
    enable_tenant_rls("notification_preferences")
    grant_app("notification_preferences", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_table("notification_deliveries")
    op.drop_table("notifications")
    op.drop_table("notification_rules")
