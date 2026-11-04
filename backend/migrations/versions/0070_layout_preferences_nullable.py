"""Navigation layout and form density follow the default until a person chooses (WP-042).

Haider's rule (D-124): a changed default never overwrites a user's stored preference. The two
columns become nullable without a server default. NULL means "not chosen", and the default is
applied when read (side bar, comfortable forms), as for the other preferences (0067).

Expand only: no data step. Values already stored stay as they are (they may be real choices).
The downgrade fills the NULLs with today's defaults, once per tenant (FORCE RLS, D-113), and
restores NOT NULL and the server defaults.

Revision ID: 0070
Revises: 0068
Created: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0070"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULTS = {"nav_layout": "side", "form_density": "comfortable"}

_FILL = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE users SET nav_layout = coalesce(nav_layout, 'side'),
                         form_density = coalesce(form_density, 'comfortable')
         WHERE tenant_id = t AND (nav_layout IS NULL OR form_density IS NULL);
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    for column in _DEFAULTS:
        op.alter_column("users", column, nullable=True, server_default=None)


def downgrade() -> None:
    op.execute(_FILL)
    for column, default in _DEFAULTS.items():
        op.alter_column("users", column, nullable=False, server_default=default)
