"""Whether an article helped its reader (REQ-KB-069, D-125).

One vote per person and published version, changed in place (AC2): the vote stays with its
version, so a new version starts at zero and history keeps each version's score (AC3). Anyone
who may read the article may vote; the scores and the feedback (reasons and comments, never who)
are for those who may change or approve it, never for requesters. `KbVoteSaved` refreshes the
counts live on the article's channel (AC4).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.knowledge.events import KbVoteSaved
from app.modules.knowledge.infra.models import VOTE_REASONS, KbArticleVersion, KbVote
from app.modules.knowledge.service.articles import ArticleView, get_article
from app.shared.events import record_event

COMMENT_MAX = 1000


def _problem(*, field: str, code: str) -> ValidationFailed:
    return ValidationFailed(
        errors=[FieldError(field=f"body.{field}", code=code, message_key=f"errors.field.{code}")]
    )


async def save_vote(  # noqa: PLR0913 - the vote, explicit
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    *,
    version_id: uuid.UUID,
    helpful: bool,
    reason: str | None,
    comment: str | None,
    now: datetime,
) -> KbVote:
    """The reader's vote on the published version they read; voting again changes it."""
    if subject.user_id is None:
        raise PermissionDenied(code="permission_denied")
    view = await get_article(session, subject, article_id)  # the article page's own rule
    if version_id not in {v.id for v in view.published.values()}:
        # Only what readers see now: never a draft, never a version replaced since.
        raise NotFound(code="kb_version_not_published")
    if helpful and reason is not None:
        raise _problem(field="reason", code="kb_vote_reason_for_no_only")
    if reason is not None and reason not in VOTE_REASONS:
        raise _problem(field="reason", code="kb_vote_reason_unknown")
    text = (comment or "").strip() or None
    if text is not None and len(text) > COMMENT_MAX:
        raise _problem(field="comment", code="kb_vote_comment_too_long")
    values = {
        "tenant_id": view.article.tenant_id,
        "article_id": article_id,
        "version_id": version_id,
        "person_id": subject.user_id,
        "helpful": helpful,
        "reason": None if helpful else reason,
        "comment": text,
    }  # created_by and updated_by: the actor trigger (migration helpers)
    statement = (
        insert(KbVote)
        .values(id=uuid.uuid4(), **values)
        .on_conflict_do_update(
            index_elements=["tenant_id", "version_id", "person_id"],
            set_={
                "helpful": values["helpful"],
                "reason": values["reason"],
                "comment": values["comment"],
                "updated_at": now,
                "version": KbVote.version + 1,
            },
        )
        .returning(KbVote.id)
    )
    vote_id = (await session.execute(statement)).scalar_one()
    await record_event(
        session,
        KbVoteSaved(article_id=article_id, version_id=version_id),
        aggregate_id=article_id,
    )
    vote = await session.get(KbVote, vote_id, populate_existing=True)
    assert vote is not None  # noqa: S101 - just written in this transaction
    return vote


async def my_vote(session: AsyncSession, subject: Subject, view: ArticleView) -> KbVote | None:
    """The reader's own vote on a published version of the article, if any."""
    if subject.user_id is None or not view.published:
        return None
    return await session.scalar(
        select(KbVote).where(
            KbVote.version_id.in_([v.id for v in view.published.values()]),
            KbVote.person_id == subject.user_id,
        )
    )


@dataclass(frozen=True)
class VersionScore:
    """Helpful and not helpful for one version."""

    version_id: uuid.UUID
    language: str
    number: int
    helpful: int
    not_helpful: int


@dataclass(frozen=True)
class Feedback:
    """One "no" with what the reader said (never who)."""

    version_number: int
    language: str
    reason: str | None
    comment: str | None
    at: datetime


def _may_see_scores(view: ArticleView) -> bool:
    """Those who may change or approve the article; requesters never (they are not staff)."""
    return view.can_edit or view.can_approve


async def scores(
    session: AsyncSession, subject: Subject, article_id: uuid.UUID
) -> tuple[list[VersionScore], list[Feedback]]:
    """Every version's score, newest first, and the "no" answers with a reason or comment."""
    view = await get_article(session, subject, article_id)
    if not _may_see_scores(view):
        raise PermissionDenied(code="permission_denied")
    counted = (
        select(
            KbArticleVersion.id,
            KbArticleVersion.language,
            KbArticleVersion.number,
            func.count().filter(KbVote.helpful.is_(True)),
            func.count().filter(KbVote.helpful.is_(False)),
        )
        .join(KbVote, KbVote.version_id == KbArticleVersion.id)
        .where(KbArticleVersion.article_id == article_id)
        .group_by(KbArticleVersion.id, KbArticleVersion.language, KbArticleVersion.number)
        .order_by(KbArticleVersion.number.desc(), KbArticleVersion.language)
    )
    by_version = [
        VersionScore(version_id, language, number, helpful, not_helpful)
        for version_id, language, number, helpful, not_helpful in (
            await session.execute(counted)
        ).all()
    ]
    said = (
        select(KbArticleVersion.number, KbArticleVersion.language, KbVote)
        .join(KbVote, KbVote.version_id == KbArticleVersion.id)
        .where(
            KbVote.article_id == article_id,
            KbVote.helpful.is_(False),
            (KbVote.reason.is_not(None)) | (KbVote.comment.is_not(None)),
        )
        .order_by(KbVote.updated_at.desc())
        .limit(200)
    )
    feedback = [
        Feedback(number, language, vote.reason, vote.comment, vote.updated_at)
        for number, language, vote in (await session.execute(said)).all()
    ]
    return by_version, feedback


def current_score(view: ArticleView, by_version: Sequence[VersionScore]) -> tuple[int, int]:
    """Helpful and not helpful over the versions readers see now."""
    current = {v.id for v in view.published.values()}
    shown = [s for s in by_version if s.version_id in current]
    return sum(s.helpful for s in shown), sum(s.not_helpful for s in shown)
