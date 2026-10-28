"""Knowledge (WP-033 session 1; D-108): settings, article types, topics, articles, versions.

Tenant-scoped with RLS. Topics, articles and versions are soft deleted. Published and superseded
versions never change: a trigger refuses any update of their content (REQ-KB-020 AC2). The
reserved `knowledge.manage` grant of custom roles becomes create + edit own + submit (its
nearest meaning in the finer D-108 set): create at the same scope, edit own and submit at `own`.

Revision ID: 0036
Revises: 0035
Created: 2026-10-28
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIENCE = "requesters IN ('none', 'all', 'selected')"
# array_to_string is only STABLE (it is generic over element types); for text[] it is
# deterministic, so this wrapper may be IMMUTABLE and used in the generated search column.
_KEYWORDS = """
CREATE FUNCTION kb_keywords_text(keywords varchar[]) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT array_to_string(keywords, ' ') $$;
"""
_SEARCH = (
    "sx_search_vector(title || ' ' || kb_keywords_text(keywords), "
    "regexp_replace(body_html, '<[^>]*>|&[a-zA-Z0-9#]+;', ' ', 'g'))"
)
_FROZEN = """
CREATE FUNCTION kb_versions_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('published', 'superseded') AND (
        NEW.title IS DISTINCT FROM OLD.title
        OR NEW.body_html IS DISTINCT FROM OLD.body_html
        OR NEW.keywords IS DISTINCT FROM OLD.keywords
        OR NEW.language IS DISTINCT FROM OLD.language
        OR NEW.number IS DISTINCT FROM OLD.number
        OR NEW.article_id IS DISTINCT FROM OLD.article_id
        OR (OLD.status = 'superseded' AND NEW.status IS DISTINCT FROM OLD.status)
    ) THEN
        RAISE EXCEPTION 'a published knowledge version cannot change' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
"""


# role_permissions has FORCE ROW LEVEL SECURITY, so a data step sees rows only with
# app.tenant_id set: it runs once per tenant (the migrator may read every tenant).
_PER_TENANT = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        STATEMENTS
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def _per_tenant(statements: str) -> str:
    return _PER_TENANT.replace("STATEMENTS", statements)


_SPLIT_MANAGE = """
        INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
        SELECT rp.tenant_id, rp.role_id, p.permission, COALESCE(p.scope, rp.scope), rp.condition
        FROM role_permissions rp
        CROSS JOIN (
            VALUES ('knowledge.create', NULL), ('knowledge.edit_own', 'own'),
                ('knowledge.submit', 'own')
        ) AS p(permission, scope)
        WHERE rp.permission = 'knowledge.manage'
        ON CONFLICT DO NOTHING;
        DELETE FROM role_permissions WHERE permission = 'knowledge.manage';
"""

_JOIN_MANAGE = """
        INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
        SELECT DISTINCT ON (tenant_id, role_id) tenant_id, role_id, 'knowledge.manage', scope,
            condition
        FROM role_permissions WHERE permission = 'knowledge.create'
        ON CONFLICT DO NOTHING;
        DELETE FROM role_permissions WHERE permission LIKE 'knowledge.%'
            AND permission NOT IN ('knowledge.view', 'knowledge.manage');
"""


# Any: these lists mix column types (datetime, uuid, int, bool), as op.create_table accepts.
def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _audience() -> list[sa.Column[Any]]:
    uuids = postgresql.ARRAY(sa.Uuid())
    return [
        sa.Column("tech_all", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("tech_groups", uuids, server_default="{}", nullable=False),
        sa.Column("requesters", sa.String(length=10), server_default="none", nullable=False),
        sa.Column("req_groups", uuids, server_default="{}", nullable=False),
        sa.Column("req_sites", uuids, server_default="{}", nullable=False),
        sa.Column("req_departments", uuids, server_default="{}", nullable=False),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.execute(_KEYWORDS)
    op.create_table(
        "kb_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("prefix", sa.String(length=6), server_default="KB", nullable=False),
        sa.Column("self_approval", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("requesters_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("prefix ~ '^[A-Z]{2,6}$'", name=op.f("ck_kb_settings_prefix_format")),
        _tenant_fk("kb_settings"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_kb_settings")),
    )
    enable_tenant_rls("kb_settings")
    grant_app("kb_settings", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "kb_types",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column(
            "names", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("review_months", sa.SmallInteger(), nullable=False),
        sa.Column("builtin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_kb_types_code_format")),
        sa.CheckConstraint(
            "review_months BETWEEN 1 AND 60", name=op.f("ck_kb_types_review_months_range")
        ),
        _tenant_fk("kb_types"),
        sa.PrimaryKeyConstraint("tenant_id", "code", name=op.f("pk_kb_types")),
    )
    enable_tenant_rls("kb_types")
    grant_app("kb_types", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "kb_topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("depth", sa.SmallInteger(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=40), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        *_audience(),
        *_timestamps(),
        sa.CheckConstraint("depth BETWEEN 1 AND 6", name=op.f("ck_kb_topics_depth_range")),
        sa.CheckConstraint(
            "jsonb_typeof(names) = 'object'", name=op.f("ck_kb_topics_names_object")
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 1000",
            name=op.f("ck_kb_topics_description_length"),
        ),
        sa.CheckConstraint(_AUDIENCE, name=op.f("ck_kb_topics_requesters_code")),
        sa.CheckConstraint(
            "tech_all OR cardinality(tech_groups) > 0",
            name=op.f("ck_kb_topics_technicians_not_empty"),
        ),
        _tenant_fk("kb_topics"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["kb_topics.tenant_id", "kb_topics.id"],
            name="fk_kb_topics_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_kb_topics_owner"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_topics")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_kb_topics_tenant_id_id"),
    )
    op.create_index(
        "ix_kb_topics_tenant_parent", "kb_topics", ["tenant_id", "parent_id", "sort_order"]
    )
    enable_tenant_rls("kb_topics")
    enable_actor_audit("kb_topics")
    grant_app("kb_topics", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "kb_articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("display_id", sa.String(length=30), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column("type_code", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("default_language", sa.String(length=5), server_default="en", nullable=False),
        sa.Column("own_audience", sa.Boolean(), server_default="false", nullable=False),
        *_audience(),
        sa.Column("review_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "default_language IN ('en', 'ar')", name=op.f("ck_kb_articles_default_language_code")
        ),
        sa.CheckConstraint(
            f"own_audience = false OR ({_AUDIENCE})", name=op.f("ck_kb_articles_requesters_code")
        ),
        sa.CheckConstraint(
            "expires_on IS NULL OR review_on IS NULL OR expires_on > review_on",
            name=op.f("ck_kb_articles_expiry_after_review"),
        ),
        sa.CheckConstraint(
            "withdrawn_reason IS NULL OR char_length(withdrawn_reason) <= 1000",
            name=op.f("ck_kb_articles_withdrawn_reason_length"),
        ),
        _tenant_fk("kb_articles"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "topic_id"],
            ["kb_topics.tenant_id", "kb_topics.id"],
            name="fk_kb_articles_topic",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type_code"],
            ["kb_types.tenant_id", "kb_types.code"],
            name="fk_kb_articles_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_kb_articles_owner"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_articles")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_kb_articles_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "display_id", name="uq_kb_articles_tenant_display_id"),
    )
    op.create_index(
        "ix_kb_articles_tenant_topic", "kb_articles", ["tenant_id", "topic_id", "updated_at", "id"]
    )
    op.create_index(
        "ix_kb_articles_tenant_owner", "kb_articles", ["tenant_id", "owner_id", "updated_at", "id"]
    )
    op.create_index(
        "ix_kb_articles_tenant_review",
        "kb_articles",
        ["tenant_id", "review_on"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("kb_articles")
    enable_actor_audit("kb_articles")
    grant_app("kb_articles", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "kb_article_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="draft", nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("body_html", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "keywords", postgresql.ARRAY(sa.String(length=60)), server_default="{}", nullable=False
        ),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("self_approved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(_SEARCH, persisted=True),
            nullable=True,
        ),
        sa.Column(
            "search_title",
            sa.Text(),
            sa.Computed("sx_search_normalize(title)", persisted=True),
            nullable=True,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "language IN ('en', 'ar')", name=op.f("ck_kb_article_versions_language_code")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'published', 'superseded', 'rejected')",
            name=op.f("ck_kb_article_versions_status_code"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 250",
            name=op.f("ck_kb_article_versions_title_length"),
        ),
        sa.CheckConstraint(
            "char_length(body_html) <= 500000", name=op.f("ck_kb_article_versions_body_length")
        ),
        sa.CheckConstraint(
            "cardinality(keywords) <= 30", name=op.f("ck_kb_article_versions_keywords_count")
        ),
        sa.CheckConstraint(
            "internal_note IS NULL OR char_length(internal_note) <= 2000",
            name=op.f("ck_kb_article_versions_note_length"),
        ),
        sa.CheckConstraint(
            "change_note IS NULL OR char_length(change_note) <= 500",
            name=op.f("ck_kb_article_versions_change_note_length"),
        ),
        sa.CheckConstraint(
            "reject_reason IS NULL OR char_length(reject_reason) <= 2000",
            name=op.f("ck_kb_article_versions_reject_reason_length"),
        ),
        _tenant_fk("kb_article_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "article_id"],
            ["kb_articles.tenant_id", "kb_articles.id"],
            name="fk_kb_article_versions_article",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_article_versions")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_kb_article_versions_tenant_id_id"),
    )
    op.create_index(
        "uq_kb_versions_published",
        "kb_article_versions",
        ["tenant_id", "article_id", "language"],
        unique=True,
        postgresql_where=sa.text("status = 'published' AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_kb_versions_open",
        "kb_article_versions",
        ["tenant_id", "article_id", "language"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'in_review') AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_kb_versions_tenant_article",
        "kb_article_versions",
        ["tenant_id", "article_id", "language", "number"],
    )
    op.create_index(
        "ix_kb_versions_search",
        "kb_article_versions",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_kb_versions_search_title",
        "kb_article_versions",
        ["search_title"],
        postgresql_using="gin",
        postgresql_ops={"search_title": "gin_trgm_ops"},
    )
    enable_tenant_rls("kb_article_versions")
    enable_actor_audit("kb_article_versions")
    grant_app("kb_article_versions", ("SELECT", "INSERT", "UPDATE"))
    op.execute(_FROZEN)
    op.execute(
        "CREATE TRIGGER kb_versions_frozen BEFORE UPDATE ON kb_article_versions"
        " FOR EACH ROW EXECUTE FUNCTION kb_versions_frozen()"
    )

    # The reserved knowledge.manage (custom roles only; system roles are computed) becomes its
    # nearest D-108 grants: create at its scope, edit own and submit at `own`, their only scope.
    op.execute(_per_tenant(_SPLIT_MANAGE))


def downgrade() -> None:
    op.execute(_per_tenant(_JOIN_MANAGE))
    op.execute("DROP TRIGGER kb_versions_frozen ON kb_article_versions")
    op.execute("DROP FUNCTION kb_versions_frozen()")
    op.drop_table("kb_article_versions")
    op.drop_table("kb_articles")
    op.drop_table("kb_topics")
    op.drop_table("kb_types")
    op.drop_table("kb_settings")
    op.execute("DROP FUNCTION kb_keywords_text(varchar[])")
