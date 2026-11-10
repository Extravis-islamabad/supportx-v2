"""No role assigns outside a record's group any more (D-154a, Haider 2026-11-10).

Haider: an assignee outside the record's group is never allowed on its own. The record moves to
a group the person is in, in the same request. That holds for everyone and for all work-item
types, so the engine's `<type>.assign_outside_group` action is gone. This drops every role grant
of it, built-in and custom roles alike. Per tenant with app.tenant_id set (role_permissions
forces RLS; see 0023, 0077, 0091); each tenant's count is logged as a NOTICE.

The downgrade is schema-only: nothing in the schema changed, and the dropped grants are not
restored (there are no real customers yet; the coordinator agreed, 2026-11-10). A role that
needs the old power cannot get it back, as the permission no longer exists in the catalogue.

Revision ID: 0125
Revises: 0124
Created: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0125"
down_revision: str | None = "0124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP = """
DO $$
DECLARE
    t uuid;
    dropped integer;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        DELETE FROM role_permissions WHERE permission LIKE '%.assign_outside_group';
        GET DIAGNOSTICS dropped = ROW_COUNT;
        IF dropped > 0 THEN
            RAISE NOTICE '0125: tenant % lost % assign_outside_group grant(s)', t, dropped;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    """Every role's `<type>.assign_outside_group` grant is dropped, counted per tenant."""
    op.execute(_DROP)


def downgrade() -> None:
    """Schema-only: the grants stay dropped (see the module docstring)."""
