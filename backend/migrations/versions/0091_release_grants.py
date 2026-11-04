"""Saved roles keep their release access (WP-058a; lane B's condition, 2026-11-05).

releases.view and releases.manage were identity's reserved keys, which the role editor offered.
Releases now use the engine's actions (releases.view, create, edit, assign, cancel, reopen ...).
A custom role holding releases.manage at scope S gets create (scope all: create has no other),
edit, assign, cancel and reopen at S; releases.view stays as it is. manage never becomes delete
(delete stays with the admin roles). Per tenant with app.tenant_id set (role_permissions forces
RLS; see 0023, 0036, 0077).

The downgrade folds back only what releases.manage can represent without losing or widening a
grant (lane B's review, CLAUDE.md rule 5h): a role holding exactly the five keys the upgrade
made (create at all; edit, assign, cancel and reopen at one scope S) gets releases.manage at S.
Any other release key (delete, take, ...), a partial set, or the four at different scopes stops
the downgrade with an error and changes nothing.

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

_FOLDED = "('releases.edit', 'releases.assign', 'releases.cancel', 'releases.reopen')"
_FIVE = (
    "('releases.create', 'releases.edit', 'releases.assign', 'releases.cancel', 'releases.reopen')"
)

_REFUSE = f"""
        IF EXISTS (
            SELECT 1 FROM role_permissions WHERE permission LIKE 'releases.%'
                AND permission NOT IN ('releases.view', 'releases.manage')
                AND permission NOT IN {_FIVE}
        ) THEN
            RAISE EXCEPTION 'a role holds a release key releases.manage cannot represent: going'
                ' below 0091 would lose it';
        END IF;
        IF EXISTS (
            SELECT role_id FROM role_permissions WHERE permission IN {_FIVE}
            GROUP BY role_id
            HAVING count(*) <> 5
                OR count(DISTINCT scope) FILTER (WHERE permission IN {_FOLDED}) <> 1
                OR bool_or(permission = 'releases.create' AND scope <> 'all')
        ) THEN
            RAISE EXCEPTION 'a role holds only part of the release keys, or at different scopes:'
                ' releases.manage cannot represent it, so going below 0091 is refused';
        END IF;
"""  # noqa: S608 - fixed key lists, no input

_JOIN = f"""{_REFUSE}
        INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
        SELECT tenant_id, role_id, 'releases.manage', scope, condition
        FROM role_permissions WHERE permission = 'releases.edit'
        ON CONFLICT DO NOTHING;
        DELETE FROM role_permissions WHERE permission IN {_FIVE};
"""  # noqa: S608 - fixed key lists, no input


def upgrade() -> None:
    """releases.manage(S) → create, edit, assign, cancel, reopen."""
    op.execute(_PER_TENANT.replace("STATEMENTS", _SPLIT))


def downgrade() -> None:
    """The five keys at S → releases.manage(S); refused when that would lose a grant."""
    op.execute(_PER_TENANT.replace("STATEMENTS", _JOIN))
