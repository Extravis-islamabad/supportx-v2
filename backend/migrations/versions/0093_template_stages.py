"""Templates choose a staged record's path and rules per stage (WP-058a s2; REQ-REL-003, -011..013).

Type-generic engine columns (ADR-041; releases now, changes later), number from the coordinator.
Expand only, no data step: unstaged types (incidents, service requests) keep NULL everywhere, and
staged types are seeded per tenant on first use.

- `work_item_templates.stage_path`: the path a record from this template takes (REQ-REL-011:
  which stages it goes through). Same-tenant, same-type key to `work_item_stage_paths`.
- `work_item_templates.stage_rules` (JSONB object): per stage, per field, whether it is shown,
  required to leave the stage, or read-only while the record is in it (REQ-REL-013). The service
  checks it against the type's stages and fields before saving.
- `work_item_reasons.attributes` (JSONB object): a pick-list value's own settings, such as a
  release type's default template and default risk (REQ-REL-003).

The downgrade drops the three columns (the stage rules and attributes go with them).

Revision ID: 0093
Revises: 0097
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0093"
down_revision: str | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEMPLATES = "work_item_templates"
PATH_FK = "fk_work_item_templates_stage_path"


def upgrade() -> None:
    """The template's path and stage rules, and pick-list value attributes."""
    op.add_column(TEMPLATES, sa.Column("stage_path", sa.String(40), nullable=True))
    op.add_column(TEMPLATES, sa.Column("stage_rules", postgresql.JSONB(), nullable=True))
    op.create_foreign_key(
        PATH_FK,
        TEMPLATES,
        "work_item_stage_paths",
        ["tenant_id", "type", "stage_path"],
        ["tenant_id", "type", "code"],
    )
    op.create_check_constraint(
        op.f("ck_work_item_templates_stage_rules_object"),
        TEMPLATES,
        "stage_rules IS NULL OR jsonb_typeof(stage_rules) = 'object'",
    )
    op.add_column("work_item_reasons", sa.Column("attributes", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_item_reasons_attributes_object"),
        "work_item_reasons",
        "attributes IS NULL OR jsonb_typeof(attributes) = 'object'",
    )


def downgrade() -> None:
    """Drop them again."""
    op.drop_constraint(
        op.f("ck_work_item_reasons_attributes_object"), "work_item_reasons", type_="check"
    )
    op.drop_column("work_item_reasons", "attributes")
    op.drop_constraint(op.f("ck_work_item_templates_stage_rules_object"), TEMPLATES, type_="check")
    op.drop_constraint(PATH_FK, TEMPLATES, type_="foreignkey")
    op.drop_column(TEMPLATES, "stage_rules")
    op.drop_column(TEMPLATES, "stage_path")
