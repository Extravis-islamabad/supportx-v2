"""Knowledge search, suggestions and votes (WP-034 session 1, D-125).

- `kb_votes`: "Did this help?" (REQ-KB-069). One vote per person and article version, changed in
  place, so a new version starts at zero and the old one keeps its score. Tenant-scoped with RLS.
- `kb_articles.featured`: articles the editors feature in the portal (D-125 Q3).
- `kb_settings.suggest_on_technician_form` and `portal_search` (REQ-KB-062 AC3, REQ-KB-082 AC2).
- `kb_record_links.source` may also be `suggestion` (linked from the create form's suggestions)
  and `report` (an issue reported from a "not helpful" vote, session 2).
- `kb_topic_search_vector(names)`: a topic's names in every language as a low-weight search
  vector, so "printer" finds articles in topic "Printers" (REQ-KB-053 AC2). Evaluated at query
  time: a generated column cannot read another table.

All additive (expand only); the downgrade drops what this adds.

Revision ID: 0050
Revises: 0048 (re-pointed onto the head of main only if the merge queue rejects it)
Created: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0050"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LINK_SOURCES_BEFORE = "source IN ('link', 'insert', 'created_from')"
LINK_SOURCES_AFTER = "source IN ('link', 'insert', 'created_from', 'suggestion', 'report')"
REASONS = (
    "reason IS NULL OR reason IN "
    "('steps_did_not_work', 'out_of_date', 'hard_to_follow', 'not_what_i_needed', 'other')"
)

# jsonb_each_text is deterministic for a given value, so the wrapper may be IMMUTABLE.
_TOPIC_VECTOR = """
CREATE FUNCTION kb_topic_search_vector(names jsonb) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT setweight(
    sx_search_vector(coalesce((SELECT string_agg(value, ' ') FROM jsonb_each_text(names)), ''), ''),
    'C'
  )
$$;
"""

# kb_record_links has FORCE ROW LEVEL SECURITY: the data step runs once per tenant (D-113). A
# downgrade cannot keep a source the old rule refuses: those links are recorded as by hand.
_LINKS_BACK = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE kb_record_links SET source = 'link' WHERE source IN ('suggestion', 'report');
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    op.create_table(
        "kb_votes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(30), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
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
        sa.CheckConstraint(REASONS, name=op.f("ck_kb_votes_reason")),
        sa.CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 1000", name=op.f("ck_kb_votes_comment")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kb_votes_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "article_id"],
            ["kb_articles.tenant_id", "kb_articles.id"],
            name="fk_kb_votes_article",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "version_id"],
            ["kb_article_versions.tenant_id", "kb_article_versions.id"],
            name="fk_kb_votes_version",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_votes")),
    )
    op.create_index(
        "uq_kb_votes_person",
        "kb_votes",
        ["tenant_id", "version_id", "person_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_kb_votes_tenant_id_article_id_created_at"),
        "kb_votes",
        ["tenant_id", "article_id", "created_at"],
    )
    enable_tenant_rls("kb_votes")
    enable_actor_audit("kb_votes")
    grant_app("kb_votes", ("SELECT", "INSERT", "UPDATE"))

    op.add_column(
        "kb_articles",
        sa.Column("featured", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "kb_settings",
        sa.Column(
            "suggest_on_technician_form", sa.Boolean(), server_default="true", nullable=False
        ),
    )
    op.add_column(
        "kb_settings",
        sa.Column("portal_search", sa.Boolean(), server_default="true", nullable=False),
    )
    op.drop_constraint(op.f("ck_kb_record_links_source"), "kb_record_links", type_="check")
    op.create_check_constraint(
        op.f("ck_kb_record_links_source"), "kb_record_links", LINK_SOURCES_AFTER
    )
    op.execute(_TOPIC_VECTOR)


def downgrade() -> None:
    op.execute("DROP FUNCTION kb_topic_search_vector(jsonb)")
    op.execute(_LINKS_BACK)
    op.drop_constraint(op.f("ck_kb_record_links_source"), "kb_record_links", type_="check")
    op.create_check_constraint(
        op.f("ck_kb_record_links_source"), "kb_record_links", LINK_SOURCES_BEFORE
    )
    op.drop_column("kb_settings", "portal_search")
    op.drop_column("kb_settings", "suggest_on_technician_form")
    op.drop_column("kb_articles", "featured")
    op.drop_table("kb_votes")
