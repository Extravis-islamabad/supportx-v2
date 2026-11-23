"""Copying a record (WP-046a S5c; REQ-INC-033), 0156.

Expand only, no data step:
- `work_item_type_settings.copy_limit`: how many copies one request may make (1 to 100, 20 by
  default; AC3);
- `files.source` may be `copy`: a record's files copied onto its copies (lane B's copy rules),
  each new file encrypted under its own ID and pointing at its original through `copied_from`.

The downgrade refuses while any tenant has a copied file or a changed copy limit (rule 5h): the
old rule cannot hold the source, and relabelling copies as uploads would misstate where they
came from.

Revision ID: 0156
Revises: 0155 (re-pointed from 0153 at its queue turn)
Created: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0156"
down_revision: str | None = "0155"  # re-pointed from 0153 at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTINGS = "work_item_type_settings"
SOURCES_BEFORE = "source IN ('ui', 'api', 'email', 'portal', 'knowledge')"
SOURCES_AFTER = "source IN ('ui', 'api', 'email', 'portal', 'knowledge', 'copy')"

# files and the settings force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM files WHERE source = 'copy')
           OR EXISTS (SELECT 1 FROM {SETTINGS} WHERE copy_limit <> 20)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has copied files or a copy limit (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def upgrade() -> None:
    """Add the copy limit and allow the `copy` file source."""
    op.add_column(
        SETTINGS, sa.Column("copy_limit", sa.Integer(), server_default="20", nullable=False)
    )
    op.create_check_constraint(
        op.f(f"ck_{SETTINGS}_copy_limit_range"), SETTINGS, "copy_limit BETWEEN 1 AND 100"
    )
    op.drop_constraint(op.f("ck_files_source"), "files", type_="check")
    op.create_check_constraint(op.f("ck_files_source"), "files", SOURCES_AFTER)


def downgrade() -> None:
    """Back to before (stops while any tenant has copied files or a changed copy limit)."""
    op.execute(GUARD)
    op.drop_constraint(op.f("ck_files_source"), "files", type_="check")
    op.create_check_constraint(op.f("ck_files_source"), "files", SOURCES_BEFORE)
    op.drop_constraint(op.f(f"ck_{SETTINGS}_copy_limit_range"), SETTINGS, type_="check")
    op.drop_column(SETTINGS, "copy_limit")
