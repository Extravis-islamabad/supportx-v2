"""CMDB relationships and business views (WP-053 S2; REQ-CMDB-006..009, 024's view side), 0180.

Expand only, no data step (each tenant's built-in relationship types are made the first time
its CMDB relationships are used, by the service, as 0173's CI types are):
- `cmdb_relationship_types`: a code, a name per direction (`names_forward`, `names_inverse`, a
  tenant's own type only; built-in ones are labelled `cmdb_relationship.<code>.forward|inverse`)
  and whether impact flows through it (`carries_impact`, read by S3's impact analysis).
- `cmdb_relationship_type_rules`: which CI types a relationship type may join (from, to); a rule
  on a CI type covers the types below it. A type with no live rule joins any two CIs.
  `suggested` offers it first for that CI type.
- `cmdb_relationships`: one live link per (tenant, type, from, to), never a CI to itself. Soft
  delete only, so earlier versions keep what was linked then.
- `cmdb_business_views`: a saved map for one base CI (layout, filters, pinned positions) with an
  owner (moved to the successor by a person's erasure, ADR-052).

Every table is tenant-scoped with RLS forced, through migrations/helpers.py only; every index
starts with tenant_id. The downgrade refuses while any tenant has a relationship, a view, or its
own relationship type or rule (rule 5h), per tenant with app.tenant_id set; built-in types are
made again on first use.

Revision ID: 0180
Revises: 0177 (main's head at its queue turn: 0175 → 0177 → 0180)
Created: 2026-11-18
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0180"
down_revision: str | None = "0177"  # main's head at its queue turn (0175 → 0177 → 0180)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REL_TYPES = "cmdb_relationship_types"
RULES = "cmdb_relationship_type_rules"
RELS = "cmdb_relationships"
VIEWS = "cmdb_business_views"
CI_TYPES = "cmdb_ci_types"
CIS = "cmdb_cis"
LAYOUTS = ("radial", "hierarchical", "tree")


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


def _to(column: str, target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], name=name
    )


def upgrade() -> None:
    """The four tables."""
    op.create_table(
        REL_TYPES,
        *_entity_columns(),
        sa.Column("code", sa.String(length=63), nullable=False),
        sa.Column("built_in", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("names_forward", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("names_inverse", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("carries_impact", sa.Boolean(), server_default="true", nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]{1,62}$'", name=op.f(f"ck_{REL_TYPES}_code_format")
        ),
        _tenant_fk(REL_TYPES),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{REL_TYPES}")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_cmdb_relationship_types_tenant_id_id"),
    )
    op.create_index(
        "uq_cmdb_relationship_types_code",
        REL_TYPES,
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        RULES,
        *_entity_columns(),
        sa.Column("type_id", sa.Uuid(), nullable=False),
        sa.Column("from_ci_type_id", sa.Uuid(), nullable=False),
        sa.Column("to_ci_type_id", sa.Uuid(), nullable=False),
        sa.Column("suggested", sa.Boolean(), server_default="false", nullable=False),
        *_audit_columns(),
        _tenant_fk(RULES),
        _to("type_id", REL_TYPES, "fk_cmdb_relationship_type_rules_type"),
        _to("from_ci_type_id", CI_TYPES, "fk_cmdb_relationship_type_rules_from"),
        _to("to_ci_type_id", CI_TYPES, "fk_cmdb_relationship_type_rules_to"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RULES}")),
    )
    op.create_index(
        "uq_cmdb_relationship_type_rules_pair",
        RULES,
        ["tenant_id", "type_id", "from_ci_type_id", "to_ci_type_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        RELS,
        *_entity_columns(),
        sa.Column("type_id", sa.Uuid(), nullable=False),
        sa.Column("from_ci_id", sa.Uuid(), nullable=False),
        sa.Column("to_ci_id", sa.Uuid(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("from_ci_id <> to_ci_id", name=op.f(f"ck_{RELS}_not_self")),
        _tenant_fk(RELS),
        _to("type_id", REL_TYPES, "fk_cmdb_relationships_type"),
        _to("from_ci_id", CIS, "fk_cmdb_relationships_from"),
        _to("to_ci_id", CIS, "fk_cmdb_relationships_to"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RELS}")),
    )
    op.create_index(
        "uq_cmdb_relationships_live",
        RELS,
        ["tenant_id", "type_id", "from_ci_id", "to_ci_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_cmdb_relationships_tenant_from", RELS, ["tenant_id", "from_ci_id"])
    op.create_index("ix_cmdb_relationships_tenant_to", RELS, ["tenant_id", "to_ci_id"])

    op.create_table(
        VIEWS,
        *_entity_columns(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base_ci_id", sa.Uuid(), nullable=False),
        sa.Column("layout", sa.String(length=20), server_default="radial", nullable=False),
        sa.Column("filters", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("positions", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f(f"ck_{VIEWS}_name_length")
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 10000",
            name=op.f(f"ck_{VIEWS}_description_length"),
        ),
        sa.CheckConstraint(_codes("layout", LAYOUTS), name=op.f(f"ck_{VIEWS}_layout_code")),
        _tenant_fk(VIEWS),
        _to("base_ci_id", CIS, "fk_cmdb_business_views_base"),
        _to("owner_id", "users", "fk_cmdb_business_views_owner"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{VIEWS}")),
    )
    for name, cols in (
        ("ix_cmdb_business_views_tenant_updated", ["tenant_id", "updated_at", "id"]),
        ("ix_cmdb_business_views_tenant_base", ["tenant_id", "base_ci_id"]),
        ("ix_cmdb_business_views_tenant_owner", ["tenant_id", "owner_id"]),
    ):
        op.create_index(name, VIEWS, cols)

    for table in (REL_TYPES, RULES, RELS, VIEWS):
        enable_tenant_rls(table)
        grant_app(table, ("SELECT", "INSERT", "UPDATE"))  # soft delete only
        enable_actor_audit(table)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {RELS}) OR EXISTS (SELECT 1 FROM {VIEWS})
           OR EXISTS (SELECT 1 FROM {RULES})
           OR EXISTS (SELECT 1 FROM {REL_TYPES} WHERE NOT built_in) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has CMDB relationship data (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops the tables only while no tenant has a relationship, a view or its own type or rule."""
    op.execute(_REFUSE_IF_ANY)
    for table in (VIEWS, RELS, RULES, REL_TYPES):
        op.drop_table(table)  # its indexes and policies go with it
