"""Tables of the mail service (WP-039 session 2): queued messages and their attachments.

Bodies and attachments are personal data: they are cleared once sent (or given up on), after
`mail_content_retention_days`; the row stays as the record of what was sent, when, to whom.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import TenantEntity

MAIL_STATES = ("queued", "sent", "failed")


class MailMessage(TenantEntity):
    """One outgoing message, as queued; the worker sends it."""

    __tablename__ = "mail_messages"
    __table_args__ = (
        CheckConstraint("state IN ('queued', 'sent', 'failed')", name="state_code"),
        CheckConstraint("language IN ('en', 'ar', 'ur')", name="language_code"),
        Index("ix_mail_messages_tenant_state", "tenant_id", "state", "created_at"),
        Index("ix_mail_messages_tenant_purge", "tenant_id", "purge_after"),
        # Target of the attachments' same-tenant foreign key.
        UniqueConstraint("tenant_id", "id"),
    )

    kind: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(5))
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String(320)))
    reply_to: Mapped[str | None] = mapped_column(String(320))
    sender_name: Mapped[str | None] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(300))
    text_body: Mapped[str | None] = mapped_column(Text)
    html_body: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(10), server_default="queued")
    attempts: Mapped[int] = mapped_column(server_default="0")
    failure: Mapped[str | None] = mapped_column(String(40))
    sent_at: Mapped[datetime | None]
    message_id: Mapped[str | None] = mapped_column(String(255))
    purge_after: Mapped[datetime | None]


class MailAttachment(TenantEntity):
    """A file sent with a message (content cleared with the message's body)."""

    __tablename__ = "mail_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["mail_messages.tenant_id", "mail_messages.id"],
            name="fk_mail_attachments_message",
            ondelete="CASCADE",
        ),
        Index("ix_mail_attachments_tenant_message", "tenant_id", "message_id"),
    )

    message_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
