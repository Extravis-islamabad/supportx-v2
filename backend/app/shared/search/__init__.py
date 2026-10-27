"""Search: one port, PostgreSQL full-text and pg_trgm for MVP (WP-027, ADR-029, D-085).

See docs/architecture/search.md. Modules describe their searchable columns and add the returned
predicate to their own scope-filtered query; nothing is copied into a separate index.
"""

from app.shared.search.domain import normalize, words
from app.shared.search.ports import Match, SearchDocument, TextSearch
from app.shared.search.postgres import PostgresTextSearch

# The installation's engine. One instance: it holds no state.
ENGINE: TextSearch = PostgresTextSearch()

__all__ = [
    "ENGINE",
    "Match",
    "PostgresTextSearch",
    "SearchDocument",
    "TextSearch",
    "normalize",
    "words",
]
