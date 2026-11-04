"""Knowledge search over the WP-027 port (REQ-KB-053) and the words suggestions use (REQ-KB-062).

The port's predicate is added to the article list's own query, after the reader's audience, so
search, suggestions and "popular" can never show an article the list would not (REQ-KB-048).

The searchable text is the version's (title, keywords and body, indexed) plus its topic's names
in every language at a lower weight, so "printer" finds an article in topic "Printers" whose
text never says it (AC2). The topic part is computed at query time: a generated column cannot
read another table; knowledge holds thousands of articles per tenant, not millions.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Float, case, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.domain.snippets import MARK_END, MARK_START, SnippetPart, split_marks
from app.modules.knowledge.infra.models import KbArticleVersion, KbTopic
from app.shared.search import ENGINE, Match, SearchDocument, words

_VERSION = KbArticleVersion.__table__.c
TEXT = SearchDocument(
    vector=_VERSION.search_vector.op("||")(func.kb_topic_search_vector(KbTopic.names)),
    short_text=_VERSION.search_title,
)
# Suggestions read a subject and a description: any word may match, the longest words first.
SUGGEST_WORDS = 8
SUGGEST_MIN_WORD = 3
_SIMPLE: ColumnElement[Any] = literal_column("'simple'::regconfig")
_HEADLINE = (
    f"StartSel={MARK_START}, StopSel={MARK_END}, MaxFragments=2, MaxWords=24, MinWords=8, "
    'FragmentDelimiter=" … "'
)
# The body as text: tags and entities become spaces (as in the index); the mark characters
# are removed so only the database's marks remain.
_PLAIN = func.translate(
    func.regexp_replace(_VERSION.body_html, "<[^>]*>|&[a-zA-Z0-9#]+;", " ", "g"),
    MARK_START + MARK_END,
    "",
)


def _suggest_words(text: str) -> list[str]:
    """The distinct words worth matching on, longest first (short ones only if nothing else)."""
    typed = list(dict.fromkeys(words(text)))
    long_words = [w for w in typed if len(w) >= SUGGEST_MIN_WORD]
    chosen = long_words or typed
    return sorted(chosen, key=len, reverse=True)[:SUGGEST_WORDS]


async def text_match(session: AsyncSession, query: str, *, any_word: bool = False) -> Match | None:
    """Rows matching `query`: every word (search), or any word ranked by how many (suggestions)."""
    if not any_word:
        return await ENGINE.match(session, TEXT, query)
    matches = [m for w in _suggest_words(query) if (m := await ENGINE.match(session, TEXT, w))]
    if not matches:
        return None
    rank = sum(
        (case((m.predicate, m.rank + 1.0), else_=0.0) for m in matches),
        start=literal_column("0.0", Float),
    )
    return Match(predicate=or_(*(m.predicate for m in matches)), rank=rank)


async def snippets(
    session: AsyncSession, version_ids: Sequence[uuid.UUID], query: str
) -> dict[uuid.UUID, list[SnippetPart]]:
    """Highlighted snippets of the given versions' bodies, for the page of results only."""
    typed = words(query)
    if not typed or not version_ids:
        return {}
    # `words()` keeps letters and digits only: no quoting needed inside the tsquery.
    terms = " | ".join(f"'{w}':*" for w in typed)
    headline = func.ts_headline(_SIMPLE, _PLAIN, func.to_tsquery(_SIMPLE, terms), _HEADLINE)
    rows = await session.execute(
        select(KbArticleVersion.id, headline).where(KbArticleVersion.id.in_(list(version_ids)))
    )
    found: dict[uuid.UUID, list[SnippetPart]] = {}
    for version_id, text in rows.all():
        parts = split_marks(" ".join(str(text).split()))
        if any(p.mark for p in parts):
            found[version_id] = parts
    return found
