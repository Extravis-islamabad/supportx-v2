"""A problem's analysis and known error (WP-044b s1, s3; REQ-PRB-030, -034..-042; D-140 Q7).

- work_items.root_cause and symptoms: sanitised rich text, problems only (the service refuses
  them on other types). The root cause is read only by holders of problems.view_root_cause and
  is not part of the search text (SEARCH_VECTOR names subject, description and custom text only).
- work_items.workaround: sanitised rich text, problems only. Incident technicians see it
  (D-140 Q7), so it is what suggestions on incidents show.
- work_items.known_error_at / known_error_retired_at: when the problem was marked a known error,
  and when that was retired (a permanent fix). A retirement needs a marking first.

Expand only, no data step. The downgrade refuses while any tenant has a value in these columns
(rule 5h: checked per tenant with app.tenant_id set, as work_items forces RLS). Otherwise it
drops them.

Revision ID: 0078
Revises: 0089
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT_COLUMNS = ("root_cause", "symptoms", "workaround")
TIME_COLUMNS = ("known_error_at", "known_error_retired_at")
RETIRED_CHECK = "ck_work_items_known_error_retired_after"

_REFUSE_IF_ANY_VALUE = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM work_items
            WHERE root_cause IS NOT NULL OR symptoms IS NOT NULL OR workaround IS NOT NULL
               OR known_error_at IS NOT NULL OR known_error_retired_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has problem analysis (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    """The text and time columns, and the retirement's order."""
    for name in TEXT_COLUMNS:
        op.add_column("work_items", sa.Column(name, sa.Text(), nullable=True))
    for name in TIME_COLUMNS:
        op.add_column("work_items", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f(RETIRED_CHECK),
        "work_items",
        "known_error_retired_at IS NULL OR "
        "(known_error_at IS NOT NULL AND known_error_retired_at >= known_error_at)",
    )


def downgrade() -> None:
    """Drop them, only while no tenant has a value in them."""
    op.execute(_REFUSE_IF_ANY_VALUE)
    op.drop_constraint(op.f(RETIRED_CHECK), "work_items", type_="check")
    for name in reversed((*TEXT_COLUMNS, *TIME_COLUMNS)):
        op.drop_column("work_items", name)
