"""Service catalog administration (WP-031 s1; REQ-CAT-001..008, -014, -016..019, -024, -027, -028).

- service_categories: `parent_id` (a tree, same tenant, at most four levels and no loops,
  checked by the service), `icon` (a fixed code), `descriptions` per language, `enabled` (a
  disabled category hides its items from requesters).
- catalog_items:
  - `status` draft | published | retired, with `publish_at` / `retire_at` run by a schedule,
    and `published_at`;
  - `kind` service | incident_template, plus `template_id` (REQ-CAT-003: a "report a problem"
    entry pointing at an incident template, never a copy of it);
  - `summaries`, `keywords` (per language, lists), `icon`, `owner_id`, `featured`,
    `sort_order`, `subject_template` and `requesters_see_approval`;
  - `extra_category_ids` (the item also shows in these, up to five);
  - search: `search_vector` (names, keywords and summaries weighted A, descriptions B, in every
    language) and `search_name` (names, normalised, for typos), generated columns with GIN
    indexes (ADR-039: Postgres, not OpenSearch).
  `enabled` stays for now (expand/contract): 0074 turns it into `status` per tenant, the code no
  longer reads it, and a later migration drops it.
- catalog_settings (one row per tenant, RLS): `starter_seeded_at` (D-138: the starter catalog is
  seeded at most once) and `hide_default_incident_template` (REQ-CAT-014).

Expand only; the data step is 0074. The downgrade removes what this adds.

Revision ID: 0073
Revises: 0070
Created: 2026-11-04
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0073"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("draft", "published", "retired")
KINDS = ("service", "incident_template")

# The texts of a per-language JSON object, and of a per-language object of lists. Both are
# deterministic for a given value, so they may be IMMUTABLE (generated columns need it).
TEXTS = """
CREATE FUNCTION catalog_texts(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT coalesce(
    (SELECT string_agg(t, ' ') FROM jsonb_each_text(coalesce(value, '{}'::jsonb)) AS e(k, t)),
    ''
  )
$$
"""
WORD_LISTS = """
CREATE FUNCTION catalog_word_lists(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT coalesce(
    (SELECT string_agg(w, ' ')
       FROM jsonb_each(coalesce(value, '{}'::jsonb)) AS e(k, v),
            jsonb_array_elements_text(CASE WHEN jsonb_typeof(v) = 'array' THEN v ELSE '[]' END)
              AS w),
    ''
  )
$$
"""
# Descriptions are sanitised HTML: tags and entities become spaces before indexing.
VECTOR = (
    "sx_search_vector("
    "catalog_texts(names) || ' ' || catalog_word_lists(keywords)"
    " || ' ' || catalog_texts(summaries),"
    " regexp_replace(catalog_texts(descriptions), '<[^>]*>|&[a-zA-Z0-9#]+;', ' ', 'g'))"
)
NAME = "sx_search_normalize(catalog_texts(names) || ' ' || catalog_word_lists(keywords))"


def _same_tenant(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target}.tenant_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    """Add the columns, the search and the settings table."""
    op.execute(TEXTS)
    op.execute(WORD_LISTS)
    jsonb = postgresql.JSONB()
    op.add_column("service_categories", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.add_column("service_categories", sa.Column("icon", sa.String(40), nullable=True))
    op.add_column(
        "service_categories",
        sa.Column("descriptions", jsonb, server_default="{}", nullable=False),
    )
    op.add_column(
        "service_categories",
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.create_foreign_key(
        "fk_service_categories_parent_id_service_categories",
        "service_categories",
        "service_categories",
        ["tenant_id", "parent_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_service_categories_tenant_parent",
        "service_categories",
        ["tenant_id", "parent_id", "sort_order"],
    )

    columns: list[sa.Column[Any]] = [  # Any: each column has its own type
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(30), server_default="service", nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("summaries", jsonb, server_default="{}", nullable=False),
        sa.Column("keywords", jsonb, server_default="{}", nullable=False),
        sa.Column("icon", sa.String(40), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("featured", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("subject_template", sa.String(200), nullable=True),
        sa.Column("requesters_see_approval", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "extra_category_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default="{}",
            nullable=False,
        ),
    ]
    for column in columns:
        op.add_column("catalog_items", column)
    op.create_check_constraint(
        op.f("ck_catalog_items_status_code"),
        "catalog_items",
        f"status IN ({', '.join(repr(s) for s in STATUSES)})",
    )
    op.create_check_constraint(
        op.f("ck_catalog_items_kind_code"),
        "catalog_items",
        f"kind IN ({', '.join(repr(k) for k in KINDS)})",
    )
    op.create_check_constraint(
        op.f("ck_catalog_items_texts_object"),
        "catalog_items",
        "jsonb_typeof(summaries) = 'object' AND jsonb_typeof(keywords) = 'object'",
    )
    op.create_check_constraint(
        op.f("ck_catalog_items_extra_categories"),
        "catalog_items",
        "cardinality(extra_category_ids) <= 5",
    )
    op.create_foreign_key(
        "fk_catalog_items_template_id_work_item_templates",
        "catalog_items",
        "work_item_templates",
        ["tenant_id", "template_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_catalog_items_owner_id_users",
        "catalog_items",
        "users",
        ["tenant_id", "owner_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.execute(
        "ALTER TABLE catalog_items"
        f" ADD COLUMN search_vector tsvector GENERATED ALWAYS AS ({VECTOR}) STORED,"
        f" ADD COLUMN search_name text GENERATED ALWAYS AS ({NAME}) STORED"
    )
    op.execute("CREATE INDEX ix_catalog_items_search ON catalog_items USING gin (search_vector)")
    op.execute(
        "CREATE INDEX ix_catalog_items_search_name ON catalog_items"
        " USING gin (search_name gin_trgm_ops)"
    )
    op.create_index(
        "ix_catalog_items_tenant_status",
        "catalog_items",
        ["tenant_id", "status", "category_id", "sort_order"],
    )
    op.create_index(
        "ix_catalog_items_extra_categories",
        "catalog_items",
        ["extra_category_ids"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_catalog_items_tenant_due",
        "catalog_items",
        ["tenant_id", "publish_at", "retire_at"],
        postgresql_where=sa.text(
            "deleted_at IS NULL AND (publish_at IS NOT NULL OR retire_at IS NOT NULL)"
        ),
    )

    op.create_table(
        "catalog_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("starter_seeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "hide_default_incident_template",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_catalog_settings"),
    )
    enable_tenant_rls("catalog_settings")
    enable_actor_audit("catalog_settings")
    grant_app("catalog_settings", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Remove what upgrade added (0074's data step is reversed by 0074 first)."""
    op.drop_table("catalog_settings")
    op.drop_index("ix_catalog_items_tenant_due", table_name="catalog_items")
    op.drop_index("ix_catalog_items_extra_categories", table_name="catalog_items")
    op.drop_index("ix_catalog_items_tenant_status", table_name="catalog_items")
    op.drop_index("ix_catalog_items_search_name", table_name="catalog_items")
    op.drop_index("ix_catalog_items_search", table_name="catalog_items")
    op.drop_column("catalog_items", "search_name")
    op.drop_column("catalog_items", "search_vector")
    op.drop_constraint("fk_catalog_items_owner_id_users", "catalog_items", type_="foreignkey")
    op.drop_constraint(
        "fk_catalog_items_template_id_work_item_templates", "catalog_items", type_="foreignkey"
    )
    for name in ("extra_categories", "texts_object", "kind_code", "status_code"):
        op.drop_constraint(op.f(f"ck_catalog_items_{name}"), "catalog_items", type_="check")
    for name in (
        "extra_category_ids",
        "requesters_see_approval",
        "subject_template",
        "sort_order",
        "featured",
        "owner_id",
        "icon",
        "keywords",
        "summaries",
        "template_id",
        "kind",
        "published_at",
        "retire_at",
        "publish_at",
        "status",
    ):
        op.drop_column("catalog_items", name)
    op.drop_index("ix_service_categories_tenant_parent", table_name="service_categories")
    op.drop_constraint(
        "fk_service_categories_parent_id_service_categories",
        "service_categories",
        type_="foreignkey",
    )
    for name in ("enabled", "descriptions", "icon", "parent_id"):
        op.drop_column("service_categories", name)
    op.execute("DROP FUNCTION catalog_word_lists(jsonb)")
    op.execute("DROP FUNCTION catalog_texts(jsonb)")
