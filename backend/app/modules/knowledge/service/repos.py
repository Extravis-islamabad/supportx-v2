"""Repositories of the knowledge tables (the session's tenant; versioned writes)."""

import uuid

from sqlalchemy import select, update

from app.core.errors import NotFound
from app.modules.knowledge.infra.models import KbArticle, KbArticleVersion, KbReview, KbTopic
from app.shared.db.repository import Repository
from app.shared.history.conflicts import stale_version


class TopicRepository(Repository[KbTopic]):
    """Topics."""

    model = KbTopic


class ArticleRepository(Repository[KbArticle]):
    """Articles."""

    model = KbArticle

    async def restore(self, entity_id: uuid.UUID, *, expected_version: int) -> KbArticle:
        """Bring a deleted article back from the trash (REQ-KB-079); If-Match as for updates."""
        statement = (
            update(KbArticle)
            .where(
                KbArticle.id == entity_id,
                KbArticle.version == expected_version,
                KbArticle.deleted_at.is_not(None),
            )
            .values(
                deleted_at=None,
                version=KbArticle.version + 1,
                updated_at=self.clock.now(),
                updated_by=self.context.user_id,
            )
            .returning(KbArticle)
            .execution_options(populate_existing=True, synchronize_session=False)
        )
        restored: KbArticle | None = await self.session.scalar(statement)
        if restored is not None:
            return restored
        current = await self.session.scalar(
            select(KbArticle).where(KbArticle.id == entity_id, KbArticle.deleted_at.is_not(None))
        )
        if current is None:
            raise NotFound(code="kb_article_not_found")
        raise await stale_version(self.session, current, expected_version=expected_version)


class VersionRepository(Repository[KbArticleVersion]):
    """Article versions (drafts are edited in place, with If-Match)."""

    model = KbArticleVersion


class ReviewRepository(Repository[KbReview]):
    """Reviews ("still correct"), append only."""

    model = KbReview
