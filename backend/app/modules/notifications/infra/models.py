"""Notification tables (WP-023): rules, in-app entries, the delivery log and preferences.

All tenant-scoped with RLS (migration 0033). In-app entries and delivery rows are removed by the
retention schedule (90 and 180 days, Appendix A), not soft-deleted: they are a log, not records.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import (
    Base,
    TenantEntity,
    TenantKeyed,
    TenantScoped,
    Timestamps,
    UuidPrimaryKey,
)


class NotificationRule(TenantEntity):
    """A tenant's saved rule for one event; events without a row use the shipped default."""

    __tablename__ = "notification_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_code", name="uq_notification_rules_event"),
        CheckConstraint("char_length(event_code) BETWEEN 3 AND 80", name="event_code_length"),
    )

    event_code: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean)
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    channels: Mapped[list[str]] = mapped_column(ARRAY(String(10)))
    user_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    group_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    conditions: Mapped[list[dict[str, object]]] = mapped_column(JSONB, server_default="[]")
    notify_actor: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Notification(UuidPrimaryKey, TenantScoped, Timestamps, Base):
    """One entry in a person's notification centre (REQ-INC-131), in their language."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_notifications_tenant_id_id"),
        Index("ix_notifications_tenant_user_created", "tenant_id", "user_id", "created_at"),
        Index(
            "ix_notifications_tenant_user_unread",
            "tenant_id",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
        Index("ix_notifications_tenant_created", "tenant_id", "created_at"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_notifications_user"
        ),
    )

    user_id: Mapped[uuid.UUID]
    event_code: Mapped[str] = mapped_column(String(80))
    record_type: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID]
    display_id: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    link: Mapped[str] = mapped_column(String(300))
    urgent: Mapped[bool] = mapped_column(Boolean, server_default="false")
    read_at: Mapped[datetime | None]


class NotificationDelivery(UuidPrimaryKey, TenantScoped, Timestamps, Base):
    """One message to one person on one channel, with its state and reason (REQ-NTF-020)."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_notification_deliveries_tenant_id_id"),
        Index(
            "ix_notification_deliveries_tenant_record",
            "tenant_id",
            "record_id",
            "created_at",
        ),
        Index(
            "ix_notification_deliveries_tenant_waiting",
            "tenant_id",
            "created_at",
            postgresql_where=text("state = 'waiting'"),
        ),
        Index("ix_notification_deliveries_tenant_created", "tenant_id", "created_at"),
        CheckConstraint("channel IN ('in_app', 'email')", name="channel_code"),
        CheckConstraint(
            "state IN ('queued', 'waiting', 'sent', 'failed', 'suppressed')", name="state_code"
        ),
    )

    event_id: Mapped[uuid.UUID]
    event_code: Mapped[str] = mapped_column(String(80))
    record_type: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID]
    display_id: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[uuid.UUID | None]
    reasons: Mapped[list[str]] = mapped_column(ARRAY(String(40)))  # how the rule reached them
    channel: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(40))
    language: Mapped[str | None] = mapped_column(String(5))
    notification_id: Mapped[uuid.UUID | None]
    mail_id: Mapped[uuid.UUID | None]
    resent_from: Mapped[uuid.UUID | None]
    resent_by: Mapped[uuid.UUID | None]
    # The rendered e-mail while it waits for outgoing mail to be set up; cleared once it is
    # handed to the mail sender (which keeps its own copy for its retention period).
    subject: Mapped[str | None] = mapped_column(String(300))
    text_body: Mapped[str | None] = mapped_column(Text)
    html_body: Mapped[str | None] = mapped_column(Text)


class NotificationPreference(TenantKeyed, Timestamps, Base):
    """One person's notification choices (REQ-NTF-016); no row means the defaults."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_notification_preferences_user",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # [["conversation", "email"], ...]: (category, channel) pairs switched off
    off: Mapped[list[list[str]]] = mapped_column(JSONB, server_default="[]")
    do_not_disturb: Mapped[bool] = mapped_column(Boolean, server_default="false")
    version: Mapped[int] = mapped_column(BigInteger, server_default="1")
