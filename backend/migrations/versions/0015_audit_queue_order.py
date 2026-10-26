"""Audit queue: index the sealing order (WP-018 follow-up; ADR-027).

`audit_seal()` takes the oldest queued entries (`ORDER BY occurred_at, entry_id LIMIT n`). Without
an index on that order every batch sorted the whole queue: harmless for a few hundred queued
entries, but a backlog of 10M (the nightly volume test; or a long sealer outage) never finished.
With the index each batch reads only the rows it seals.

The queue is normally a handful of rows (entries are sealed within seconds), so a plain CREATE
INDEX is quick. Additive (expand only; reversible).

Revision ID: 0015
Revises: 0014
Created: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_queue_tenant_order", "audit_queue", ["tenant_id", "occurred_at", "entry_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_queue_tenant_order", table_name="audit_queue")
