"""The console menu moves to the side bar with labels (console UI pass, D-124).

- `users.nav_layout` defaults to `side` for new users (was `top`).
- Every existing user is moved to `side` once. The product owner approved this explicitly
  (2026-11-02, through the coordinator): before the pilot the only users are dev, QA and demo
  accounts, so this one-time change of a stored preference satisfies CLAUDE.md rule 5h. After
  go-live a changed default never overwrites a user's stored preference (D-124).

Reversible: the downgrade restores the `top` default and moves everyone on `side` back to
`top` (a user who had chosen `side` before also returns to `top`, which is acceptable for the
same dev data).

Revision ID: 0051
Revises: 0038 (re-pointed onto the head of main only if the merge queue rejects it)
Created: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0051"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# users has FORCE ROW LEVEL SECURITY: the data step runs once per tenant (D-113).
_MOVE = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE users SET nav_layout = '{to}' WHERE tenant_id = t AND nav_layout = '{source}';
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    op.alter_column("users", "nav_layout", server_default="side")
    op.execute(_MOVE.format(source="top", to="side"))


def downgrade() -> None:
    op.execute(_MOVE.format(source="side", to="top"))
    op.alter_column("users", "nav_layout", server_default="top")
