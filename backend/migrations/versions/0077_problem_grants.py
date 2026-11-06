"""Saved roles keep their problem access (WP-044a s1; lane B's condition, 2026-11-05).

problems.view and problems.manage were identity's reserved keys; problems now use the engine's
actions (problems.view, create, edit, assign, close ...). A custom role holding
problems.manage at scope S gets create (scope all: create has no other), edit, assign and close
at S; problems.view stays as it is. manage never becomes delete (delete stays with the admin
roles). Per tenant with app.tenant_id set (role_permissions forces RLS; see 0023, 0036).

The downgrade folds back only what problems.manage can represent without losing or widening a
grant (lane B's review, CLAUDE.md rule 5h; the same as lane C's 0091). A role holding exactly the
four keys the upgrade made (create at all; edit, assign and close at one scope S) gets
problems.manage at S. Any other problem key (delete, take, ...), a partial set, or the three at
different scopes or with different conditions stops the downgrade with an error and changes nothing.

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

_FOLDED = "('problems.edit', 'problems.assign', 'problems.close')"
_FOUR = "('problems.create', 'problems.edit', 'problems.assign', 'problems.close')"

_REFUSE = f"""
        IF EXISTS (
            SELECT 1 FROM role_permissions WHERE permission LIKE 'problems.%'
                AND permission NOT IN ('problems.view', 'problems.manage')
                AND permission NOT IN {_FOUR}
        ) THEN
            RAISE EXCEPTION 'a role holds a problem key problems.manage cannot represent: going'
                ' below 0077 would lose it';
        END IF;
        IF EXISTS (
            SELECT role_id FROM role_permissions WHERE permission IN {_FOUR}
            GROUP BY role_id
            HAVING count(*) <> 4
                OR count(DISTINCT scope) FILTER (WHERE permission IN {_FOLDED}) <> 1
                OR count(DISTINCT coalesce(condition::text, '')) FILTER (
                    WHERE permission IN {_FOLDED}) <> 1
                OR bool_or(permission = 'problems.create' AND scope <> 'all')
        ) THEN
            RAISE EXCEPTION 'a role holds only part of the problem keys, or at different scopes:'
                ' problems.manage cannot represent it, so going below 0077 is refused';
        END IF;
"""  # noqa: S608 - fixed key lists, no input

_JOIN = f"""{_REFUSE}
        INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
        SELECT tenant_id, role_id, 'problems.manage', scope, condition
        FROM role_permissions WHERE permission = 'problems.edit'
        ON CONFLICT DO NOTHING;
        DELETE FROM role_permissions WHERE permission IN {_FOUR};
"""  # noqa: S608 - fixed key lists, no input


def upgrade() -> None:
    """problems.manage(S) → create, edit, assign, close."""
    op.execute(_PER_TENANT.replace("STATEMENTS", _SPLIT))


def downgrade() -> None:
    """The four keys at S → problems.manage(S); refused when that would lose a grant."""
    op.execute(_PER_TENANT.replace("STATEMENTS", _JOIN))
