"""The embedding store behind the one embedding and retrieval service (WP-037, REQ-AI-057, 058).

Expand only:

- `ai_embeddings` (RLS, FORCE): one vector per piece of a record (`source_type`, `source_id`,
  `chunk`), with the model that made it. A search only ever compares vectors of the configured
  model (D-131: models swap by configuration; vectors of two models never meet), and a model
  change leaves the old rows to be re-embedded by a background job, never mixed in.
- The vectors are 1024 wide, the width of both approved embedding models (bge-m3 and
  multilingual-e5-large). The HNSW index needs one fixed width, so a model of another width is
  refused by configuration until a migration widens the column (recorded in D-131).
- Derived data, like a search index: the application role may delete rows (a record removed or
  re-embedded). No text is stored, only a hash of it, so unchanged text is never embedded again.

No data step. The downgrade drops the table.

Revision ID: 0075
Revises: 0072
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0075"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIMENSION = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "ai_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("chunk", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("dimension", sa.SmallInteger(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),  # retyped to vector below
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            f"dimension = {DIMENSION}", name=op.f("ck_ai_embeddings_dimension_width")
        ),
        sa.CheckConstraint("chunk >= 0", name=op.f("ck_ai_embeddings_chunk_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ai_embeddings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_embeddings")),
        sa.UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_id",
            "chunk",
            "model",
            name=op.f("uq_ai_embeddings_tenant_id_source_type_source_id_chunk_model"),
        ),
    )
    op.execute(
        f"ALTER TABLE ai_embeddings ALTER COLUMN embedding TYPE vector({DIMENSION}) "
        f"USING embedding::vector({DIMENSION})"
    )
    # Stale rows (another model) are found by tenant and model; searches filter on both too.
    op.create_index(
        "ix_ai_embeddings_tenant_model_source",
        "ai_embeddings",
        ["tenant_id", "model", "source_type"],
    )
    # Nearest neighbours by cosine distance (the models' vectors are normalised).
    op.execute(
        "CREATE INDEX ix_ai_embeddings_embedding_hnsw ON ai_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    enable_tenant_rls("ai_embeddings")
    enable_actor_audit("ai_embeddings")
    grant_app("ai_embeddings", ("SELECT", "INSERT", "UPDATE", "DELETE"))


def downgrade() -> None:
    op.drop_table("ai_embeddings")
