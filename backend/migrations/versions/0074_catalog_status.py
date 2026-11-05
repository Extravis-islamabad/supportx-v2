"""Catalog items get their status; existing tenants are marked as seeded (WP-031 s1, D-138).

Per tenant (business tables force RLS, so each statement runs with `app.tenant_id` set; see
0023):
- every item takes its status from `enabled`: enabled → published (published when it was
  created), disabled → retired. Items keep their requests either way;
- the tenant's catalog_settings row is created with `starter_seeded_at` set, so the starter
  catalog is never added to a tenant that already exists (only new tenants get it, through
  `organization.tenant.provisioned`, or by the explicit tooling command on an empty catalog).

The downgrade sets `enabled` back from the status (published → enabled; draft and retired →
disabled) and empties catalog_settings, which 0073's downgrade then drops.

Revision ID: 0074
Revises: 0073
Created: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UP = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE catalog_items
           SET status = CASE WHEN enabled THEN 'published' ELSE 'retired' END,
               published_at = CASE WHEN enabled THEN created_at END;
        INSERT INTO catalog_settings (tenant_id, starter_seeded_at)
        VALUES (t, now())
        ON CONFLICT (tenant_id) DO NOTHING;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""

DOWN = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE catalog_items SET enabled = (status = 'published');
        DELETE FROM catalog_settings;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    """Status from `enabled`; mark every existing tenant as seeded."""
    op.execute(UP)


def downgrade() -> None:
    """`enabled` from the status; remove the settings rows."""
    op.execute(DOWN)
