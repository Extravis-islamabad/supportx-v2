"""The ai module's tables (WP-037): the tenant's AI settings, the call log and the embeddings."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

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
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    # Hundredths of a US cent per call, when the provider has a price (local models: none).
    cost_estimate: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10))
    error_code: Mapped[str | None] = mapped_column(String(60))
    outcome: Mapped[str | None] = mapped_column(String(10))
    text_purged_at: Mapped[datetime | None]


# The embedding width of both approved models (bge-m3, multilingual-e5-large; D-131). The HNSW
# index needs one fixed width; another width needs a migration first (see 0075).
EMBEDDING_DIMENSION = 1024


class Vector(UserDefinedType[list[float]]):
    """pgvector's `vector(n)`, written and read as text (`[0.1,0.2]`): no extra package."""

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **_: Any) -> str:  # noqa: ANN401 - SQLAlchemy's signature
        """The column type in DDL."""
        return f"vector({self.dimension})"


# Reflection (Alembic's model check) knows the column type too, instead of warning about it.
ischema_names["vector"] = Vector


class AiEmbedding(UuidPrimaryKey, TenantScoped, Timestamps, Actors, Base):
    """One vector per piece of a record, with the model that made it (REQ-AI-057, 058).

    Searches compare only vectors of the configured model; rows of another model wait for the
    re-embed job (D-131). No text is kept, only its hash, so unchanged text is not embedded again.
    """

    __tablename__ = "ai_embeddings"
    __table_args__ = (
        CheckConstraint(f"dimension = {EMBEDDING_DIMENSION}", name="dimension_width"),
        CheckConstraint("chunk >= 0", name="chunk_positive"),
        UniqueConstraint("tenant_id", "source_type", "source_id", "chunk", "model"),
        Index("ix_ai_embeddings_tenant_model_source", "tenant_id", "model", "source_type"),
        Index(
            "ix_ai_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID]
    chunk: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    model: Mapped[str] = mapped_column(String(120))
    dimension: Mapped[int] = mapped_column(SmallInteger)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION))
