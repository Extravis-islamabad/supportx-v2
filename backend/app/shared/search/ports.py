"""The search port (ADR-029): how a module asks "which of my records match this text?".

A module describes where its searchable text lives (`SearchDocument`, columns of its own table)
and gets back a `Match`: a SQL predicate and a rank expression. The module adds them to the very
query that lists its records, after its own scope filter, so search can never show a record the
list would not (D-052, architecture.md §11.2): permissions are not copied into an index.

The MVP engine is PostgreSQL full-text search plus pg_trgm (`PostgresTextSearch`). Other engines
plug in behind the same shape:
- OpenSearch (later): the adapter asks OpenSearch for candidate IDs and returns
  `id IN (candidates)` with their order as the rank; the scope filter still runs in PostgreSQL.
- Meaning-based search (WP-038, similar incidents): pgvector in the same database is the first
  option; the predicate and rank are distance expressions over an embedding column, so the scope
  filter stays exact there too.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import ColumnElement, SQLColumnExpression
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class SearchDocument:
    """Where one kind of record keeps its searchable text, in its own table.

    `vector`: a tsvector of everything searchable (weights A for titles, B for bodies).
    `short_text`: the normalised short text people misspell or type in part (a subject, a name),
    for typo tolerance (pg_trgm).
    """

    vector: SQLColumnExpression[Any]
    short_text: SQLColumnExpression[str]


@dataclass(frozen=True)
class Match:
    """Which rows match (`predicate`) and how well (`rank`, higher is better)."""

    predicate: ColumnElement[bool]
    rank: ColumnElement[float]


class TextSearch(Protocol):
    """A search engine behind the port."""

    async def match(
        self, session: AsyncSession, document: SearchDocument, query: str
    ) -> Match | None:
        """Rows of `document` matching `query`, or None when the query has no words to search."""
        ...
