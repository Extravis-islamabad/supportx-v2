"""Mailboxes, the ledger of fetched mail and the secrets store (WP-024, WP-040).

Migrations 0037 and 0042 (mailboxes), 0045 (connector secrets), 0049 (connector runs, health).

Both tenant-scoped with RLS. A mailbox's password is stored sealed with the installation key ring
(AES-256-GCM, bound to the tenant and to the purpose "mailbox"), never in clear. The ledger has
one row per (mailbox, message ID): a message is acted on once, even when the poller restarts
between storing it and marking it on the server (REQ-ADM-067 AC2).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed, Timestamps, utc_now


class Mailbox(TenantEntity):
    """One support mailbox SupportX reads."""

    __tablename__ = "mailboxes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_mailboxes_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "secret_ref"],
            ["connector_secrets.tenant_id", "connector_secrets.id"],
            name="fk_mailboxes_secret_ref",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "token_ref"],
            ["connector_secrets.tenant_id", "connector_secrets.id"],
            name="fk_mailboxes_token_ref",
        ),
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
    # Kept, and still written, until the contract step after the secrets store (0045) is proven;
    # `secret_ref` and `token_ref` point at the store's copies.
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
    # A sender is over the flood limit and their mail waits for review (REQ-NTF-023); cleared by
    # the fetch once every such sender is back under the limit.
    flooding: Mapped[bool] = mapped_column(Boolean, server_default="false")
    next_fetch_at: Mapped[datetime | None]
    secret_ref: Mapped[uuid.UUID | None]  # connector_secrets (WP-040)
    token_ref: Mapped[uuid.UUID | None]
    # The store's copy could not be read and the old column was used: shown as degraded until a
    # read from the store works again (never silent).
    secret_fallback_at: Mapped[datetime | None]


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


class ConnectorSecret(TenantEntity):
    """One sealed credential of a connector (WP-040, REQ-INT-003; migration 0045).

    Sealed with the installation key ring, bound to the tenant and to `purpose` (the same
    context the owner used before the store, so moved secrets were copied without being opened).
    Never returned or logged; the API shows its name, type and age. Rotating replaces the value
    behind the same row, so what uses it keeps its reference.
    """

    __tablename__ = "connector_secrets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_connector_secrets_tenant_id_id"),
        Index(
            "uq_connector_secrets_tenant_owner_role",
            "tenant_id",
            "owner_kind",
            "owner_id",
            "role",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_connector_secrets_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "secret_type IN ('password', 'client_secret', 'certificate', 'refresh_token')",
            name="secret_type_code",
        ),
        # A password never shows any of its characters (product owner, 2026-11-02).
        CheckConstraint(
            "secret_type <> 'password' OR last_four IS NULL", name="no_password_ending"
        ),
    )

    name: Mapped[str] = mapped_column(String(200))  # stable; exports carry {{secret:<name>}}
    secret_type: Mapped[str] = mapped_column(String(20))
    owner_kind: Mapped[str] = mapped_column(String(40))  # a connector kind code ("mailbox")
    owner_id: Mapped[uuid.UUID]
    role: Mapped[str] = mapped_column(String(20))  # which of the owner's secrets
    purpose: Mapped[str] = mapped_column(String(40))  # the sealing context
    key_id: Mapped[str] = mapped_column(String(32))
    sealed: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    set_at: Mapped[datetime]  # its age (REQ-INT-003 AC3)
    # "ending in ..a3f9", for display only, never for verification, and only for long random
    # secrets (product owner, 2026-11-02): client secrets and refresh tokens; for a certificate
    # its public thumbprint's end. Never for a password.
    last_four: Mapped[str | None] = mapped_column(String(4))


class ConnectorHealth(TenantKeyed, Base):
    """One connector instance's standing between runs (WP-040, REQ-INT-004/005; migration 0049).

    Any kind's instance: `kind` is the catalogue code, `instance_id` the owner's own ID (a
    mailbox). Written only by `service.runs.record_run`, in the run's own transaction.
    """

    __tablename__ = "connector_health"

    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    failing: Mapped[bool] = mapped_column(Boolean, server_default="false")
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default="0")
    failing_since: Mapped[datetime | None]
    last_success_at: Mapped[datetime | None]
    last_error_at: Mapped[datetime | None]
    last_error_code: Mapped[str | None] = mapped_column(String(60))  # a label code
    updated_at: Mapped[datetime] = mapped_column(onupdate=utc_now)


class ConnectorIdentity(TenantKeyed, Base):
    """The service identity a connector instance acts as (WP-040, REQ-INT-012; migration 0052).

    One per instance, made with it (or at its next run); the user row is identity_access's.
    """

    __tablename__ = "connector_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_connector_identities_user",
        ),
        UniqueConstraint("tenant_id", "user_id", name="uq_connector_identities_tenant_user"),
    )

    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ConnectorRun(TenantKeyed, Base):
    """One run of a connector and its counts (kept RUN_RETENTION_DAYS; migration 0049)."""

    __tablename__ = "connector_runs"
    __table_args__ = (
        Index(
            "ix_connector_runs_tenant_instance_finished", "tenant_id", "instance_id", "finished_at"
        ),
        Index("ix_connector_runs_tenant_finished", "tenant_id", "finished_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    instance_id: Mapped[uuid.UUID]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime]
    ok: Mapped[bool] = mapped_column(Boolean)
    read: Mapped[int] = mapped_column(Integer, server_default="0")
    created: Mapped[int] = mapped_column(Integer, server_default="0")
    updated: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, server_default="0")
    failed: Mapped[int] = mapped_column(Integer, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(60))


class ConnectorError(TenantKeyed, Base):
    """One failure of a connector, for its error list (kept ERROR_RETENTION_DAYS, REQ-INT-005 AC3).

    A code and when, never the outside system's message text (it may carry personal data).
    """

    __tablename__ = "connector_errors"
    __table_args__ = (
        Index("ix_connector_errors_tenant_instance_at", "tenant_id", "instance_id", "occurred_at"),
        Index("ix_connector_errors_tenant_at", "tenant_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    instance_id: Mapped[uuid.UUID]
    occurred_at: Mapped[datetime]
    code: Mapped[str] = mapped_column(String(60))


class DirectoryConnector(TenantEntity):
    """A directory SupportX takes its people from (WP-040 session 2; REQ-INT-063; migration 0053).

    The customer's own least-privilege sync app (`client_id`, secret in `connector_secrets`),
    who is synced (`scope`: everyone or `scope_groups`), how attributes map (`mapping`) and which
    directory groups fill which SupportX groups (`group_mappings`). The delta links say where the
    next round starts; Graph keeps them for about a week, then a round starts again.
    """

    __tablename__ = "directory_connectors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_directory_connectors_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "secret_ref"],
            ["connector_secrets.tenant_id", "connector_secrets.id"],
            name="fk_directory_connectors_secret_ref",
        ),
        Index(
            "uq_directory_connectors_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("source IN ('entra')", name="source_code"),
        CheckConstraint("scope IN ('all_users', 'groups')", name="scope_code"),
        CheckConstraint(
            "credential_kind IN ('secret', 'certificate')", name="credential_kind_code"
        ),
        CheckConstraint("interval_minutes BETWEEN 15 AND 1440", name="interval_range"),
    )

    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), server_default="entra")
    directory_tenant: Mapped[str] = mapped_column(String(200))  # Entra tenant ID or domain
    client_id: Mapped[str] = mapped_column(String(200))
    credential_kind: Mapped[str] = mapped_column(String(20))
    secret_ref: Mapped[uuid.UUID | None]
    scope: Mapped[str] = mapped_column(String(20), server_default="all_users")
    # Any: JSON lists and objects, read through the domain's types.
    scope_groups: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    group_mappings: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    interval_minutes: Mapped[int] = mapped_column(Integer, server_default="30")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    users_delta_link: Mapped[str | None] = mapped_column(Text, deferred=True)
    groups_delta_link: Mapped[str | None] = mapped_column(Text, deferred=True)
    next_sync_at: Mapped[datetime | None]
    last_synced_at: Mapped[datetime | None]
    # The last run's skipped people and values by reason code ({"unknown_site": 3}), shown on
    # the connector page: never names or addresses.
    last_skips: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class DirectoryPersonLink(TenantKeyed, Base):
    """Which SupportX person a directory person is (one each way; migration 0053)."""

    __tablename__ = "directory_people"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connector_id"],
            ["directory_connectors.tenant_id", "directory_connectors.id"],
            name="fk_directory_people_connector",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_directory_people_user",
        ),
        UniqueConstraint("tenant_id", "user_id", name="uq_directory_people_tenant_user"),
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID]
    manager_external_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DirectoryMembership(TenantKeyed, Base):
    """A directory person in a directory group the connector reads (migration 0053).

    Bookkeeping of the sync, not people data: a person leaves the scope when they are in none of
    the scope groups, and a mapped SupportX group follows its directory group.
    """

    __tablename__ = "directory_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connector_id"],
            ["directory_connectors.tenant_id", "directory_connectors.id"],
            name="fk_directory_memberships_connector",
        ),
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    group_external_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), primary_key=True)
