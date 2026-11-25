"""D-185 (product owner, 2026-11-24): moving an asset to the trash is its own right.

`assets.delete` now gates `DELETE /assets/{asset_id}` alone (assets.manage no longer stands in;
vendor support never holds it). So that nobody loses the delete they had, every role that holds
`assets.manage` gets `assets.delete` at the same scope and condition, built-in and custom alike.
Data only, per tenant with app.tenant_id set (role_permissions forces RLS; see 0023, 0125).

Each tenant's copies are logged as a NOTICE, and separately how many of them sit on roles held by
a service identity (a service account or a workflow's run-as identity), so an admin can review
automation that can now delete (the coordinator's ask).

The downgrade removes only the copies (an `assets.delete` grant on a role that still holds
`assets.manage`) and refuses while any other `assets.delete` grant exists: that one is a tenant's
own choice, never ours to drop (rule 5h).

Revision ID: 0202
Revises: 0203
Created: 2026-11-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0202"
down_revision: str | None = "0203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COPY = """
DO $$
DECLARE
    t uuid;
    copied integer;
    automation integer;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        WITH added AS (
            INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
            SELECT tenant_id, role_id, 'assets.delete', scope, condition
            FROM role_permissions
            WHERE permission = 'assets.manage'
            ON CONFLICT DO NOTHING
            RETURNING role_id
        )
        SELECT count(*),
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM user_roles ur JOIN users u ON u.id = ur.user_id
                   WHERE ur.role_id = added.role_id AND u.user_type = 'service'
               ))
        INTO copied, automation FROM added;
        IF copied > 0 THEN
            RAISE NOTICE '0202: tenant % gave assets.delete to % role(s), % held by automation',
                t, copied, automation;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""

_UNCOPY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM role_permissions d
            WHERE d.permission = 'assets.delete'
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions m
                  WHERE m.role_id = d.role_id AND m.permission = 'assets.manage'
              )
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % granted assets.delete on its own', t;
        END IF;
        DELETE FROM role_permissions WHERE permission = 'assets.delete';
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    """Every assets.manage holder also holds assets.delete (logged per tenant)."""
    op.execute(_COPY)


def downgrade() -> None:
    """Removes the copies; refuses while a tenant granted assets.delete on its own."""
    op.execute(_UNCOPY)
