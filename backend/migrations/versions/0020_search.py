"""Search (WP-027, ADR-029, D-085): PostgreSQL full-text search and pg_trgm.

- Extension pg_trgm (trusted: the migrator, owner of the database, may create it; bootstrap's
  schema.sql creates it too, for new installations).
- sx_search_normalize(text): the search form of a text (Arabic and Urdu letter variants and
  diacritics, accents, case, digits). The same rules as app/shared/search/domain.py; a database
  test checks they agree.
- sx_search_vector(title, body): one tsvector with the simple (prefix), English and Arabic
  forms of the title (weight A) and body (weight B).
- work_items.search_vector (subject and description text) and search_subject (normalised
  subject, for typo tolerance); users.search_vector (name and email) and search_name.
  Generated columns: always current, in the same transaction as the row. GIN indexes.
  (Function bodies name `public.` explicitly: a restore runs with an empty search_path.)

Adding stored generated columns rewrites both tables once (a lock for the duration). Fine at
MVP sizes; at scale this becomes expand/contract with a backfill (docs/architecture/search.md).

Additive and reversible (pg_trgm stays installed on downgrade: other objects may use it).

Revision ID: 0020
Revises: 0019
Created: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of app/shared/search/domain.py MARKS, LETTERS_FROM and LETTERS_TO.
MARKS = "\\u0300-\\u036f\\u0610-\\u061a\\u064b-\\u065f\\u0670\\u06d6-\\u06ed\\u0640\\u200b-\\u200f"
LETTERS_FROM = (
    "\u0671\u0649\u06cc\u06d2\u06a9\u06aa\u06c1\u06be\u06d5\u0629\u06c3"
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
)
LETTERS_TO = "\u0627\u064a\u064a\u064a\u0643\u0643\u0647\u0647\u0647\u0647\u0647" + "0123456789" * 2

NORMALIZE = f"""
CREATE FUNCTION sx_search_normalize(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$
  SELECT translate(
    lower(regexp_replace(normalize(value, NFKD), '[{MARKS}]', '', 'g')),
    '{LETTERS_FROM}',
    '{LETTERS_TO}'
  )
$$
"""

VECTOR = """
CREATE FUNCTION sx_search_vector(title text, body text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
  SELECT setweight(to_tsvector('simple'::regconfig, t), 'A')
      || setweight(to_tsvector('english'::regconfig, t), 'A')
      || setweight(to_tsvector('arabic'::regconfig, t), 'A')
      || setweight(to_tsvector('simple'::regconfig, b), 'B')
      || setweight(to_tsvector('english'::regconfig, b), 'B')
      || setweight(to_tsvector('arabic'::regconfig, b), 'B')
  FROM (
    SELECT coalesce(public.sx_search_normalize(title), '') AS t,
           coalesce(public.sx_search_normalize(body), '') AS b
  ) AS normalised
$$
"""

# Description is sanitised HTML: tags and entities become spaces before indexing.
WORK_ITEM_VECTOR = (
    "sx_search_vector(subject, regexp_replace(description, '<[^>]*>|&[a-zA-Z0-9#]+;', ' ', 'g'))"
)
# Name and email; the email also split at its punctuation, so "ahmed" finds ahmed.ali@x.com.
USER_VECTOR = "sx_search_vector(display_name, email || ' ' || translate(email, '@._-+', '     '))"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(NORMALIZE)
    op.execute(VECTOR)
    op.execute(
        "ALTER TABLE work_items"
        f" ADD COLUMN search_vector tsvector GENERATED ALWAYS AS ({WORK_ITEM_VECTOR}) STORED,"
        " ADD COLUMN search_subject text"
        " GENERATED ALWAYS AS (sx_search_normalize(subject)) STORED"
    )
    op.execute(
        "ALTER TABLE users"
        f" ADD COLUMN search_vector tsvector GENERATED ALWAYS AS ({USER_VECTOR}) STORED,"
        " ADD COLUMN search_name text"
        " GENERATED ALWAYS AS (sx_search_normalize(display_name)) STORED"
    )
    op.execute("CREATE INDEX ix_wi_search_vector ON work_items USING gin (search_vector)")
    op.execute(
        "CREATE INDEX ix_wi_search_subject ON work_items USING gin (search_subject gin_trgm_ops)"
    )
    op.execute("CREATE INDEX ix_users_search_vector ON users USING gin (search_vector)")
    op.execute("CREATE INDEX ix_users_search_name ON users USING gin (search_name gin_trgm_ops)")


def downgrade() -> None:
    op.drop_index("ix_users_search_name", table_name="users")
    op.drop_index("ix_users_search_vector", table_name="users")
    op.drop_index("ix_wi_search_subject", table_name="work_items")
    op.drop_index("ix_wi_search_vector", table_name="work_items")
    op.drop_column("users", "search_name")
    op.drop_column("users", "search_vector")
    op.drop_column("work_items", "search_subject")
    op.drop_column("work_items", "search_vector")
    op.execute("DROP FUNCTION sx_search_vector(text, text)")
    op.execute("DROP FUNCTION sx_search_normalize(text)")
