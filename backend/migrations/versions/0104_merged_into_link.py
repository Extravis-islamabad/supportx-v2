"""A link kind for merged problems (WP-044b s2; REQ-PRB-046).

work_item_links may be `merged_into`: the merged problem (source) points to the one it was
merged into (target), so the record says where it went and an undo knows the pair. The status
moves are the system actions `merge` and `undo_merge` (never transitions; widened in the
transitions' action check like 0089's guided actions). Bulk jobs may `unlink_problem`
(incidents no longer caused by their problem).

Expand only. Both checks are widened from their live definitions, and narrowed by removing only
these codes. Lane C's 0098 widens the link kinds too, so neither drops the other's codes in
either merge order. The downgrade fails while a `merged_into` link exists: the narrowed check
would not hold, so the data stays (rule 5h).

Revision ID: 0104
Revises: 0078
Created: 2026-11-05
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0104"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LINK_CHECK = "ck_work_item_links_kind_code"
ACTION_CHECK = "ck_work_item_transitions_action_code"
BULK_CHECK = "ck_work_item_bulk_jobs_action_code"
WIDENED = {
    (LINK_CHECK, "work_item_links", "kind"): ("merged_into",),
    (ACTION_CHECK, "work_item_transitions", "action"): ("merge", "undo_merge"),
    (BULK_CHECK, "work_item_bulk_jobs", "action"): ("unlink_problem",),
}


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now(name: str) -> list[str]:
    """The codes a `col IN (...)` check allows now, in their order (lane C's 0092 pattern)."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _replace(name: str, table: str, column: str, codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, _in(column, codes))


def upgrade() -> None:
    """Add only these codes to the live checks (other lanes' codes stay)."""
    for (name, table, column), codes in WIDENED.items():
        now = _codes_now(name)
        _replace(name, table, column, [*now, *(c for c in codes if c not in now)])


def downgrade() -> None:
    """Remove only these codes (fails while a row uses one, so nothing is lost)."""
    for (name, table, column), codes in WIDENED.items():
        _replace(name, table, column, [c for c in _codes_now(name) if c not in codes])
