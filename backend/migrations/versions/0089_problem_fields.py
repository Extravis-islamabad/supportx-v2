"""A problem's own fields (WP-044a s2; REQ-PRB-005, -006).

- work_items.problem_type and root_cause_category: codes from the tenant's pick lists of the
  same names (seeded for problems: Appendix A), checked by the service like `level`.
- work_items.outage_started_at / outage_ended_at: the outage window; the end, when given, is
  not before the start.
- work_item_reasons may hold the two new lists.
- work_item_links may be `caused_by` (an incident caused by a problem, at most one per incident:
  a partial unique index); bulk jobs may `link_problem` (REQ-PRB-011, -012).

Expand only. The downgrade removes the columns and the two lists' values (per tenant: the
table forces RLS, see 0023).

Revision ID: 0089
Revises: 0077
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0089"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LISTS_BEFORE = ("pause", "third_party", "cancel", "reopen", "reassign", "level", "closure_code")
LISTS_AFTER = (*LISTS_BEFORE, "problem_type", "root_cause")
LIST_CHECK = "ck_work_item_reasons_list_code"
LINK_CHECK = "ck_work_item_links_kind_code"
LINKS_BEFORE = ("related", "follows")
BULK_CHECK = "ck_work_item_bulk_jobs_action_code"
BULK_BEFORE = ("edit", "assign", "take", "resolve", "close")
ONE_CAUSE = "uq_wil_tenant_one_cause"
OUTAGE_CHECK = "ck_work_items_outage_order"

_DROP_LISTS = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        DELETE FROM work_item_reasons WHERE list IN ('problem_type', 'root_cause');
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def upgrade() -> None:
    """The columns, their check and the wider list check."""
    op.add_column("work_items", sa.Column("problem_type", sa.String(length=40), nullable=True))
    op.add_column(
        "work_items", sa.Column("root_cause_category", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "work_items", sa.Column("outage_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "work_items", sa.Column("outage_ended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f(OUTAGE_CHECK),
        "work_items",
        "outage_ended_at IS NULL OR outage_started_at IS NULL"
        " OR outage_ended_at >= outage_started_at",
    )
    op.drop_constraint(op.f(LIST_CHECK), "work_item_reasons", type_="check")
    op.create_check_constraint(op.f(LIST_CHECK), "work_item_reasons", _in("list", LISTS_AFTER))
    op.drop_constraint(op.f(LINK_CHECK), "work_item_links", type_="check")
    op.create_check_constraint(
        op.f(LINK_CHECK), "work_item_links", _in("kind", (*LINKS_BEFORE, "caused_by"))
    )
    op.create_index(
        ONE_CAUSE,
        "work_item_links",
        ["tenant_id", "source_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'caused_by' AND deleted_at IS NULL"),
    )
    op.drop_constraint(op.f(BULK_CHECK), "work_item_bulk_jobs", type_="check")
    op.create_check_constraint(
        op.f(BULK_CHECK), "work_item_bulk_jobs", _in("action", (*BULK_BEFORE, "link_problem"))
    )


def downgrade() -> None:
    """Back to the lists and columns before problems' fields (a downgrade refuses while a
    caused_by link or a link_problem job exists: the checks would fail, keeping data intact)."""
    op.drop_constraint(op.f(BULK_CHECK), "work_item_bulk_jobs", type_="check")
    op.create_check_constraint(op.f(BULK_CHECK), "work_item_bulk_jobs", _in("action", BULK_BEFORE))
    op.drop_index(ONE_CAUSE, table_name="work_item_links")
    op.drop_constraint(op.f(LINK_CHECK), "work_item_links", type_="check")
    op.create_check_constraint(op.f(LINK_CHECK), "work_item_links", _in("kind", LINKS_BEFORE))
    op.execute(_DROP_LISTS)
    op.drop_constraint(op.f(LIST_CHECK), "work_item_reasons", type_="check")
    op.create_check_constraint(op.f(LIST_CHECK), "work_item_reasons", _in("list", LISTS_BEFORE))
    op.drop_constraint(op.f(OUTAGE_CHECK), "work_items", type_="check")
    for column in ("outage_ended_at", "outage_started_at", "root_cause_category", "problem_type"):
        op.drop_column("work_items", column)
