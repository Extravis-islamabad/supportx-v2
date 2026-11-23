"""Template form layouts and form rules (WP-046a S5b; REQ-INC-036, REQ-INC-037), 0155.

Expand only, no data step, on `work_item_templates`:
- `layout`: the designer's sections for the technician form and, optionally, the requester
  form (`{"technician": ..., "requester": ... | null}`); NULL keeps the classic single list,
  so no tenant's rows need writing.
- `form_rules`: the template's form rules (show, hide, require, lock, set on a condition),
  checked by the browser and enforced by the server on every save; empty by default.

The downgrade refuses while any tenant has a layout or a rule (rule 5h); otherwise it drops both.

Revision ID: 0155
Revises: 0154 (re-pointed from 0150 at its queue turn)
Created: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0155"
down_revision: str | None = "0154"  # main's head at its queue turn (after #463's 0154)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_templates"
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM {TABLE}
            WHERE tenant_id = t AND (layout IS NOT NULL OR jsonb_array_length(form_rules) > 0)
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has form layouts or form rules'
                ' (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def upgrade() -> None:
    """The two columns, each with a shape check."""
    op.add_column(TABLE, sa.Column("layout", postgresql.JSONB(astext_type=sa.Text())))
    op.add_column(
        TABLE,
        sa.Column(
            "form_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_layout_object"),
        TABLE,
        "layout IS NULL OR jsonb_typeof(layout) = 'object'",
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_form_rules_array"),
        TABLE,
        "jsonb_typeof(form_rules) = 'array' AND jsonb_array_length(form_rules) <= 50",
    )


def downgrade() -> None:
    """Drop both (stops while anything uses them)."""
    op.execute(GUARD)
    op.drop_constraint(op.f(f"ck_{TABLE}_form_rules_array"), TABLE, type_="check")
    op.drop_constraint(op.f(f"ck_{TABLE}_layout_object"), TABLE, type_="check")
    op.drop_column(TABLE, "form_rules")
    op.drop_column(TABLE, "layout")
