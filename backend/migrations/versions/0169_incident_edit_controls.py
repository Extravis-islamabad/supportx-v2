"""Incident edit controls and first-contact resolution (WP-046b S1), 0169.

Expand only, no data step:
- `work_item_type_settings.closed_edit_locked`: the tenant locks closed records fully; no one
  edits their fields, holders of `<type>.edit_closed` included (REQ-INC-101; lane B).
- `work_item_type_settings.edit_reason_fields`: the fields whose change needs a reason
  (REQ-INC-124); none by default.
- `work_item_type_settings.first_contact_minutes`: how soon after creation a record its creator
  resolves, never reassigned, is suggested as resolved at first contact (REQ-INC-102).
- `work_items.first_contact_resolution`: the flag the technician confirms or changes; null until
  the record is resolved.

Expand/contract (§14.3): new columns with defaults, read only by the new code.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0169"
down_revision: str | None = "0167"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTINGS = "work_item_type_settings"
ITEMS = "work_items"

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
               SELECT 1 FROM {SETTINGS}
               WHERE closed_edit_locked OR cardinality(edit_reason_fields) > 0
           )
           OR EXISTS (SELECT 1 FROM {ITEMS} WHERE first_contact_resolution IS NOT NULL)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses incident edit controls (rule 5h)', t;
        END IF;
    END LOOP;
END $$;
"""  # noqa: S608 - fixed table names, no input


def upgrade() -> None:
    """Add the settings and the flag."""
    op.add_column(
        SETTINGS,
        sa.Column("closed_edit_locked", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        SETTINGS,
        sa.Column(
            "edit_reason_fields",
            postgresql.ARRAY(sa.String(80)),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        SETTINGS,
        sa.Column("first_contact_minutes", sa.Integer(), server_default="30", nullable=False),
    )
    op.create_check_constraint(
        "ck_work_item_type_settings_first_contact_minutes",
        SETTINGS,
        "first_contact_minutes BETWEEN 0 AND 1440",
    )
    op.add_column(ITEMS, sa.Column("first_contact_resolution", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Back to before (stops while any tenant uses them)."""
    op.execute(GUARD)
    op.drop_column(ITEMS, "first_contact_resolution")
    op.drop_constraint("ck_work_item_type_settings_first_contact_minutes", SETTINGS)
    op.drop_column(SETTINGS, "first_contact_minutes")
    op.drop_column(SETTINGS, "edit_reason_fields")
    op.drop_column(SETTINGS, "closed_edit_locked")
