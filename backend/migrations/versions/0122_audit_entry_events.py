"""The lifecycle events of a save's audit entry (WP-064 session 1, D-150, ADR-045).

Every save of a lifecycle record type writes one audit entry listing all the events it stands
for. `audit_entries.events` holds them (codes only, inside the entry hash). It is NULL for every
entry written before this release and for entries that are not a save, which hash exactly as
before. Expand-only: no data step.

A plain GIN index on the array serves "action is X or X is among the events", so filters, saved
searches, exports and the SIEM stream find a route code inside a save's entry. Tenant filtering
comes from RLS and the tenant-first btree indexes. btree_gin is not used: a new extension can
need a superuser on some installs (coordinator, 2026-11-10). On a partitioned table the index is
created on every partition.

The downgrade refuses while any tenant has an entry with events: dropping them would make those
entries fail verification (rule 5h).

Revision ID: 0122
Revises: 0114
Created: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0122"
down_revision: str | None = "0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_audit_entries_events"


def upgrade() -> None:
    """Adds the nullable array and its GIN index."""
    op.add_column(
        "audit_entries", sa.Column("events", postgresql.ARRAY(sa.String(length=80)), nullable=True)
    )
    op.create_index(INDEX, "audit_entries", ["events"], postgresql_using="gin")


_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM audit_entries WHERE events IS NOT NULL) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has lifecycle audit entries (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the column only while no tenant has an entry with events; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_index(INDEX, table_name="audit_entries")
    op.drop_column("audit_entries", "events")
