"""AD/LDAP directories through Keycloak federation (WP-040 session 2, D-118).

Expand only (D-113), no data step: directory_connectors also takes `source = 'ldap'`.
- Entra's own columns (directory_tenant, client_id, credential_kind) become nullable, and a
  check keeps them required for Entra;
- `ldap` (the admin's settings), `keycloak_component_id`, `federation_state` and
  `federation_error` (what the worker last did in Keycloak).

The downgrade refuses while an AD/LDAP directory exists (it would lose it): remove those first.

Revision ID: 0056
Revises: 0057 (main's head after #185; re-pointed onto 0058 once #178 lands)
Created: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "directory_connectors"
SOURCE = "ck_directory_connectors_source_code"
ENTRA_APP = "ck_directory_connectors_entra_app"
LDAP_SETTINGS = "ck_directory_connectors_ldap_settings"
STATE = "ck_directory_connectors_federation_state_code"
ENTRA_COLUMNS = ("directory_tenant", "client_id", "credential_kind")

# Any tenant's AD/LDAP directory blocks the downgrade (checked under every tenant: FORCE RLS).
REFUSE_IF_LDAP = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM directory_connectors WHERE tenant_id = t AND source = 'ldap') THEN
            RAISE EXCEPTION 'AD/LDAP directories exist: remove them before going below 0056';
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("ldap", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(TABLE, sa.Column("keycloak_component_id", sa.String(length=64), nullable=True))
    op.add_column(TABLE, sa.Column("federation_state", sa.String(length=20), nullable=True))
    op.add_column(TABLE, sa.Column("federation_error", sa.String(length=60), nullable=True))
    for column in ENTRA_COLUMNS:
        op.alter_column(TABLE, column, existing_type=sa.String(), nullable=True)
    op.drop_constraint(op.f(SOURCE), TABLE, type_="check")
    op.create_check_constraint(op.f(SOURCE), TABLE, "source IN ('entra', 'ldap')")
    op.create_check_constraint(
        op.f(ENTRA_APP),
        TABLE,
        "source <> 'entra' OR (directory_tenant IS NOT NULL AND client_id IS NOT NULL"
        " AND credential_kind IS NOT NULL)",
    )
    op.create_check_constraint(op.f(LDAP_SETTINGS), TABLE, "source <> 'ldap' OR ldap IS NOT NULL")
    op.create_check_constraint(
        op.f(STATE),
        TABLE,
        "federation_state IS NULL OR federation_state IN ('pending', 'applied', 'failed')",
    )


def downgrade() -> None:
    op.execute(REFUSE_IF_LDAP)
    for name in (STATE, LDAP_SETTINGS, ENTRA_APP, SOURCE):
        op.drop_constraint(op.f(name), TABLE, type_="check")
    op.create_check_constraint(op.f(SOURCE), TABLE, "source IN ('entra')")
    for column in ENTRA_COLUMNS:
        op.alter_column(TABLE, column, existing_type=sa.String(), nullable=False)
    for column in ("federation_error", "federation_state", "keycloak_component_id", "ldap"):
        op.drop_column(TABLE, column)
