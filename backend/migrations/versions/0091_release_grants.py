"""Saved roles keep their release access (WP-058a; lane B's condition, 2026-11-05).

releases.view and releases.manage were identity's reserved keys, which the role editor offered.
Releases now use the engine's actions (releases.view, create, edit, assign, cancel, reopen ...).
A custom role holding releases.manage at scope S gets create (scope all: create has no other),
edit, assign, cancel and reopen at S; releases.view stays as it is. manage never becomes delete
(delete stays with the admin roles). Per tenant with app.tenant_id set (role_permissions forces
RLS; see 0023, 0036, 0077).

The downgrade folds them back: a role with releases.edit at S gets releases.manage at S, and the
engine's release keys other than view are removed.

Revision ID: 0091
Revises: 0090
Created: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PER_TENANT = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        STATEMENTS
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""

_SPLIT = """
        INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
        SELECT rp.tenant_id, rp.role_id, p.permission, COALESCE(p.scope, rp.scope), rp.condition
        FROM role_permissions rp
        CROSS JOIN (
            VALUES ('releases.create', 'all'), ('releases.edit', NULL),
                ('releases.assign', NULL), ('releases.cancel', NULL), ('releases.reopen', NULL)
        ) AS p(permission, scope)
        WHERE rp.permission = 'releases.manage'
        ON CONFLICT DO NOTHING;
        DELETE FROM role_permissions WHERE permission = 'releases.manage';
"""

_JOIN = """
        INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
        SELECT tenant_id, role_id, 'releases.manage', scope, condition
        FROM role_permissions WHERE permission = 'releases.edit'
        ON CONFLICT DO NOTHING;
        DELETE FROM role_permissions WHERE permission LIKE 'releases.%'
            AND permission NOT IN ('releases.view', 'releases.manage');
"""


def upgrade() -> None:
    """releases.manage(S) → create, edit, assign, cancel, reopen."""
    op.execute(_PER_TENANT.replace("STATEMENTS", _SPLIT))


def downgrade() -> None:
    """releases.edit(S) → releases.manage(S); the engine's other release keys removed."""
    op.execute(_PER_TENANT.replace("STATEMENTS", _JOIN))
