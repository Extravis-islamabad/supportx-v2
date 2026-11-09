"""Assets carry custom fields (WP-049a session 2; REQ-AST-004): `asset` joins custom_fields.entity.

The check is read live and only `asset` is added (and on the way down only `asset` removed), so
another lane's codes (release, problem, ...) survive whatever order the migrations land in; the
helpers are lane C's from 0092.

The downgrade refuses while any tenant has an asset custom field (rule 5h): removing the code
would otherwise drop those fields' definitions or fail half-way.

Revision ID: 0083
Revises: 0082
Created: 2026-11-05
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, COLUMN, NAME, ADDED = "custom_fields", "entity", "ck_custom_fields_entity_code", ("asset",)


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _codes_now(name: str) -> list[str]:
    """The codes a `col IN (...)` check allows now, in their order."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(table: str, column: str, name: str, codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, _in(column, codes))


def upgrade() -> None:
    now = _codes_now(NAME)
    _recheck(TABLE, COLUMN, NAME, [*now, *(c for c in ADDED if c not in now)])


# Each tenant's fields are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ASSET_FIELDS = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM custom_fields WHERE entity = 'asset') THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has asset custom fields (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    op.execute(_REFUSE_IF_ASSET_FIELDS)
    _recheck(TABLE, COLUMN, NAME, [c for c in _codes_now(NAME) if c not in ADDED])
