"""Audit tables (WP-018, ADR-027). All tenant-scoped with RLS; see migration 0013.

Grants (the database enforces them, whatever this code does):

* `audit_entries`, `audit_personal`: the app may INSERT and SELECT, never UPDATE or DELETE.
* `audit_queue`: INSERT and SELECT; only the sealing function removes rows.
* `audit_chain`: SELECT only; rows are written by the SECURITY DEFINER function `audit_seal()`,
  which computes every chain hash itself.
* `audit_anchors`: INSERT and SELECT (signed checkpoints written by the worker).
* `audit_settings`, `audit_verification_runs`: SELECT, INSERT, UPDATE.

`audit_entries` is partitioned by month on `occurred_at`; partitions are created by
`audit_ensure_partitions()` and never appear here (migrations/env.py skips them).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantKeyed, TenantScoped, UuidPrimaryKey

OUTCOMES = "('done', 'refused', 'failed')"
ACTOR_TYPES = (
    "('person', 'service_account', 'api_key', 'ai_agent', 'automation', 'system', 'vendor_support')"
)
CLIENTS = "('console', 'portal', 'mobile', 'api', 'worker')"
RUN_KINDS = "('daily', 'weekly', 'on_demand')"
RUN_STATUSES = "('running', 'passed', 'failed', 'error')"


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
    entry_hash: Mapped[bytes] = mapped_column(LargeBinary)


class AuditQueueItem(TenantKeyed, Base):
    """An entry waiting to be sealed into the chain (removed by `audit_seal()`)."""

    __tablename__ = "audit_queue"

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
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
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
