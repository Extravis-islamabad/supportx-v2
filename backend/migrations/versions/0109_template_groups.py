"""Templates limited to groups (WP-044c S1; REQ-PRB-021).

work_item_templates.limited_group_ids: when not empty, only members of those support groups are
offered the template when creating a record (admins who manage the type's settings see all). A
record already made from it stays visible to anyone with access to the record (AC2): the column
narrows what is offered, never what is seen.

Expand only: a new column with an empty default, so every existing template stays open to all.
At most 50 groups, as for shared views. The downgrade refuses, per tenant with app.tenant_id set
(RLS), while any template is limited: dropping the column would lose that choice (rule 5h).

Revision ID: 0109
Revises: 0105
Created: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0109"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_templates"
COLUMN = "limited_group_ids"
CHECK = "limited_group_ids_count"


def upgrade() -> None:
    """The column, empty for every template (open to all), and its cap."""
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
    )
    op.create_check_constraint(op.f(f"ck_{TABLE}_{CHECK}"), TABLE, f"cardinality({COLUMN}) <= 50")


_REFUSE_IF_LIMITED = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM work_item_templates WHERE cardinality(limited_group_ids) > 0) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has templates limited to groups'
                ' (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drop the column while no tenant limits a template; otherwise refuses."""
    op.execute(_REFUSE_IF_LIMITED)
    op.drop_constraint(op.f(f"ck_{TABLE}_{CHECK}"), TABLE, type_="check")
    op.drop_column(TABLE, COLUMN)
