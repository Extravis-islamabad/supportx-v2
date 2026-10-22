"""Transactional outbox, consumer idempotency records and the relay's rights (WP-007).

outbox_events     tenant-scoped (RLS). supportx_app: INSERT only. supportx_relay: read every
                  tenant's rows, set the delivery columns, delete PUBLISHED rows (purge).
processed_events  tenant-scoped (RLS). supportx_app: SELECT, INSERT (consumers run as the app
                  role inside the event's tenant).

Revision ID: 0003
Revises: 0002
Created: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.shared.db.rls import RELAY_ROLE
from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Columns the relay may change; everything that describes the event stays immutable for it.
RELAY_UPDATE_COLUMNS = "published_at, publish_attempts, last_error, updated_at"

# NOTIFY is queued by the inserting transaction and delivered only when it commits, so the relay
# never wakes for a rolled-back event. One notification per statement (and PostgreSQL folds
# identical ones within a transaction), not one per row.
NOTIFY_FUNCTION = """
CREATE FUNCTION supportx_outbox_notify() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('supportx_outbox', '');
    RETURN NULL;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=False),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name=op.f("ck_outbox_events_schema_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_outbox_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        "ix_outbox_events_published_at",
        "outbox_events",
        ["published_at"],
        postgresql_where=sa.text("published_at IS NOT NULL"),
    )
    enable_tenant_rls("outbox_events")
    grant_app("outbox_events", ("INSERT",))
    op.execute(NOTIFY_FUNCTION)
    op.execute(
        "CREATE TRIGGER outbox_events_notify AFTER INSERT ON outbox_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION supportx_outbox_notify()"
    )
    # The relay reads across tenants through policies scoped TO supportx_relay alone (not
    # BYPASSRLS, which would also cover any table the role were ever granted by mistake).
    # Allowlisted in tooling/rls_guard.py CROSS_TENANT_POLICIES.
    op.execute(
        f"CREATE POLICY outbox_events_relay_select ON outbox_events FOR SELECT TO {RELAY_ROLE} "
        "USING (true)"
    )
    op.execute(
        f"CREATE POLICY outbox_events_relay_update ON outbox_events FOR UPDATE TO {RELAY_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    # Purge: the database itself refuses to delete an event that was never published.
    op.execute(
        f"CREATE POLICY outbox_events_relay_delete ON outbox_events FOR DELETE TO {RELAY_ROLE} "
        "USING (published_at IS NOT NULL)"
    )
    op.execute(f"REVOKE ALL ON outbox_events FROM {RELAY_ROLE}")
    op.execute(f"GRANT SELECT, DELETE ON outbox_events TO {RELAY_ROLE}")
    op.execute(f"GRANT UPDATE ({RELAY_UPDATE_COLUMNS}) ON outbox_events TO {RELAY_ROLE}")

    op.create_table(
        "processed_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_processed_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "consumer", "event_id", name=op.f("pk_processed_events")
        ),
    )
    enable_tenant_rls("processed_events")
    grant_app("processed_events", ("SELECT", "INSERT"))


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("outbox_events")  # drops its trigger and policies with it
    op.execute("DROP FUNCTION supportx_outbox_notify()")
