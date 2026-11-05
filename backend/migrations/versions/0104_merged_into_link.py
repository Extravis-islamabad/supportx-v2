"""A link kind for merged problems (WP-044b s2; REQ-PRB-046).

work_item_links may be `merged_into`: the merged problem (source) points to the one it was
merged into (target), so the record says where it went and an undo knows the pair.

Expand only. The kind check is widened from its live definition, and narrowed by removing only
this code. Lane C's 0098 widens the same check, so neither drops the other's codes in either
merge order. The downgrade fails while a `merged_into` link exists: the narrowed check would
not hold, so the data stays (rule 5h).

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
CODES = ("merged_into",)


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now(name: str) -> list[str]:
    """The codes a `col IN (...)` check allows now, in their order (lane C's 0092 pattern)."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _replace(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(LINK_CHECK), "work_item_links", type_="check")
    op.create_check_constraint(op.f(LINK_CHECK), "work_item_links", _in("kind", codes))


def upgrade() -> None:
    """Add `merged_into` to the live kind check (other lanes' codes stay)."""
    now = _codes_now(LINK_CHECK)
    _replace([*now, *(c for c in CODES if c not in now)])


def downgrade() -> None:
    """Remove only `merged_into` (fails while such a link exists, so nothing is lost)."""
    _replace([c for c in _codes_now(LINK_CHECK) if c not in CODES])
