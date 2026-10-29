"""Tables of the files service (WP-022, ADR-028; migration 0018).

- `files`: one stored file (encrypted object, scan state, sniffed type, size, hash).
- `file_links`: where a file is attached (an incident, a reply or note, or an editor draft). Who
  may see it is answered by the owner module (`FileOwnerAccess`); nothing about visibility is
  copied here, so a note made public takes its files along.
- `tenant_data_keys`: the tenant's data keys, wrapped by the installation key ring.
- `tenant_storage_usage`: bytes and files counted against the `storage_gb` limit, kept in the
  same transaction as every link and purge (a row lock makes quota checks exact).
- `file_settings`: the tenant's size and type rules.
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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import (
    Actors,
    Base,
    TenantEntity,
    TenantKeyed,
    TenantScoped,
    Timestamps,
    UuidPrimaryKey,
    Versioned,
)

STATES = ("scanning", "clean", "infected", "scan_failed", "not_scanned", "deleted")
OWNER_TYPES = ("work_item", "conversation_entry", "draft", "branding", "kb_article")
SOURCES = ("ui", "api", "email", "portal")


class StoredFile(TenantEntity):
    """One file. Its bytes live encrypted at `object_key` until the file is purged."""

    __tablename__ = "files"

    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int]
    sha256: Mapped[bytes] = mapped_column(LargeBinary(32))
    content_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10))
    active_markup: Mapped[bool] = mapped_column(Boolean, server_default="false")
    state: Mapped[str] = mapped_column(String(20))
    scan_signature: Mapped[str | None] = mapped_column(String(200))
    scan_attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    scanned_at: Mapped[datetime | None]
    metadata_stripped: Mapped[bool] = mapped_column(Boolean, server_default="false")
    data_key_id: Mapped[uuid.UUID]
    object_key: Mapped[str] = mapped_column(String(300))
    stored_size: Mapped[int]
    thumb_key: Mapped[str | None] = mapped_column(String(300))
    thumb_size: Mapped[int | None]
    source: Mapped[str] = mapped_column(String(10))
    purge_after: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(f"state IN {STATES}", name="state"),
        CheckConstraint(f"source IN {SOURCES}", name="source"),
        CheckConstraint("kind IN ('image', 'pdf', 'other')", name="kind"),
        CheckConstraint("size >= 0", name="size"),
        Index(None, "tenant_id", "state"),
        Index(None, "tenant_id", "purge_after", postgresql_where=text("purge_after IS NOT NULL")),
        UniqueConstraint("tenant_id", "id"),
    )


class FileLink(UuidPrimaryKey, TenantScoped, Timestamps, Actors, Base):
    """Where one file is attached. A file has exactly one link."""

    __tablename__ = "file_links"

    file_id: Mapped[uuid.UUID]
    owner_type: Mapped[str] = mapped_column(String(30))
    owner_id: Mapped[uuid.UUID]
    # The record the owner belongs to (the incident of a reply), for listing a record's files and
    # purging them with it. None for drafts.
    record_type: Mapped[str | None] = mapped_column(String(30))
    record_id: Mapped[uuid.UUID | None]
    inline: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        CheckConstraint(f"owner_type IN {OWNER_TYPES}", name="owner_type"),
        CheckConstraint("(owner_type = 'draft') = (record_id IS NULL)", name="draft_has_no_record"),
        ForeignKeyConstraint(
            ["tenant_id", "file_id"], ["files.tenant_id", "files.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "file_id"),
        Index(None, "tenant_id", "record_type", "record_id"),
        Index(None, "tenant_id", "owner_type", "owner_id"),
    )


class TenantDataKey(UuidPrimaryKey, TenantScoped, Timestamps, Base):
    """A tenant data key, wrapped by installation key `kek_id`. New files use the newest key."""

    __tablename__ = "tenant_data_keys"

    kek_id: Mapped[str] = mapped_column(String(32))
    wrapped: Mapped[bytes] = mapped_column(LargeBinary)
    retired_at: Mapped[datetime | None]

    __table_args__ = (
        Index(None, "tenant_id", "created_at"),
        UniqueConstraint("tenant_id", "id"),
    )


class TenantStorageUsage(TenantKeyed, Base):
    """Stored bytes and files of a tenant (what the `storage_gb` limit counts)."""

    __tablename__ = "tenant_storage_usage"

    bytes_used: Mapped[int] = mapped_column(server_default="0")
    files_count: Mapped[int] = mapped_column(server_default="0")

    __table_args__ = (CheckConstraint("bytes_used >= 0 AND files_count >= 0", name="not_negative"),)


class FileSettings(TenantKeyed, Timestamps, Actors, Versioned, Base):
    """A tenant's file rules (D-082 D7): size limit, batch size, blocked extensions."""

    __tablename__ = "file_settings"

    max_file_mb: Mapped[int] = mapped_column(Integer, server_default="25")
    max_batch: Mapped[int] = mapped_column(Integer, server_default="20")
    blocked_extensions: Mapped[list[str]] = mapped_column(ARRAY(String(16)))

    __table_args__ = (
        CheckConstraint("max_file_mb BETWEEN 1 AND 100", name="max_file_mb"),
        CheckConstraint("max_batch BETWEEN 1 AND 50", name="max_batch"),
    )
