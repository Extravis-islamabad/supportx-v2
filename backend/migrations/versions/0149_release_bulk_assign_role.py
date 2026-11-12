"""Release bulk role assignment and Take's role (WP-058b S5a; REQ-REL-057), 0149.

Expand only, no data step:
- bulk action `assign_role`, setting a release role's holders (release manager, release
  engineer ...) on every chosen release, each through the single assign's own checks;
- `work_item_role_defs.taken_by_take`: the role Take makes you, at most one per type (a partial
  unique index). None marked means the type's default (a release's engineer), so no tenant's
  rows need writing.

The downgrade refuses while any tenant has an `assign_role` bulk job or a marked role (rule 5h);
otherwise it drops both.

Revision ID: 0149
Revises: 0148
Created: 2026-11-12
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0149"
down_revision: str | None = "0148"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BULK_CHECK = "ck_work_item_bulk_jobs_action_code"
TABLE = "work_item_bulk_jobs"
ROLE_DEFS = "work_item_role_defs"
TAKE_INDEX = "uq_work_item_role_defs_take"
ADDED = ("assign_role",)
GUARD = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM work_item_bulk_jobs WHERE action = 'assign_role')
           OR EXISTS (SELECT 1 FROM work_item_role_defs WHERE taken_by_take)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has role bulk jobs or a Take role'
                ' (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now() -> list[str]:
    """The codes the check allows now, in their order (the 0092/0141 pattern)."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": BULK_CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _replace(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(BULK_CHECK), TABLE, type_="check")
    op.create_check_constraint(op.f(BULK_CHECK), TABLE, _in("action", codes))


def upgrade() -> None:
    """The bulk action `assign_role`, and the role Take makes you."""
    now = _codes_now()
    _replace([*now, *(c for c in ADDED if c not in now)])
    op.add_column(
        ROLE_DEFS,
        sa.Column("taken_by_take", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        TAKE_INDEX,
        ROLE_DEFS,
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("taken_by_take"),
    )


def downgrade() -> None:
    """Back to before (stops while any tenant has such a job)."""
    op.execute(GUARD)
    op.drop_index(TAKE_INDEX, table_name=ROLE_DEFS)
    op.drop_column(ROLE_DEFS, "taken_by_take")
    _replace([c for c in _codes_now() if c not in ADDED])
