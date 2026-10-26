"""PostgreSQL full-text search plus pg_trgm: the MVP engine behind the search port (ADR-029, D-085).

Each typed word matches if any of these does:
- the word as a **prefix** (`simple` dictionary): "comp" finds "computer", and Urdu inflections
  ("کمپیوٹر" finds "کمپیوٹروں"), for which no stemmer exists;
- the word's **English stem** ("printers" finds "printer");
- the word's **Arabic stem** ("طابعة" finds "الطابعات").

A word of three or more letters may instead match the document's short text by **trigram word
similarity** (typos and partial words: "printr" finds "Printer down"). Every typed word must
match, one way or the other (AND), so "printer down" never finds "Printer toner is low". Both
sides are normalised the same way (`domain.normalize`, `sx_search_normalize`).
"""

from functools import reduce
from typing import Any

from sqlalchemy import ColumnElement, and_, func, literal, literal_column, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.search.domain import words
from app.shared.search.ports import Match, SearchDocument

# Below this word similarity a misspelling no longer counts ("printr" vs "printer" is 0.71).
TYPO_THRESHOLD = 0.5
# Trigrams of shorter words match almost anything; prefixes cover them instead.
MIN_TYPO_WORD = 3
_SIMPLE: ColumnElement[Any] = literal_column("'simple'::regconfig")
_ENGLISH: ColumnElement[Any] = literal_column("'english'::regconfig")
_ARABIC: ColumnElement[Any] = literal_column("'arabic'::regconfig")


def _word_query(word: str) -> ColumnElement[Any]:
    # `words()` keeps letters and digits only, so the word needs no escaping inside the quotes.
    prefix = f"'{word}':*" if len(word) > 1 else f"'{word}'"
    return (
        func.to_tsquery(_SIMPLE, prefix)
        .op("||")(func.plainto_tsquery(_ENGLISH, word))
        .op("||")(func.plainto_tsquery(_ARABIC, word))
    )


class PostgresTextSearch:
    """`TextSearch` on PostgreSQL (full-text and pg_trgm)."""

    async def match(
        self, session: AsyncSession, document: SearchDocument, query: str
    ) -> Match | None:
        """Rows where every typed word matches, exactly or with a typo; None if no words."""
        typed = words(query)
        if not typed:
            return None
        if any(len(w) >= MIN_TYPO_WORD for w in typed):
            # The threshold of the `<%` operator (which the trigram index serves), for this
            # transaction only.
            await session.execute(
                text("SELECT set_config('pg_trgm.word_similarity_threshold', :value, true)"),
                {"value": str(TYPO_THRESHOLD)},
            )
        conditions: list[ColumnElement[bool]] = []
        closeness: list[ColumnElement[float]] = []
        for word in typed:
            exact = document.vector.op("@@")(_word_query(word))
            if len(word) < MIN_TYPO_WORD:
                conditions.append(exact)
                continue
            typo = literal(word).op("<%")(document.short_text)
            conditions.append(or_(exact, typo))
            closeness.append(func.word_similarity(literal(word), document.short_text))
        everything = reduce(lambda a, b: a.op("&&")(b), (_word_query(w) for w in typed))
        rank: ColumnElement[float] = func.ts_rank_cd(document.vector, everything)
        if closeness:
            rank = rank + reduce(lambda a, b: a + b, closeness) / len(typed)
        return Match(predicate=and_(*conditions), rank=rank)
