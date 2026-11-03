"""The ai module's tables (WP-037): the tenant's AI settings and the call log."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import (
    Actors,
    Base,
    TenantKeyed,
    TenantScoped,
    Timestamps,
    UuidPrimaryKey,
    utc_now,
)


class AiSettings(TenantKeyed, Base):
    """One row per tenant (REQ-AI-027, 031), created with the defaults on first use.

    AI is on, every feature on, local calls unmasked (masking is always on for an external
    provider, whatever this says), and call text kept for `log_retention_days` (30 by default
    until the product owner confirms the number).
    """

    __tablename__ = "ai_settings"
    __table_args__ = (
        CheckConstraint("log_retention_days BETWEEN 1 AND 365", name="log_retention_range"),
    )

    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    disabled_features: Mapped[list[str]] = mapped_column(ARRAY(String(40)), server_default="{}")
    mask_local: Mapped[bool] = mapped_column(Boolean, server_default="false")
    log_retention_days: Mapped[int] = mapped_column(Integer, server_default="30")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    updated_by: Mapped[uuid.UUID | None]


class AiCall(UuidPrimaryKey, TenantScoped, Timestamps, Actors, Base):
    """One AI call (REQ-AI-031): who, what, which model, the masked text, the cost and outcome.

    The text (`masked_input`, `output`) is cleared after the tenant's retention period by the
    purge job; the row with its counts and outcome stays for usage and quality reporting.
    """

    __tablename__ = "ai_calls"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'failed', 'refused')", name="status_code"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('accepted', 'edited', 'discarded')", name="outcome_code"
        ),
        Index("ix_ai_calls_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_calls_tenant_feature", "tenant_id", "feature", "created_at"),
    )

    feature: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[uuid.UUID | None]
    record_type: Mapped[str | None] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID | None]
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    masked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    masked_values: Mapped[int] = mapped_column(Integer, server_default="0")
    masked_input: Mapped[str | None] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    tools: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    sources: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    guardrail_events: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    latency_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    # Hundredths of a US cent per call, when the provider has a price (local models: none).
    cost_estimate: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(10))
    error_code: Mapped[str | None] = mapped_column(String(60))
    outcome: Mapped[str | None] = mapped_column(String(10))
    text_purged_at: Mapped[datetime | None]
