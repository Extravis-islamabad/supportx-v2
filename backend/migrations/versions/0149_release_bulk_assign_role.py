"""Release bulk role assignment (WP-058b S5a; REQ-REL-057), 0149.

Expand only, no data step: bulk action `assign_role`, setting a release role's holders (release
manager, release engineer ...) on every chosen release, each through the single assign's own
checks.

The downgrade refuses while any tenant has an `assign_role` bulk job (rule 5h); otherwise it
narrows the check again.

Revision ID: 0149
Revises: 0146
Created: 2026-11-12
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0149"
down_revision: str | None = "0146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BULK_CHECK = "ck_work_item_bulk_jobs_action_code"
TABLE = "work_item_bulk_jobs"
ADDED = ("assign_role",)
GUARD = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM work_item_bulk_jobs WHERE action = 'assign_role') THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has release role bulk jobs (rule 5h)', t;
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
    """The bulk action `assign_role`."""
    now = _codes_now()
    _replace([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Back to before (stops while any tenant has such a job)."""
    op.execute(GUARD)
    _replace([c for c in _codes_now() if c not in ADDED])
