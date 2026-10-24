"""Field history and display counters for the work item engine (WP-020, ADR-026).

field_changes:
- new sources `portal`, `email`, `sla`, `integration` and child kinds (`child_added`,
  `child_changed`, `child_removed`): parts of a record are recorded without bumping its version;
- `automation_ref` (JSONB): which rule, matrix or agent made a change;
- an index for reading history in true time order (occurred_at, change_id).

display_id_sequences: the counter key may now be an internal key such as `WI_INCIDENT`, so work
item numbering follows the type, not the (renamable) prefix.

Expand-only: no existing row changes. The downgrade restores the old checks; it fails only if
rows using the new codes exist, which is the safe outcome.

Revision ID: 0011
Revises: 0010
Created: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ("created", "updated", "status", "deleted", "restored")
NEW_KINDS = (*OLD_KINDS, "child_added", "child_changed", "child_removed")
OLD_SOURCES = ("ui", "api", "rule", "workflow", "ai_agent", "system", "import")
NEW_SOURCES = (
    "ui",
    "api",
    "portal",
    "email",
    "rule",
    "workflow",
    "sla",
    "ai_agent",
    "integration",
    "system",
    "import",
)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _checks(kinds: Sequence[str], sources: Sequence[str]) -> None:
    op.drop_constraint(op.f("ck_field_changes_kind_code"), "field_changes", type_="check")
    op.drop_constraint(op.f("ck_field_changes_source_code"), "field_changes", type_="check")
    op.create_check_constraint(
        op.f("ck_field_changes_kind_code"), "field_changes", _in("kind", kinds)
    )
    op.create_check_constraint(
        op.f("ck_field_changes_source_code"), "field_changes", _in("source", sources)
    )


def upgrade() -> None:
    op.add_column(
        "field_changes",
        sa.Column("automation_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    _checks(NEW_KINDS, NEW_SOURCES)
    op.create_index(
        "ix_field_changes_tenant_record_time",
        "field_changes",
        ["tenant_id", "record_type", "record_id", "occurred_at", "change_id"],
    )
    op.drop_constraint(
        op.f("ck_display_id_sequences_prefix_format"), "display_id_sequences", "check"
    )
    op.create_check_constraint(
        op.f("ck_display_id_sequences_prefix_format"),
        "display_id_sequences",
        "prefix ~ '^[A-Z][A-Z_]{1,39}$'",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_display_id_sequences_prefix_format"), "display_id_sequences", "check"
    )
    op.create_check_constraint(
        op.f("ck_display_id_sequences_prefix_format"),
        "display_id_sequences",
        "prefix ~ '^[A-Z]{2,6}$'",
    )
    op.drop_index(
        "ix_field_changes_tenant_record_time",
        table_name="field_changes",
    )
    _checks(OLD_KINDS, OLD_SOURCES)
    op.drop_column("field_changes", "automation_ref")
