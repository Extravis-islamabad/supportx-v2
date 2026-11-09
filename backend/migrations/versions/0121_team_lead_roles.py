"""The service desk manager splits; team leads manage only their groups (D-152, D-153).

Built-in roles' rights are computed in code. What is stored is the role rows and who holds them,
so the new built-in roles (team_lead, asset_manager, change_manager, release_manager,
purchase_manager, department_viewer) need no data step: a tenant gets their rows when its roles
are next listed (`ensure_system_roles`). This migration moves people, per tenant, with
`app.tenant_id` set (business tables force RLS):

* A holder of the old combined service desk manager in a tenant whose technicians see their
  groups (`access_settings.technician_scope = 'group'`, the default when unanswered), or who
  leads a live group, moves to team_lead. Everyone else keeps service_desk_manager, which means
  every desk record and no settings. Decided by the coordinator under Haider's "map by current
  scope" (D-153): the built-in role only ever held all-records grants, so no per-holder scope was
  stored to read.
* Every lead of a live group who does not hold team_lead gets it, additively, so no lead loses
  managing their group under D-152's `groups.manage_own` (coordinator, 2026-11-10).
* Roles held through a group (`group_roles`) are left as they are: a group's role is an
  admin's choice for all its members.
* The technician's narrower asset rights (assets linked to their own tickets) are code, with
  no data step; they are announced in the release notes.

Each tenant's counts go to the migration log (RAISE NOTICE). The rows it makes carry a fixed
`created_at` (MOVED, ADDED), so the downgrade undoes exactly them: moved managers return to
service_desk_manager, added leads just lose team_lead. It refuses while anyone holds one of the
other new roles, or a team lead given by hand, which would vanish (rule 5h).

D-153's standing rule: after the first customer install, any change that reduces existing rights
needs a release-note announcement and a mapping that removes nothing silently.

Revision ID: 0121
Revises: 0110
Created: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0121"
down_revision: str | None = "0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The new built-in role keys (named literally in the SQL below).
NEW_ROLES = (
    "team_lead",
    "asset_manager",
    "change_manager",
    "release_manager",
    "purchase_manager",
    "department_viewer",
)

# The role row of `key` in the current tenant, made like ensure_system_roles makes it.
_ROLE_ID = """
CREATE OR REPLACE FUNCTION pg_temp.sx_0121_role(t uuid, role_key text) RETURNS uuid
LANGUAGE plpgsql AS $f$
DECLARE r uuid;
BEGIN
    SELECT id INTO r FROM roles
    WHERE tenant_id = t AND key = role_key AND deleted_at IS NULL;
    IF r IS NULL THEN
        r := gen_random_uuid();
        INSERT INTO roles (id, tenant_id, key, name, is_system, version)
        VALUES (r, t, role_key, role_key, true, 1);
    END IF;
    RETURN r;
END
$f$;
"""

# The rows this migration makes are marked by their `created_at` (literal in the SQL below), so the
# downgrade undoes exactly them: MOVED for a service desk manager moved to team lead, ADDED for a
# group lead given it.
MOVED = "2026-11-10 00:01:21+00"
ADDED = "2026-11-10 00:01:22+00"

UPGRADE = """
DO $$
DECLARE
    t uuid;
    manager uuid;
    lead uuid;
    scope text;
    moved int;
    kept int;
    added int;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        moved := 0; kept := 0; added := 0;
        SELECT id INTO manager FROM roles
        WHERE tenant_id = t AND key = 'service_desk_manager' AND deleted_at IS NULL;
        SELECT coalesce(
            (SELECT technician_scope FROM access_settings WHERE tenant_id = t), 'group'
        ) INTO scope;
        IF manager IS NOT NULL THEN
            CREATE TEMP TABLE sx_0121_moving ON COMMIT DROP AS
            SELECT ur.user_id FROM user_roles ur
            WHERE ur.tenant_id = t AND ur.role_id = manager
              AND (
                  scope = 'group'
                  OR EXISTS (
                      SELECT 1 FROM support_groups g
                      WHERE g.tenant_id = t AND g.lead_id = ur.user_id
                        AND g.deleted_at IS NULL AND g.disabled_at IS NULL
                  )
              );
            SELECT count(*) INTO moved FROM sx_0121_moving;
            IF moved > 0 THEN
                lead := pg_temp.sx_0121_role(t, 'team_lead');
                INSERT INTO user_roles (tenant_id, user_id, role_id, created_at)
                SELECT t, user_id, lead, '2026-11-10 00:01:21+00'::timestamptz FROM sx_0121_moving
                ON CONFLICT DO NOTHING;
                DELETE FROM user_roles
                WHERE tenant_id = t AND role_id = manager
                  AND user_id IN (SELECT user_id FROM sx_0121_moving);
            END IF;
            SELECT count(*) INTO kept FROM user_roles WHERE tenant_id = t AND role_id = manager;
            DROP TABLE sx_0121_moving;
        END IF;
        -- Every live group's lead keeps managing their group (D-152 needs groups.manage_own):
        -- additive, removes nothing (coordinator, 2026-11-10).
        IF EXISTS (
            SELECT 1 FROM support_groups
            WHERE tenant_id = t AND lead_id IS NOT NULL
              AND deleted_at IS NULL AND disabled_at IS NULL
        ) THEN
            lead := pg_temp.sx_0121_role(t, 'team_lead');
            INSERT INTO user_roles (tenant_id, user_id, role_id, created_at)
            SELECT DISTINCT t, g.lead_id, lead, '2026-11-10 00:01:22+00'::timestamptz FROM support_groups g
            WHERE g.tenant_id = t AND g.lead_id IS NOT NULL
              AND g.deleted_at IS NULL AND g.disabled_at IS NULL
            ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS added = ROW_COUNT;
        END IF;
        RAISE NOTICE '0121 tenant %: % moved to team lead, % kept manager, % leads added',
            t, moved, kept, added;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""

DOWNGRADE = """
DO $$
DECLARE
    t uuid;
    lead uuid;
    manager uuid;
    back int;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM roles r
            WHERE r.tenant_id = t AND r.key IN ('asset_manager', 'change_manager', 'release_manager',
                            'purchase_manager', 'department_viewer')
              AND (
                  EXISTS (SELECT 1 FROM user_roles ur WHERE ur.role_id = r.id)
                  OR EXISTS (SELECT 1 FROM group_roles gr WHERE gr.role_id = r.id)
              )
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has holders of the new roles (rule 5h)', t;
        END IF;
        SELECT id INTO lead FROM roles
        WHERE tenant_id = t AND key = 'team_lead' AND deleted_at IS NULL;
        back := 0;
        IF lead IS NOT NULL THEN
            -- Team lead given by an admin after the upgrade: there is no old role to return to.
            IF EXISTS (
                SELECT 1 FROM user_roles WHERE tenant_id = t AND role_id = lead
                  AND created_at NOT IN ('2026-11-10 00:01:21+00'::timestamptz, '2026-11-10 00:01:22+00'::timestamptz)
            ) OR EXISTS (SELECT 1 FROM group_roles WHERE tenant_id = t AND role_id = lead) THEN
                RAISE EXCEPTION 'downgrade refused: tenant % gave team lead by hand (rule 5h)', t;
            END IF;
            manager := pg_temp.sx_0121_role(t, 'service_desk_manager');
            INSERT INTO user_roles (tenant_id, user_id, role_id)
            SELECT t, user_id, manager FROM user_roles
            WHERE tenant_id = t AND role_id = lead AND created_at = '2026-11-10 00:01:21+00'::timestamptz
            ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS back = ROW_COUNT;
            DELETE FROM user_roles WHERE tenant_id = t AND role_id = lead;
        END IF;
        DELETE FROM roles WHERE tenant_id = t AND key IN ('team_lead', 'asset_manager',
            'change_manager', 'release_manager', 'purchase_manager', 'department_viewer')
          AND is_system;
        RAISE NOTICE '0121 downgrade tenant %: % back to service desk manager', t, back;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def upgrade() -> None:
    """Moves group-scoped service desk managers to team lead, per tenant."""
    op.execute(_ROLE_ID)
    op.execute(UPGRADE)


def downgrade() -> None:
    """Team leads back to service desk manager; refuses while the other new roles are held."""
    op.execute(_ROLE_ID)
    op.execute(DOWNGRADE)
