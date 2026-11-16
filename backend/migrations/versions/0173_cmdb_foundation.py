"""CMDB foundation (WP-053 S1; REQ-CMDB-001..005, 024, 031), 0173.

Expand only, no data step (each tenant's built-in CI types and states are made the first time
its CMDB is used, by the service):
- `cmdb_ci_types`: the CI type tree, with the attributes each type's CIs hold (inherited below).
- `cmdb_ci_states`: CI states, each active or end of life.
- `cmdb_cis`: configuration items, one per asset at most, with typed custom values and search.
- `cmdb_ci_versions`: a snapshot after every save; append-only for the app (SELECT, INSERT).
- `cmdb_settings`: one row per tenant.

Every table is tenant-scoped with RLS forced, through migrations/helpers.py only; every index
starts with tenant_id. The downgrade refuses while any tenant has a CMDB row (rule 5h), per
tenant with app.tenant_id set.

Revision ID: 0173
Revises: 0168 (main's head while building; re-pointed at its queue turn)
Created: 2026-11-16
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0173"
down_revision: str | None = "0168"  # main's head while building; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = "cmdb_ci_types"
STATES = "cmdb_ci_states"
CIS = "cmdb_cis"
VERSIONS = "cmdb_ci_versions"
SETTINGS = "cmdb_settings"
SOURCES = ("manual", "asset_sync", "import", "monetx")
IMPACTS = ("low", "medium", "high", "critical")
CATEGORIES = ("active", "end_of_life")
SEARCH_VECTOR = (
    "sx_search_vector(name || ' ' || display_id || ' ' || replace(display_id, '-', ' '),"
    " coalesce(description, ''))"
)


def _codes(column: str, codes: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _entity_columns() -> list[sa.Column[Any]]:
    """A TenantEntity's own columns (app/shared/db/models.py), in its order."""
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
    ]


def _audit_columns() -> list[sa.Column[Any]]:
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
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    """The five CMDB tables."""
    op.create_table(
        TYPES,
        *_entity_columns(),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("api_name", sa.String(length=63), nullable=False),
        sa.Column("built_in", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("names", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("relationship_types", postgresql.JSONB(), server_default="[]", nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "api_name ~ '^[a-z][a-z0-9_]{1,62}$'", name=op.f(f"ck_{TYPES}_api_name_format")
        ),
        _tenant_fk(TYPES),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            [f"{TYPES}.tenant_id", f"{TYPES}.id"],
            name="fk_cmdb_ci_types_parent",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TYPES}")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_cmdb_ci_types_tenant_id_id"),
    )
    op.create_index(
        "uq_cmdb_ci_types_api_name",
        TYPES,
        ["tenant_id", "api_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_cmdb_ci_types_tenant_parent", TYPES, ["tenant_id", "parent_id"])

    op.create_table(
        STATES,
        *_entity_columns(),
        sa.Column("api_name", sa.String(length=63), nullable=False),
        sa.Column("built_in", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("names", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("category", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "api_name ~ '^[a-z][a-z0-9_]{1,62}$'", name=op.f(f"ck_{STATES}_api_name_format")
        ),
        sa.CheckConstraint(_codes("category", CATEGORIES), name=op.f(f"ck_{STATES}_category_code")),
        _tenant_fk(STATES),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{STATES}")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_cmdb_ci_states_tenant_id_id"),
    )
    op.create_index(
        "uq_cmdb_ci_states_api_name",
        STATES,
        ["tenant_id", "api_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        CIS,
        *_entity_columns(),
        sa.Column("display_id", sa.String(length=20), nullable=False),
        sa.Column("type_id", sa.Uuid(), nullable=False),
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("owner_group_id", sa.Uuid(), nullable=True),
        sa.Column("managed_by_group_id", sa.Uuid(), nullable=True),
        sa.Column("business_impact", sa.String(length=20), nullable=True),
        sa.Column("criticality", sa.String(length=20), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("custom", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR, persisted=True),
            nullable=True,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f(f"ck_{CIS}_name_length")
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 10000",
            name=op.f(f"ck_{CIS}_description_length"),
        ),
        sa.CheckConstraint(_codes("source", SOURCES), name=op.f(f"ck_{CIS}_source_code")),
        sa.CheckConstraint(
            f"business_impact IS NULL OR {_codes('business_impact', IMPACTS)}",
            name=op.f(f"ck_{CIS}_business_impact_code"),
        ),
        sa.CheckConstraint(
            f"criticality IS NULL OR {_codes('criticality', IMPACTS)}",
            name=op.f(f"ck_{CIS}_criticality_code"),
        ),
        _tenant_fk(CIS),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type_id"], [f"{TYPES}.tenant_id", f"{TYPES}.id"], name="fk_cmdb_cis_type"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "state_id"],
            [f"{STATES}.tenant_id", f"{STATES}.id"],
            name="fk_cmdb_cis_state",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_cmdb_cis_owner",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{CIS}")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_cmdb_cis_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "display_id", name="uq_cmdb_cis_tenant_id_display_id"),
    )
    op.create_index(
        "uq_cmdb_cis_asset",
        CIS,
        ["tenant_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NOT NULL AND deleted_at IS NULL"),
    )
    for name, cols in (
        ("ix_cmdb_cis_tenant_updated", ["tenant_id", "updated_at", "id"]),
        ("ix_cmdb_cis_tenant_type", ["tenant_id", "type_id", "id"]),
        ("ix_cmdb_cis_tenant_state", ["tenant_id", "state_id", "id"]),
        ("ix_cmdb_cis_tenant_site", ["tenant_id", "site_id", "id"]),
        ("ix_cmdb_cis_tenant_owner", ["tenant_id", "owner_user_id"]),
        ("ix_cmdb_cis_tenant_owner_group", ["tenant_id", "owner_group_id"]),
    ):
        op.create_index(name, CIS, cols)
    op.create_index("ix_cmdb_cis_custom", CIS, ["custom"], postgresql_using="gin")
    op.create_index("ix_cmdb_cis_search_vector", CIS, ["search_vector"], postgresql_using="gin")

    op.create_table(
        VERSIONS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ci_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "saved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("saved_by", sa.Uuid(), nullable=True),
        _tenant_fk(VERSIONS),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ci_id"], [f"{CIS}.tenant_id", f"{CIS}.id"], name="fk_cmdb_ci_versions_ci"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{VERSIONS}")),
    )
    op.create_index("ix_cmdb_ci_versions_ci", VERSIONS, ["tenant_id", "ci_id", "version"])

    op.create_table(
        SETTINGS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("exclude_eol_from_pickers", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _tenant_fk(SETTINGS),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f(f"pk_{SETTINGS}")),
    )

    for table in (TYPES, STATES, CIS, VERSIONS, SETTINGS):
        enable_tenant_rls(table)
    for table in (TYPES, STATES, CIS):
        grant_app(table, ("SELECT", "INSERT", "UPDATE"))  # soft delete only
        enable_actor_audit(table)
    grant_app(VERSIONS, ("SELECT", "INSERT"))  # append-only
    grant_app(SETTINGS, ("SELECT", "INSERT", "UPDATE"))


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {CIS}) OR EXISTS (SELECT 1 FROM {TYPES} WHERE NOT built_in)
           OR EXISTS (SELECT 1 FROM {STATES} WHERE NOT built_in) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has CMDB data (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops the CMDB tables only while no tenant has a CI or its own type or state."""
    op.execute(_REFUSE_IF_ANY)
    for table in (SETTINGS, VERSIONS, CIS, STATES, TYPES):
        op.drop_table(table)  # its indexes and policies go with it
