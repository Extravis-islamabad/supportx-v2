"""Changes in a release (WP-058b S1; REQ-REL-033), number 0138.

Expand only, no data step: `work_item_links.kind` also accepts `in_release` (a change -> the
release it is part of). "At most one open release per change" is the service's rule, checked
under a lock (openness lives on the release, not on the link); the existing (tenant_id,
target_id) index serves a release's list of changes. The check is widened from its live
definition and only this code is removed on the way down (as 0104 and 0115 do), so lanes adding
kinds in either order keep each other's.

The downgrade narrows the check back; while an `in_release` link exists the narrowed check fails
and the downgrade stops, keeping the data (rule 5h).

Revision ID: 0138
Revises: 0137
Created: 2026-11-11
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0138"
down_revision: str | None = "0137"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, CHECK = "work_item_links", "ck_work_item_links_kind_code"
ADDED = ("in_release",)


def _codes_now() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(op.f(CHECK), TABLE, f"kind IN ({listed})")


def upgrade() -> None:
    """`in_release` joins the link kinds."""
    now = _codes_now()
    _recheck([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Back to the kinds before (stops while an in_release link exists)."""
    _recheck([c for c in _codes_now() if c not in ADDED])
