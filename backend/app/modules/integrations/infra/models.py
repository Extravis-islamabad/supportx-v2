"""Mailboxes and the ledger of fetched mail (WP-024; migrations 0037 and 0040).

Both tenant-scoped with RLS. A mailbox's password is stored sealed with the installation key ring
(AES-256-GCM, bound to the tenant and to the purpose "mailbox"), never in clear. The ledger has
one row per (mailbox, message ID): a message is acted on once, even when the poller restarts
between storing it and marking it on the server (REQ-ADM-067 AC2).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed, Timestamps


class Mailbox(TenantEntity):
    """One support mailbox SupportX reads."""

    __tablename__ = "mailboxes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_mailboxes_tenant_id_id"),
        Index(
            "uq_mailboxes_tenant_address",
            "tenant_id",
            "address",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("protocol IN ('imap', 'graph', 'gmail')", name="protocol_code"),
        CheckConstraint(
            "auth_model IS NULL OR auth_model IN ('app', 'delegated')", name="auth_model_code"
        ),
        CheckConstraint(
            "credential_kind IS NULL OR credential_kind IN ('secret', 'certificate')",
            name="credential_kind_code",
        ),
        CheckConstraint(
            "protocol <> 'imap'"
            " OR (host IS NOT NULL AND port IS NOT NULL AND username IS NOT NULL)",
            name="imap_server",
        ),
        Index(
            "uq_mailboxes_tenant_oauth_state",
            "tenant_id",
            "oauth_state_hash",
            unique=True,
            postgresql_where=text("oauth_state_hash IS NOT NULL"),
        ),
        CheckConstraint("security IN ('tls', 'starttls', 'none')", name="security_code"),
        CheckConstraint("after_fetch IN ('mark_read', 'move', 'delete')", name="after_fetch_code"),
        CheckConstraint("creates IN ('incident', 'nothing')", name="creates_code"),
        CheckConstraint(
            "unknown_senders IN ('create', 'create_allowed_domains', 'reject')",
            name="unknown_senders_code",
        ),
        CheckConstraint("state IN ('not_set_up', 'working', 'failing')", name="state_code"),
        CheckConstraint("port BETWEEN 1 AND 65535", name="port_range"),
    )

    address: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(120))
    protocol: Mapped[str] = mapped_column(String(10), server_default="imap")
    host: Mapped[str | None] = mapped_column(String(255))  # IMAP only
    port: Mapped[int | None] = mapped_column(Integer)
    security: Mapped[str] = mapped_column(String(10), server_default="tls")
    allow_plain: Mapped[bool] = mapped_column(Boolean, server_default="false")
    username: Mapped[str | None] = mapped_column(String(320))
    # The IMAP password, or the API mailbox's client secret or certificate (with its key).
    secret_key_id: Mapped[str | None] = mapped_column(String(32))
    secret_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Microsoft 365 and Gmail (session 2): the customer's own OAuth app (D-109 (2)).
    auth_model: Mapped[str | None] = mapped_column(String(12))
    client_id: Mapped[str | None] = mapped_column(String(255))
    directory_id: Mapped[str | None] = mapped_column(String(64))  # Microsoft Entra tenant ID
    credential_kind: Mapped[str | None] = mapped_column(String(12))
    credential_expires_at: Mapped[datetime | None]  # announced ahead (REQ-INT-050)
    credential_warned_at: Mapped[datetime | None]
    token_key_id: Mapped[str | None] = mapped_column(String(32))
    token_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)  # the refresh token
    connected_account: Mapped[str | None] = mapped_column(String(320))  # who signed in
    # A consent in progress: the state's hash, and the PKCE verifier sealed until it returns.
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64))
    oauth_pending_key_id: Mapped[str | None] = mapped_column(String(32))
    oauth_pending_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    oauth_pending_until: Mapped[datetime | None]
    folder: Mapped[str] = mapped_column(String(255), server_default="INBOX")
    after_fetch: Mapped[str] = mapped_column(String(10), server_default="mark_read")
    move_to: Mapped[str | None] = mapped_column(String(255))
    creates: Mapped[str] = mapped_column(String(10), server_default="incident")
    group_id: Mapped[uuid.UUID | None]
    unknown_senders: Mapped[str] = mapped_column(
        String(30), server_default="create_allowed_domains"
    )
    allowed_domains: Mapped[list[str]] = mapped_column(ARRAY(String(255)), server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    state: Mapped[str] = mapped_column(String(12), server_default="not_set_up")
    state_reason: Mapped[str | None] = mapped_column(String(60))
    last_fetch_at: Mapped[datetime | None]
    next_fetch_at: Mapped[datetime | None]


class MailFetched(TenantKeyed, Timestamps, Base):
    """One message fetched from a mailbox, and what it became."""

    __tablename__ = "mail_fetched"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "mailbox_id"],
            ["mailboxes.tenant_id", "mailboxes.id"],
            name="fk_mail_fetched_mailbox",
        ),
        Index("ix_mail_fetched_tenant_sender_created", "tenant_id", "sender", "created_at"),
        # The review queue: what waits for an admin, per mailbox (D-109 (9)).
        Index(
            "ix_mail_fetched_tenant_waiting",
            "tenant_id",
            "mailbox_id",
            "created_at",
            postgresql_where=text("outcome IN ('held', 'too_large')"),
        ),
        CheckConstraint(
            "outcome IN ('created', 'replied', 'automatic', 'own_address', 'held', 'rejected',"
            " 'too_large', 'discarded')",
            name="outcome_code",
        ),
    )

    mailbox_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(500), primary_key=True)
    sender: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    outcome: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str | None] = mapped_column(String(40))  # a label code, never shown raw
    reason_params: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    record_type: Mapped[str | None] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID | None]
    # The message as fetched, kept only while it waits for an admin (released or discarded:
    # cleared). Not kept for mail over the size limit.
    raw: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    handled_by: Mapped[uuid.UUID | None]  # the admin who released or discarded it
