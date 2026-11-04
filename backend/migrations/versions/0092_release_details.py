"""A release's own fields (WP-058a s1; REQ-REL-002..005), number from the coordinator.

Expand only, no data step (no release exists before this build):
- `work_item_release_details` (RLS): one row per release, keyed (tenant_id, work_item_id), with
  its type and reason (codes of the tenant's `release_type` and `release_reason` pick lists),
  risk (low, medium, high), version and build reference (searchable), release notes (sanitised
  rich text), scheduled and actual start and end (an end never before its start), and the
  release manager and engineer. It has no version of its own: every edit goes through the
  release's work item, whose `version` it bumps (one If-Match for the whole record).
- `work_item_reasons.list` also accepts `release_type` and `release_reason` (REQ-REL-003:
  release types of their own, never shared with changes). Their seeds are made per tenant on
  first use.
- `custom_fields.entity` also accepts `release` (REQ-REL-006; the closing rules read a type's
  custom fields).

Both checks are widened from their live definition (only this migration's codes are added, and
only they are removed on the way down), so lanes landing other codes in either order never drop
each other's (lane A's problem lists, 0076/0089).

The downgrade drops the table and narrows both checks back; while a tenant still has release
types, reasons or release custom fields the narrowed check fails and the downgrade stops,
keeping the data.

Revision ID: 0092
Revises: 0091
Created: 2026-11-05
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, check name, the codes this migration adds)
CHECKS = (
    (
        "work_item_reasons",
        "list",
        "ck_work_item_reasons_list_code",
        ("release_type", "release_reason"),
    ),
    ("custom_fields", "entity", "ck_custom_fields_entity_code", ("release",)),
)
TABLE = "work_item_release_details"


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now(name: str) -> list[str]:
    """The codes a `col IN (...)` check allows now, in their order."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(table: str, column: str, name: str, codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, _in(column, codes))


def _person_fk(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        ["users.tenant_id", "users.id"],
        name=op.f(f"fk_{TABLE}_{column}"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    """The details table and the two release lists."""
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("release_type", sa.String(40), nullable=True),
        sa.Column("risk", sa.String(10), nullable=True),
        sa.Column("release_version", sa.String(60), nullable=True),
        sa.Column("build_ref", sa.String(200), nullable=True),
        sa.Column("release_reason", sa.String(40), nullable=True),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_manager_id", sa.Uuid(), nullable=True),
        sa.Column("release_engineer_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "risk IS NULL OR risk IN ('low', 'medium', 'high')", name=op.f(f"ck_{TABLE}_risk_code")
        ),
        sa.CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end >= scheduled_start",
            name=op.f(f"ck_{TABLE}_scheduled_order"),
        ),
        sa.CheckConstraint(
            "actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start",
            name=op.f(f"ck_{TABLE}_actual_order"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"],
            ["work_items.id"],
            name=op.f(f"fk_{TABLE}_work_item_id_work_items"),
            ondelete="CASCADE",
        ),
        _person_fk("release_manager_id"),
        _person_fk("release_engineer_id"),
        sa.PrimaryKeyConstraint("tenant_id", "work_item_id", name=op.f(f"pk_{TABLE}")),
    )
    # REQ-REL-005: lists show and filter by version; the unique-versions setting checks it.
    op.create_index(
        "ix_work_item_release_details_tenant_version",
        TABLE,
        ["tenant_id", "release_version"],
        postgresql_where=sa.text("release_version IS NOT NULL"),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))

    for table, column, name, added in CHECKS:
        now = _codes_now(name)
        _recheck(table, column, name, [*now, *(c for c in added if c not in now)])


def downgrade() -> None:
    """Back to the checks before releases (stops while release values exist)."""
    for table, column, name, added in CHECKS:
        _recheck(table, column, name, [c for c in _codes_now(name) if c not in added])
    op.drop_index("ix_work_item_release_details_tenant_version", table_name=TABLE)
    op.drop_table(TABLE)
