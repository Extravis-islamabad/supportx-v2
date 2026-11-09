"""Changes carry custom fields (WP-045a S1; REQ-CHG-006), number from the coordinator (0099-0103).

Expand only, no data step (no change exists before this build): `custom_fields.entity` also
accepts `change`. The check is widened from its live definition (only `change` is added, and
only it is removed on the way down), so lanes landing other codes in either order never drop
each other's (as 0092 does for releases).

The downgrade narrows the check back; while a tenant still has a change custom field the
narrowed check fails and the downgrade stops, keeping the data (rule 5h).

Revision ID: 0099
Revises: 0110
Created: 2026-11-09
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0099"
down_revision: str | None = "0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, COLUMN, CHECK = "custom_fields", "entity", "ck_custom_fields_entity_code"
ADDED = ("change",)


def _codes_now() -> list[str]:
    """The codes the check allows now, in their order."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CHECK), TABLE, f"{COLUMN} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"
    )


def upgrade() -> None:
    """`change` joins the entities with custom fields."""
    now = _codes_now()
    _recheck([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Back to the check before changes (stops while change custom fields exist)."""
    _recheck([c for c in _codes_now() if c not in ADDED])
