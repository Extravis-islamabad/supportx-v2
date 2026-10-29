"""Knowledge review: "still correct" history and article files (WP-033 session 2, D-108).

- `kb_reviews`: who checked an article and moved its review date, with no new version
  (REQ-KB-034). Tenant-scoped with RLS.
- `kb_articles.review_reminded_on`: the review date its owner was last reminded of, so the
  hourly sweep reminds once per date (REQ-KB-086). Nullable, no default: expand only.
- Files may belong to a knowledge article (`kb_article` owner type, lane B's files module):
  expand-only, as 0022 did for branding.

Revision ID: 0041
Revises: 0038 (re-chained onto the head of main at merge: lane A's 0039 and 0040 come first)
Created: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0041"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER_TYPES_BEFORE = "owner_type IN ('work_item', 'conversation_entry', 'draft', 'branding')"
OWNER_TYPES_AFTER = (
    "owner_type IN ('work_item', 'conversation_entry', 'draft', 'branding', 'kb_article')"
)

# file_links has FORCE ROW LEVEL SECURITY: a data step sees rows only with app.tenant_id set, so it
# runs once per tenant (D-113; the migrator may read every tenant).
_DROP_ARTICLE_LINKS = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        DELETE FROM file_links WHERE owner_type = 'kb_article';
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    op.create_table(
        "kb_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=False),
        sa.Column("next_review_on", sa.Date(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kb_reviews_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "article_id"],
            ["kb_articles.tenant_id", "kb_articles.id"],
            name="fk_kb_reviews_article",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_reviews")),
    )
    op.create_index(
        op.f("ix_kb_reviews_tenant_id_article_id_created_at"),
        "kb_reviews",
        ["tenant_id", "article_id", "created_at"],
    )
    enable_tenant_rls("kb_reviews")
    enable_actor_audit("kb_reviews")
    grant_app("kb_reviews", ("SELECT", "INSERT"))
    op.add_column("kb_articles", sa.Column("review_reminded_on", sa.Date(), nullable=True))

    op.drop_constraint(op.f("ck_file_links_owner_type"), "file_links", type_="check")
    op.create_check_constraint(op.f("ck_file_links_owner_type"), "file_links", OWNER_TYPES_AFTER)


def downgrade() -> None:
    # Article file links cannot outlive the owner type; the files themselves stay (rule 5h).
    op.execute(_DROP_ARTICLE_LINKS)
    op.drop_constraint(op.f("ck_file_links_owner_type"), "file_links", type_="check")
    op.create_check_constraint(op.f("ck_file_links_owner_type"), "file_links", OWNER_TYPES_BEFORE)
    op.drop_column("kb_articles", "review_reminded_on")
    op.drop_table("kb_reviews")
