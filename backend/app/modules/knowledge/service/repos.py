"""Repositories of the knowledge tables (the session's tenant; versioned writes)."""

from app.modules.knowledge.infra.models import KbArticle, KbArticleVersion, KbTopic
from app.shared.db.repository import Repository


class TopicRepository(Repository[KbTopic]):
    """Topics."""

    model = KbTopic


class ArticleRepository(Repository[KbArticle]):
    """Articles."""

    model = KbArticle


class VersionRepository(Repository[KbArticleVersion]):
    """Article versions (drafts are edited in place, with If-Match)."""

    model = KbArticleVersion
