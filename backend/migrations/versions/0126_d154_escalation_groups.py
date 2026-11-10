"""D-154 "rules" (Haider, 2026-11-10): an escalation that assigns a person names their group.

A `reassign_person` escalation action now carries `group_id`, the group the record moves to
with the person (D-154a keeps the assignee inside the record's group). The editor requires it
for someone in several groups and fills it in for someone in one. This fills it in on the
levels saved before, where the person is in exactly one group; the others are left for an
admin to choose (at run time they fall back to the record's own group, or to the group only).

Config rows only (`sla_escalation_levels`): never records, their SLA snapshots or the audit
log. Each policy whose levels change gets a new version (rule 5g: an editor open on the old one
gets a 409). Per tenant with app.tenant_id set, as these tables force RLS (see 0023, 0125). Each
tenant's counts (filled, left for a choice) are logged as a NOTICE.

Downgrade: nothing to undo. Code before this ignores `group_id`, and taking it out again would
also drop the groups admins chose since.

Revision ID: 0126
Revises: 0121
Created: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0126"
down_revision: str | None = "0121"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILL = """
DO $$
DECLARE
    t uuid;
    filled integer;
    policies integer;
    waiting integer;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        WITH single AS (
            SELECT m.user_id::text AS person, min(m.group_id::text) AS group_id
              FROM group_members m
              JOIN support_groups g ON g.tenant_id = m.tenant_id AND g.id = m.group_id
             WHERE m.tenant_id = t AND g.deleted_at IS NULL
             GROUP BY m.user_id
            HAVING count(*) = 1
        ),
        changed AS (
        UPDATE sla_escalation_levels l
           SET actions = (
               SELECT jsonb_agg(
                          CASE WHEN a->>'kind' = 'reassign_person' AND a->>'group_id' IS NULL
                                    AND s.group_id IS NOT NULL
                               THEN a || jsonb_build_object('group_id', s.group_id)
                               ELSE a END
                          ORDER BY e.n)
                 FROM jsonb_array_elements(l.actions) WITH ORDINALITY AS e(a, n)
                 LEFT JOIN single s ON s.person = e.a->>'target_id'
           )
         WHERE l.tenant_id = t
           AND EXISTS (
               SELECT 1 FROM jsonb_array_elements(l.actions) AS x(a)
                 JOIN single s ON s.person = x.a->>'target_id'
                WHERE x.a->>'kind' = 'reassign_person' AND x.a->>'group_id' IS NULL
           )
        RETURNING l.policy_id
        ),
        -- Rule 5g: an editor still holding the policy's old version gets a 409, never saves
        -- the actions without the group back over this.
        bumped AS (
            UPDATE sla_policies p SET version = p.version + 1, updated_at = now()
             WHERE p.tenant_id = t AND p.id IN (SELECT policy_id FROM changed)
            RETURNING p.id
        )
        SELECT (SELECT count(*) FROM changed), (SELECT count(*) FROM bumped)
          INTO filled, policies;
        SELECT count(*) INTO waiting
          FROM sla_escalation_levels l, jsonb_array_elements(l.actions) AS x(a)
         WHERE l.tenant_id = t
           AND x.a->>'kind' = 'reassign_person' AND x.a->>'group_id' IS NULL;
        IF filled > 0 OR waiting > 0 THEN
            RAISE NOTICE '0126: tenant % filled % level(s) of % policy(ies), % action(s) left for a choice',
                t, filled, policies, waiting;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    """Fills the person's only group into the escalation levels saved before (counted)."""
    op.execute(FILL)


def downgrade() -> None:
    """Nothing to undo (see the module docstring)."""
