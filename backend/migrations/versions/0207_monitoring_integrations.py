"""MonetX connections, topology runs and the devices they mapped (WP-053 S6), 0207.

The first tables of `monitoring_integrations` (ADR-017, D-001: SupportX only reads MonetX):
- `monitoring_connections`: one MonetX per row. Its API token lives in integrations' secret store
  (`secret_ref`), never here.
- `monitoring_topology_runs`: each topology import, with counts and an error code.
- `monitoring_devices`: which MonetX device a connection mapped to which CI, how many runs in a
  row missed it (stale after 1, ended after 3), and its last health. The CI is the CMDB's,
  referenced by ID only: no constraint across modules (rule e).
- `monitoring_links`: the relationships the import made, so a hand-made one is never removed.

All tenant-scoped with RLS; soft delete for connections, none for the others (rows the import
owns). Reversible; no data step.

Revision ID: 0207
Revises: 0205
Created: 2026-11-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0207"
down_revision: str | None = "0205"  # main's head at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONNECTIONS = "monitoring_connections"
RUNS = "monitoring_topology_runs"
DEVICES = "monitoring_devices"
LINKS = "monitoring_links"


def _audit_columns() -> list[sa.Column[Any]]:  # Any: the columns mix types (timestamps, UUIDs)
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]  # fmt: skip


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"], ["tenants.id"], name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )  # fmt: skip


def _connection_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "connection_id"],
        [f"{CONNECTIONS}.tenant_id", f"{CONNECTIONS}.id"],
        name=f"fk_{table}_connection",
    )


def upgrade() -> None:
    # integrations' secret store learns the API token type (SecretType.API_TOKEN): expand only.
    op.drop_constraint(op.f(_STORE_KIND_CHECK), "connector_secrets", type_="check")
    op.create_check_constraint(
        op.f(_STORE_KIND_CHECK), "connector_secrets", f"secret_type IN {_TYPES_NOW}"
    )
    """The four tables, RLS on each."""
    op.create_table(
        CONNECTIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), server_default="monetx", nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("secret_ref", sa.Uuid(), nullable=True),
        sa.Column("tls", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "site_map", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=60), nullable=True),
        *_audit_columns(),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('monetx')", name=op.f(f"ck_{CONNECTIONS}_kind_code")),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 120", name=op.f(f"ck_{CONNECTIONS}_name_length")
        ),
        _tenant_fk(CONNECTIONS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{CONNECTIONS}")),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{CONNECTIONS}_tenant_id_id"),
    )
    op.create_index(
        f"uq_{CONNECTIONS}_name",
        CONNECTIONS,
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(CONNECTIONS)
    grant_app(CONNECTIONS, ("SELECT", "INSERT", "UPDATE"))  # soft delete only

    op.create_table(
        RUNS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="running", nullable=False),
        sa.Column(
            "counts", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "state IN ('running', 'done', 'failed')", name=op.f(f"ck_{RUNS}_state_code")
        ),
        _tenant_fk(RUNS),
        _connection_fk(RUNS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RUNS}")),
    )
    op.create_index(
        f"ix_{RUNS}_tenant_connection", RUNS, ["tenant_id", "connection_id", "started_at"]
    )
    enable_tenant_rls(RUNS)
    grant_app(RUNS, ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        DEVICES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("ci_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="seen", nullable=False),
        sa.Column("missed_runs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health", sa.String(length=20), nullable=True),
        sa.Column("health_since", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "state IN ('seen', 'stale', 'ended')", name=op.f(f"ck_{DEVICES}_state_code")
        ),
        sa.CheckConstraint("missed_runs >= 0", name=op.f(f"ck_{DEVICES}_missed_runs")),
        _tenant_fk(DEVICES),
        _connection_fk(DEVICES),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{DEVICES}")),
    )
    op.create_index(
        f"uq_{DEVICES}_external",
        DEVICES,
        ["tenant_id", "connection_id", "external_id"],
        unique=True,
    )
    op.create_index(f"ix_{DEVICES}_tenant_ci", DEVICES, ["tenant_id", "ci_id"])
    enable_tenant_rls(DEVICES)
    grant_app(DEVICES, ("SELECT", "INSERT", "UPDATE"))  # an ended device is kept, never deleted

    op.create_table(
        LINKS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=400), nullable=False),
        sa.Column("relationship_id", sa.Uuid(), nullable=False),
        *_audit_columns(),
        _tenant_fk(LINKS),
        _connection_fk(LINKS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{LINKS}")),
    )
    op.create_index(
        f"uq_{LINKS}_external", LINKS, ["tenant_id", "connection_id", "external_id"], unique=True
    )
    enable_tenant_rls(LINKS)
    grant_app(LINKS, ("SELECT", "INSERT", "DELETE"))  # a link the import removed is forgotten


# Per tenant (business tables force RLS, even for the migrator; see 0023): a tenant's MonetX set-up
# is never dropped by a downgrade (rule 5h).
_STORE_KIND_CHECK = "ck_connector_secrets_secret_type_code"
_TYPES_BEFORE = "('password', 'client_secret', 'certificate', 'refresh_token')"
_TYPES_NOW = "('password', 'client_secret', 'certificate', 'refresh_token', 'api_token')"

_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM monitoring_connections) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has a monitoring connection (rule 5h)', t;
        END IF;
        IF EXISTS (SELECT 1 FROM connector_secrets WHERE secret_type = 'api_token') THEN
            RAISE EXCEPTION 'downgrade refused: tenant % still holds an API token secret', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drop the four tables, only while no tenant has a connection (rule 5h)."""
    op.execute(_REFUSE_IF_ANY)
    for table in (LINKS, DEVICES, RUNS, CONNECTIONS):
        op.drop_table(table)
    op.drop_constraint(op.f(_STORE_KIND_CHECK), "connector_secrets", type_="check")
    op.create_check_constraint(
        op.f(_STORE_KIND_CHECK), "connector_secrets", f"secret_type IN {_TYPES_BEFORE}"
    )
