"""Saved roles keep their problem access (WP-044a s1; lane B's condition, 2026-11-05).

problems.view and problems.manage were identity's reserved keys; problems now use the engine's
actions (problems.view, create, edit, assign, close ...). A custom role holding
problems.manage at scope S gets create (scope all: create has no other), edit, assign and close
at S; problems.view stays as it is. manage never becomes delete (delete stays with the admin
roles). Per tenant with app.tenant_id set (role_permissions forces RLS; see 0023, 0036).

The downgrade folds them back: a role with problems.edit at S gets problems.manage at S, and
the engine's problem keys other than view are removed.

Revision ID: 0077
Revises: 0076
Created: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
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
            VALUES ('problems.create', 'all'), ('problems.edit', NULL),
                ('problems.assign', NULL), ('problems.close', NULL)
        ) AS p(permission, scope)
        WHERE rp.permission = 'problems.manage'
        ON CONFLICT DO NOTHING;
        DELETE FROM role_permissions WHERE permission = 'problems.manage';
"""

_JOIN = """
        INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
        SELECT tenant_id, role_id, 'problems.manage', scope, condition
        FROM role_permissions WHERE permission = 'problems.edit'
        ON CONFLICT DO NOTHING;
        DELETE FROM role_permissions WHERE permission LIKE 'problems.%'
            AND permission NOT IN ('problems.view', 'problems.manage');
"""


def upgrade() -> None:
    """problems.manage(S) → create, edit, assign, close."""
    op.execute(_PER_TENANT.replace("STATEMENTS", _SPLIT))


def downgrade() -> None:
    """problems.edit(S) → problems.manage(S); the engine's other problem keys removed."""
    op.execute(_PER_TENANT.replace("STATEMENTS", _JOIN))
