"""A service request's own fields on the work item (WP-030 s1; REQ-SR-001, -003, -005).

Expand only, no data step (no service request exists yet):
- work_items.catalog_item_id: the item it was raised from (same-tenant key to catalog_items);
  the service refuses a service request without one (REQ-SR-001 AC2).
- work_items.answers: the item form's answers (JSONB object; checked against the item).
- work_items.approval_status: not_needed | pending | approved | rejected | withdrawn (NULL on
  incidents).
- custom fields may be defined for service requests (custom_fields.entity accepts
  `service_request`).
- priority_source also accepts `catalog_item` (REQ-SR-005 AC1: the item set it), and widens
  from 10 to 20 characters to hold it.

The downgrade drops the three columns and the extra priority source (it refuses while a record
still has it, keeping data intact).

Revision ID: 0063
Revises: 0062
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVAL = ("not_needed", "pending", "approved", "rejected", "withdrawn")
SOURCES_BEFORE = ("matrix", "manual", "default", "rule")
SOURCES_AFTER = (*SOURCES_BEFORE, "catalog_item")
SOURCE_CHECK = "ck_work_items_priority_source_code"
ENTITY_CHECK = "ck_custom_fields_entity_code"


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def upgrade() -> None:
    """Add the fields and the item as a priority source."""
    op.add_column("work_items", sa.Column("catalog_item_id", sa.Uuid(), nullable=True))
    op.add_column(
        "work_items",
        sa.Column("answers", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.add_column("work_items", sa.Column("approval_status", sa.String(length=20), nullable=True))
    op.create_foreign_key(
        "fk_work_items_catalog_item_id_catalog_items",
        "work_items",
        "catalog_items",
        ["tenant_id", "catalog_item_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_work_items_approval_status_code"),
        "work_items",
        "approval_status IS NULL OR " + _in("approval_status", APPROVAL),
    )
    op.create_check_constraint(
        op.f("ck_work_items_answers_object"), "work_items", "jsonb_typeof(answers) = 'object'"
    )
    op.create_index(
        "ix_wi_tenant_catalog_item",
        "work_items",
        ["tenant_id", "catalog_item_id", "id"],
        postgresql_where=sa.text("catalog_item_id IS NOT NULL"),
    )
    op.drop_constraint(op.f(SOURCE_CHECK), "work_items", type_="check")
    op.alter_column(
        "work_items",
        "priority_source",
        type_=sa.String(length=20),
        existing_type=sa.String(length=10),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f(SOURCE_CHECK), "work_items", _in("priority_source", SOURCES_AFTER)
    )
    op.drop_constraint(op.f(ENTITY_CHECK), "custom_fields", type_="check")
    op.create_check_constraint(
        op.f(ENTITY_CHECK), "custom_fields", _in("entity", ("incident", "service_request"))
    )


def downgrade() -> None:
    """Back to incidents' fields only."""
    op.drop_constraint(op.f(ENTITY_CHECK), "custom_fields", type_="check")
    op.create_check_constraint(op.f(ENTITY_CHECK), "custom_fields", _in("entity", ("incident",)))
    op.drop_constraint(op.f(SOURCE_CHECK), "work_items", type_="check")
    op.create_check_constraint(
        op.f(SOURCE_CHECK), "work_items", _in("priority_source", SOURCES_BEFORE)
    )
    op.alter_column(
        "work_items",
        "priority_source",
        type_=sa.String(length=10),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.drop_index("ix_wi_tenant_catalog_item", table_name="work_items")
    op.drop_constraint(op.f("ck_work_items_answers_object"), "work_items", type_="check")
    op.drop_constraint(op.f("ck_work_items_approval_status_code"), "work_items", type_="check")
    op.drop_constraint(
        "fk_work_items_catalog_item_id_catalog_items", "work_items", type_="foreignkey"
    )
    op.drop_column("work_items", "approval_status")
    op.drop_column("work_items", "answers")
    op.drop_column("work_items", "catalog_item_id")
