"""Knowledge on incidents (WP-033 session 4, D-121).

- `kb_record_links`: an article linked to a record (an incident), how (`link`, `insert`,
  `created_from`) and by whom. Tenant-scoped with RLS; an unlink is a soft delete, so the history
  keeps it. One live link per article and record.
- `files.copied_from`: the file a copy was made from, when an article's images are copied into a
  reply (lane B's condition), so a later verdict on the source can reach its copies. Nullable:
  expand only.
- `files.source` may be `knowledge` (those copies emit the upload event with that source).

Revision ID: 0048
Revises: 0046 (re-pointed onto the head of main only if the merge queue rejects it)
Created: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0048"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCES_BEFORE = "source IN ('ui', 'api', 'email', 'portal')"
SOURCES_AFTER = "source IN ('ui', 'api', 'email', 'portal', 'knowledge')"

# files has FORCE ROW LEVEL SECURITY: the data step runs once per tenant (D-113). A downgrade
# cannot keep a source the old rule refuses: those copies are recorded as made in the UI.
_SOURCES_BACK = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE files SET source = 'ui' WHERE source = 'knowledge';
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def upgrade() -> None:
    op.create_table(
        "kb_record_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(30), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
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
        sa.CheckConstraint(
            "source IN ('link', 'insert', 'created_from')", name=op.f("ck_kb_record_links_source")
        ),
        sa.CheckConstraint(
            "record_type ~ '^[a-z][a-z_]{1,29}$'", name=op.f("ck_kb_record_links_record_type")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kb_record_links_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "article_id"],
            ["kb_articles.tenant_id", "kb_articles.id"],
            name="fk_kb_record_links_article",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_record_links")),
    )
    op.create_index(
        "uq_kb_record_links_live",
        "kb_record_links",
        ["tenant_id", "article_id", "record_type", "record_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        op.f("ix_kb_record_links_tenant_id_record_type_record_id"),
        "kb_record_links",
        ["tenant_id", "record_type", "record_id"],
    )
    enable_tenant_rls("kb_record_links")
    enable_actor_audit("kb_record_links")
    grant_app("kb_record_links", ("SELECT", "INSERT", "UPDATE"))

    op.add_column("files", sa.Column("copied_from", sa.Uuid(), nullable=True))
    op.drop_constraint(op.f("ck_files_source"), "files", type_="check")
    op.create_check_constraint(op.f("ck_files_source"), "files", SOURCES_AFTER)


def downgrade() -> None:
    op.execute(_SOURCES_BACK)
    op.drop_constraint(op.f("ck_files_source"), "files", type_="check")
    op.create_check_constraint(op.f("ck_files_source"), "files", SOURCES_BEFORE)
    op.drop_column("files", "copied_from")
    op.drop_table("kb_record_links")
