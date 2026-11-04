"""Digits preference, and a one-time reset of stored layouts (WP-042; D-135, D-136).

- Expand: `users.digits`, nullable (NULL: Western digits 0-9, the default in every language,
  D-135), with a check: `western` or `arabic_indic`.
- Data step, once per tenant (users has FORCE RLS, D-113): stored navigation layout and form
  density go back to "not chosen" (NULL), so the current defaults apply to everyone (D-136).
  The product owner approved this one reset because only dev, QA and demo accounts exist yet;
  after go-live a changed default never overwrites a stored preference.

The downgrade drops `digits`. The reset is not undone: the old values were the old server
defaults, not choices, and NULL is valid under 0071.

Revision ID: 0072
Revises: 0071
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESET = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE users SET nav_layout = NULL, form_density = NULL
         WHERE tenant_id = t AND (nav_layout IS NOT NULL OR form_density IS NOT NULL);
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    op.add_column("users", sa.Column("digits", sa.String(16), nullable=True))
    op.create_check_constraint(
        "digits_code", "users", "digits IS NULL OR digits IN ('western', 'arabic_indic')"
    )
    op.execute(_RESET)


def downgrade() -> None:
    op.drop_column("users", "digits")  # its check goes with it
