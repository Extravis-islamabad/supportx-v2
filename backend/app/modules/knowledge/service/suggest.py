"""Knowledge suggestions (REQ-KB-062): one service for every entry point (D-125).

The console's new-incident form, the portal's report form and later the chat assistant all ask
here, so a suggestion never shows an article its reader could not open: it is the article list's
own query (`reader_predicate`), published versions only, matching any of the typed words and
ranked by how many match. Drafts and versions in review are never suggested (AC2); category,
service and CI matching is REQ-KB-011 (V1).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.knowledge.service.articles import ArticleRow, list_articles
from app.shared.search import words

MIN_LETTERS = 3  # "pr" matches half the library: wait for a word
DEFAULT_LIMIT = 5


async def suggest(
    session: AsyncSession,
    subject: Subject,
    text: str,
    *,
    language: str,
    limit: int = DEFAULT_LIMIT,
) -> list[ArticleRow]:
    """Published articles this reader may read that match the text, best first."""
    if sum(len(word) for word in words(text)) < MIN_LETTERS:
        return []
    return await list_articles(
        session,
        subject,
        view="published",
        language=language,
        query=text,
        any_word=True,
        limit=limit,
    )
