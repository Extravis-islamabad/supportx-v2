"""Audit tables (WP-018, ADR-027). All tenant-scoped with RLS; see migration 0014.

Grants (the database enforces them, whatever this code does):

* `audit_entries`, `audit_personal`: the app may INSERT and SELECT, never UPDATE or DELETE.
* `audit_queue`: INSERT and SELECT; only the sealing function removes rows.
* `audit_chain`: SELECT only; rows are written by the SECURITY DEFINER function `audit_seal()`,
  which computes every chain hash itself.
* `audit_anchors`: INSERT and SELECT (signed checkpoints written by the worker).
* `audit_settings`, `audit_verification_runs`: SELECT, INSERT, UPDATE.
* `audit_subject_salts`: nothing at all. Salts are reached only through the definer functions
  `audit_subject_salts_ensure()`, `audit_subject_salts_of()` and `audit_erase_subject()`
  (migration 0129, ADR-046); no API, viewer or export ever returns one.

`audit_entries` is partitioned by month on `occurred_at`; partitions are created by
`audit_ensure_partitions()` and never appear here (migrations/env.py skips them).
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
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantKeyed, TenantScoped, UuidPrimaryKey, utc_now

OUTCOMES = "('done', 'refused', 'failed')"
ACTOR_TYPES = (
    "('person', 'service_account', 'api_key', 'ai_agent', 'automation', 'system', 'vendor_support')"
)
CLIENTS = "('console', 'portal', 'mobile', 'api', 'worker')"
RUN_KINDS = "('daily', 'weekly', 'on_demand')"
RUN_STATUSES = "('running', 'passed', 'failed', 'error')"
EXPORT_STATUSES = "('running', 'ready', 'failed', 'expired')"
EXPORT_FORMATS = "('jsonl', 'csv')"
ARCHIVE_STATUSES = "('ready', 'failed')"
RESTORE_STATUSES = "('running', 'ready', 'failed')"


class AuditEntry(TenantKeyed, Base):
    """One audited action (append-only; partitioned by month)."""

    __tablename__ = "audit_entries"
    __table_args__ = (
        Index("ix_audit_entries_tenant_id_id", "tenant_id", "id"),
        Index("ix_audit_entries_tenant_actor_time", "tenant_id", "actor_id", "occurred_at"),
        Index("ix_audit_entries_tenant_action_time", "tenant_id", "action", "occurred_at"),
        Index(
            "ix_audit_entries_tenant_object_time",
            "tenant_id",
            "object_type",
            "object_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_entries_tenant_change",
            "tenant_id",
            "change_id",
            postgresql_where=text("change_id IS NOT NULL"),
        ),
        Index(
            "ix_audit_entries_tenant_outcome_time",
            "tenant_id",
            "outcome",
            "occurred_at",
            postgresql_where=text("outcome <> 'done'"),
        ),
        # "action is X or X is among a save's events" (WP-064, migration 0122)
        Index("ix_audit_entries_events", "events", postgresql_using="gin"),
        # The entries whose fingerprint uses a person's salt, for erasure (migration 0129)
        Index("ix_audit_entries_personal_subjects", "personal_subjects", postgresql_using="gin"),
        CheckConstraint(f"outcome IN {OUTCOMES}", name="outcome_code"),
        CheckConstraint(f"actor_type IN {ACTOR_TYPES}", name="actor_type_code"),
        CheckConstraint(f"client IN {CLIENTS}", name="client_code"),
        CheckConstraint("octet_length(entry_hash) = 32", name="entry_hash_length"),
        CheckConstraint("action ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'", name="action_code"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    occurred_at: Mapped[datetime] = mapped_column(primary_key=True, sort_order=-80)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, sort_order=-70)
    action: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40))
    module: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(10))
    reason_code: Mapped[str | None] = mapped_column(String(80))
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID | None]
    on_behalf_id: Mapped[uuid.UUID | None]
    object_type: Mapped[str | None] = mapped_column(String(40))
    object_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    client: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str | None] = mapped_column(String(64))
    change_id: Mapped[uuid.UUID | None]
    personal_commitments: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    # The lifecycle events of a save's entry, most significant first (WP-064, ADR-045); codes
    # only, inside the hash. NULL for every other entry.
    events: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))
    # A save's change-set fingerprints (WP-064 S2, ADR-046): `fp1:<hex>` over digests of the
    # values in field_changes, never the values: `fingerprint` over the ordinary fields (no
    # salt, so it verifies even after an erasure), `personal_fingerprint` over the personal
    # ones, salted (NULL when the saves changed none). With them: the saves (change IDs, in
    # order) and the data subjects whose salts the personal half uses. Inside the hash when
    # set; NULL on every older entry and every non-save entry, which hash exactly as before.
    fingerprint: Mapped[str | None] = mapped_column(String(80))
    personal_fingerprint: Mapped[str | None] = mapped_column(String(80))
    fingerprint_saves: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(Uuid))
    personal_subjects: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(Uuid))
    entry_hash: Mapped[bytes] = mapped_column(LargeBinary)


class AuditQueueItem(TenantKeyed, Base):
    """An entry waiting to be sealed into the chain (removed by `audit_seal()`)."""

    __tablename__ = "audit_queue"
    # The sealing order (migration 0015): without it every batch sorted the whole queue.
    __table_args__ = (Index("ix_audit_queue_tenant_order", "tenant_id", "occurred_at", "entry_id"),)

    entry_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime]


class AuditChainLink(TenantKeyed, Base):
    """The chain: one link per sealed entry, in `seq` order (written only by `audit_seal()`)."""

    __tablename__ = "audit_chain"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entry_id", name="uq_audit_chain_tenant_id_entry_id"),
        Index("ix_audit_chain_tenant_sealed", "tenant_id", "sealed_at"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint(
            "octet_length(entry_hash) = 32 AND octet_length(prev_hash) = 32 "
            "AND octet_length(chain_hash) = 32",
            name="hash_lengths",
        ),
    )

    seq: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[uuid.UUID]
    entry_occurred_at: Mapped[datetime]
    entry_hash: Mapped[bytes] = mapped_column(LargeBinary)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    chain_hash: Mapped[bytes] = mapped_column(LargeBinary)
    sealed_at: Mapped[datetime]


class AuditPersonal(TenantKeyed, Base):
    """Personal data of one subject in one entry, outside the hash (erasable, REQ-AUD-013)."""

    __tablename__ = "audit_personal"
    __table_args__ = (
        Index("ix_audit_personal_tenant_subject", "tenant_id", "subject_id"),
        Index("ix_audit_personal_tenant_time", "tenant_id", "occurred_at"),
        CheckConstraint("octet_length(salt) = 16", name="salt_length"),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    salt: Mapped[bytes] = mapped_column(LargeBinary)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime]


ACCESS_KINDS = ("view", "export", "ai_masking")


class PersonalDataAccess(TenantKeyed, Base):
    """Who viewed or exported whose personal data (REQ-AUD-017; WP-057 S3b-1; 0163).

    Never a value: field codes, and per-type counts for AI masking (REQ-AI-019). Append-only for
    the app role; rows leave only through `audit_erase_access` and `audit_purge_access`. A view is
    written once per accessor, record and 15 minutes (`dedupe_key`).
    """

    __tablename__ = "personal_data_access"
    __table_args__ = (
        CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in ACCESS_KINDS) + ")", name="kind_code"
        ),
        CheckConstraint(
            "subject_person_id IS NOT NULL OR record_id IS NOT NULL", name="names_whose"
        ),
        Index(
            "uq_personal_data_access_once",
            "tenant_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
        Index("ix_personal_data_access_subject", "tenant_id", "subject_person_id", "occurred_at"),
        Index("ix_personal_data_access_time", "tenant_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime]
    accessor_type: Mapped[str] = mapped_column(String(20))
    accessor_id: Mapped[uuid.UUID | None]
    subject_person_id: Mapped[uuid.UUID | None]
    record_type: Mapped[str | None] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID | None]
    kind: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(60))
    fields: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    counts: Mapped[dict[str, int] | None] = mapped_column(JSONB)
    client: Mapped[str | None] = mapped_column(String(20))
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuditAnchor(TenantKeyed, Base):
    """A signed checkpoint of the chain (REQ-AUD-001: detects removal of the newest entries)."""

    __tablename__ = "audit_anchors"
    __table_args__ = (
        CheckConstraint("octet_length(chain_hash) = 32", name="chain_hash_length"),
        CheckConstraint("octet_length(public_key) = 32", name="public_key_length"),
        CheckConstraint("octet_length(signature) = 64", name="signature_length"),
    )

    seq: Mapped[int] = mapped_column(primary_key=True)
    chain_hash: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime]
    key_id: Mapped[str] = mapped_column(String(40))
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    signature: Mapped[bytes] = mapped_column(LargeBinary)


class AuditSettings(TenantKeyed, Base):
    """Per-tenant audit settings (one row, created on first change; defaults in the service)."""

    __tablename__ = "audit_settings"
    __table_args__ = (
        CheckConstraint("retention_days BETWEEN 365 AND 3650", name="retention_range"),
        CheckConstraint("read_window_minutes BETWEEN 1 AND 1440", name="read_window_range"),
        CheckConstraint("refusal_threshold BETWEEN 3 AND 1000", name="refusal_threshold_range"),
        CheckConstraint("refusal_window_minutes BETWEEN 1 AND 1440", name="refusal_window_range"),
    )

    retention_days: Mapped[int] = mapped_column(Integer)
    read_window_minutes: Mapped[int] = mapped_column(Integer)
    refusal_threshold: Mapped[int] = mapped_column(Integer)
    refusal_window_minutes: Mapped[int] = mapped_column(Integer)
    read_categories: Mapped[list[str]] = mapped_column(JSONB)
    # REQ-AUD-017 (WP-057 S3b-1; 0163): the personal data access log is on.
    personal_data_log: Mapped[bool] = mapped_column(default=False, server_default="false")
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    updated_by: Mapped[uuid.UUID | None]


class AuditVerificationRun(UuidPrimaryKey, TenantScoped, Base):
    """One verification of a range of the chain, scheduled or on demand (REQ-AUD-010)."""

    __tablename__ = "audit_verification_runs"
    __table_args__ = (
        Index("ix_audit_verification_runs_tenant_started", "tenant_id", "started_at"),
        CheckConstraint(f"kind IN {RUN_KINDS}", name="kind_code"),
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status_code"),
    )

    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    range_from: Mapped[datetime | None]
    range_to: Mapped[datetime | None]
    entries_checked: Mapped[int] = mapped_column(server_default="0")
    unsealed_overdue: Mapped[int] = mapped_column(server_default="0")
    first_broken_seq: Mapped[int | None]
    first_broken_entry_id: Mapped[uuid.UUID | None]
    problem: Mapped[str | None] = mapped_column(String(40))
    requested_by: Mapped[uuid.UUID | None]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    # Fingerprinted saves checked against record history (WP-064 S2): per verdict.
    fingerprints_verified: Mapped[int] = mapped_column(Integer, server_default="0")
    fingerprints_erased: Mapped[int] = mapped_column(Integer, server_default="0")
    fingerprint_mismatches: Mapped[int] = mapped_column(Integer, server_default="0")
    # Saves verified through digests kept at a signed history redaction (0167).
    fingerprints_redacted: Mapped[int] = mapped_column(Integer, server_default="0")


class AuditSubjectSalt(TenantKeyed, Base):
    """One data subject's salt for fingerprinting personal values (WP-064 S2, ADR-046).

    The app role has no right on this table: only the migrator-owned definer functions read,
    create and erase salts. Erasure sets `salt` NULL (crypto-shredding: the salted digests in
    the chain can no longer be matched to a guess) and keeps the row as a tombstone, so a
    later save never gives the erased person a fresh salt that older entries would not match.
    """

    __tablename__ = "audit_subject_salts"
    __table_args__ = (
        CheckConstraint("salt IS NULL OR octet_length(salt) = 16", name="salt_length"),
        CheckConstraint("(salt IS NULL) = (erased_at IS NOT NULL)", name="salt_or_erased"),
    )

    subject_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    salt: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    erased_at: Mapped[datetime | None]


class AuditExport(UuidPrimaryKey, TenantScoped, Base):
    """An export for auditors (REQ-AUD-009): built in the background, kept for 7 days."""

    __tablename__ = "audit_exports"
    __table_args__ = (
        Index("ix_audit_exports_tenant_created", "tenant_id", "created_at"),
        CheckConstraint(f"status IN {EXPORT_STATUSES}", name="status_code"),
        CheckConstraint(f"format IN {EXPORT_FORMATS}", name="format_code"),
    )

    status: Mapped[str] = mapped_column(String(20))
    format: Mapped[str] = mapped_column(String(10))
    range_from: Mapped[datetime | None]
    range_to: Mapped[datetime | None]
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    requested_by: Mapped[uuid.UUID | None]
    entries: Mapped[int] = mapped_column(server_default="0")
    object_key: Mapped[str | None] = mapped_column(String(300))
    size_bytes: Mapped[int | None]
    sha256: Mapped[str | None] = mapped_column(String(64))
    verification: Mapped[str | None] = mapped_column(String(20))
    problem: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]


class AuditSavedSearch(UuidPrimaryKey, TenantScoped, Base):
    """A search an auditor saved for themselves (REQ-AUD-007)."""

    __tablename__ = "audit_saved_searches"
    __table_args__ = (
        Index("ix_audit_saved_searches_tenant_owner", "tenant_id", "owner_id"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 100", name="name_length"),
    )

    owner_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(100))
    query: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuditArchive(UuidPrimaryKey, TenantScoped, Base):
    """A month of entries past retention, written to object storage and read back (D-076 #10)."""

    __tablename__ = "audit_archives"
    __table_args__ = (
        Index("ix_audit_archives_tenant_range", "tenant_id", "range_from"),
        CheckConstraint(f"status IN {ARCHIVE_STATUSES}", name="status_code"),
        CheckConstraint("range_to > range_from", name="range_order"),
        CheckConstraint(f"restore_status IN {RESTORE_STATUSES}", name="restore_status_code"),
    )

    range_from: Mapped[datetime]
    range_to: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(20))
    object_key: Mapped[str | None] = mapped_column(String(300))
    entries: Mapped[int] = mapped_column(server_default="0")
    first_seq: Mapped[int | None]
    last_seq: Mapped[int | None]
    sha256: Mapped[str | None] = mapped_column(String(64))
    problem: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime]
    # A copy restored for an investigation (audit_restored), kept until `restored_until`.
    restore_status: Mapped[str | None] = mapped_column(String(20))
    restore_problem: Mapped[str | None] = mapped_column(String(60))
    restored_until: Mapped[datetime | None]


class AuditCutoff(TenantKeyed, Base):
    """Entries before `hidden_before` are archived and hidden by RLS (read-only for the app).

    Set only by `audit_advance_cutoff()`, which checks a ready archive covers the range.
    """

    __tablename__ = "audit_cutoffs"

    hidden_before: Mapped[datetime]
    updated_at: Mapped[datetime] = mapped_column(onupdate=utc_now)


class AuditRestored(TenantKeyed, Base):
    """An archived entry restored for an investigation (kept 7 days, outside the live log).

    Archives hold no personal data (it is not kept past retention), so neither does this.
    """

    __tablename__ = "audit_restored"

    archive_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(primary_key=True)
    entry: Mapped[dict[str, Any]] = mapped_column(JSONB)
    entry_hash: Mapped[bytes] = mapped_column(LargeBinary)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    chain_hash: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime]


class FieldChangeRedaction(TenantKeyed, Base):
    """A signed history row blanked by a redaction, with its pre-blank digests (0167).

    ADR-046 addendum: the digests are exactly what the save's fingerprint commits to for that
    field (salted for a personal field), so the verifier can still recompute the fingerprint and
    reports the save as `redacted_on_request`. Read-only for the app role; written only by the
    migrator-owned `history_redact_signed()`.
    """

    __tablename__ = "field_change_redactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "mention_id"],
            ["person_erasure_mentions.tenant_id", "person_erasure_mentions.id"],
            name="fk_field_change_redactions_mention",
        ),
        UniqueConstraint("tenant_id", "field_change_id", name="uq_field_change_redactions_row"),
        CheckConstraint(
            "old_digest ~ '^[0-9a-f]{64}$' AND new_digest ~ '^[0-9a-f]{64}$'",
            name="digest_form",
        ),
        Index("ix_field_change_redactions_change", "tenant_id", "change_id", "field_change_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    field_change_id: Mapped[uuid.UUID]
    change_id: Mapped[uuid.UUID]
    record_type: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID]
    field: Mapped[str] = mapped_column(String(80))
    mention_id: Mapped[uuid.UUID]
    old_digest: Mapped[str] = mapped_column(Text)
    new_digest: Mapped[str] = mapped_column(Text)
    # For auditors reading the table: whether the digests were salted (a personal field). The
    # verifier never trusts it: it takes the field's half from the record type's own spec.
    salted: Mapped[bool] = mapped_column(Boolean)
    redacted_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
