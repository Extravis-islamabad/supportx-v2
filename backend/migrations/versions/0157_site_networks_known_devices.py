"""Address ranges mapped to sites, and known devices (identity_access; WP-057 S2b-1, D-170).

Expand only, no data step:
- `site_networks`: an admin's address range (cidr) → site, for the approximate sign-in place.
  The most specific prefix wins (domain/place.py). Edited as one list under the tenant's identity
  settings version, so rows carry no version of their own. One row per range per tenant.
- `known_devices`: a keyed fingerprint (32 bytes, HMAC) per person of each browser or device
  they have signed in from, so a sign-in from a new one sends them a notice (REQ-SEC-033).
  Never the address or the browser string. The GDPR erasure job deletes a person's rows.

Both are tenant tables, RLS forced, through migrations/helpers.py only (D-168 option b).
The sign-in log keeps no place: it is computed when read from the stored address, so erasing
the address erases the place too.

The downgrade refuses while any tenant has a mapped range or a known device, per tenant with
app.tenant_id set (rule 5h).

Revision ID: 0157
Revises: 0154
Created: 2026-11-13
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0157"
down_revision: str | None = "0154"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NETWORKS = "site_networks"
DEVICES = "known_devices"


def _times() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    """Adds the site map and the known devices."""
    op.create_table(
        NETWORKS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("network", postgresql.CIDR(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        *_times(),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{NETWORKS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], name="fk_site_networks_site"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{NETWORKS}")),
        sa.UniqueConstraint("tenant_id", "network", name="uq_site_networks_network"),
    )
    enable_tenant_rls(NETWORKS)
    grant_app(NETWORKS)

    op.create_table(
        DEVICES,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        *_times(),
        sa.CheckConstraint(
            "octet_length(fingerprint) = 32", name=op.f(f"ck_{DEVICES}_fingerprint_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{DEVICES}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_known_devices_user"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{DEVICES}")),
        sa.UniqueConstraint("tenant_id", "user_id", "fingerprint", name="uq_known_devices_print"),
    )
    enable_tenant_rls(DEVICES)
    grant_app(DEVICES)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {NETWORKS}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % maps address ranges to sites (rule 5h)', t;
        END IF;
        IF EXISTS (SELECT 1 FROM {DEVICES}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has known devices (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops both tables only while they are empty in every tenant; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    for table in (DEVICES, NETWORKS):
        op.drop_table(table)  # its policies go with it
