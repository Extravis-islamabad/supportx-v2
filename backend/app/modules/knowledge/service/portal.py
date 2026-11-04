"""What the portal's knowledge area reads (REQ-KB-081, D-125); its pages come with WP-028.

Built and tested before the portal exists, so session 2 only adds screens. Everything here goes
through the article list's own reader rule. While requester knowledge is switched off, every
requester call answers 404 (AC2): not an empty page that hints at hidden articles.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.identity_access import Subject
from app.modules.knowledge.domain.knowledge import VersionStatus
from app.modules.knowledge.infra.models import KbArticle, KbArticleVersion, KbTopic
from app.modules.knowledge.service.access import is_staff
from app.modules.knowledge.service.articles import (
    ArticleRow,
    list_articles,
    reader_predicate,
    settings_row,
)

HOME_LIST = 5


async def _open_to(session: AsyncSession, subject: Subject) -> None:
    """404 for requesters while requester knowledge is off (REQ-KB-081 AC2)."""
    if not is_staff(subject) and not (await settings_row(session)).requesters_enabled:
        raise NotFound(code="kb_requesters_off")


@dataclass(frozen=True)
class PortalTopic:
    """A topic that holds at least one article this reader may read, and how many."""

    topic: KbTopic
    articles: int


async def topics(session: AsyncSession, subject: Subject) -> list[PortalTopic]:
    """Only topics with something this reader may open (AC1), in tree order."""
    await _open_to(session, subject)
    reader = await reader_predicate(session, subject)
    counted = (
        select(KbTopic, func.count(func.distinct(KbArticle.id)))
        .join(
            KbArticle,
            and_(KbArticle.topic_id == KbTopic.id, KbArticle.tenant_id == KbTopic.tenant_id),
        )
        .join(
            KbArticleVersion,
            and_(
                KbArticleVersion.article_id == KbArticle.id,
                KbArticleVersion.tenant_id == KbArticle.tenant_id,
                KbArticleVersion.deleted_at.is_(None),
                KbArticleVersion.status == VersionStatus.PUBLISHED.value,
            ),
        )
        .where(KbTopic.deleted_at.is_(None), KbArticle.deleted_at.is_(None), reader)
        .group_by(KbTopic.id)
        .order_by(KbTopic.depth, KbTopic.sort_order, KbTopic.id)
    )
    return [PortalTopic(topic, count) for topic, count in (await session.execute(counted)).all()]


@dataclass(frozen=True)
class PortalHome:
    """The knowledge area's three lists (REQ-KB-081)."""

    recent: Sequence[ArticleRow]
    popular: Sequence[ArticleRow]
    featured: Sequence[ArticleRow]


async def home(
    session: AsyncSession, subject: Subject, *, language: str, topic_id: uuid.UUID | None = None
) -> PortalHome:
    """Recently updated, popular (D-125 Q1) and featured (Q3) articles this reader may read."""
    await _open_to(session, subject)

    async def one(*, order: str = "recent", featured: bool | None = None) -> list[ArticleRow]:
        return await list_articles(
            session,
            subject,
            view="published",
            language=language,
            topic_id=topic_id,
            limit=HOME_LIST,
            order=order,
            featured=featured,
        )

    return PortalHome(
        recent=await one(),
        popular=await one(order="popular"),
        featured=await one(featured=True),
    )
