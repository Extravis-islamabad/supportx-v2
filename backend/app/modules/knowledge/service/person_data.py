"""The knowledge base's slice of a person's erasure (ADR-052 §4; lane C's S2 port).

- **Votes** (with their free-text comments) are deleted: they are the person's own.
- **Topics and articles they own move to the successor** (D4): shared objects are never deleted
  and never left without an owner. What they wrote in articles stays (D1a), shown with the
  erased name.
- **Drafts they never submitted** are their unsent work: the draft's text is blanked and the
  draft soft-deleted. An article left with nothing but such drafts is soft-deleted too.

Batched (ERASE_BATCH rows a call), resumable through the cursor (the phase reached), idempotent:
a second run finds nothing and returns zero counts. Counts only, never data. Each moved or
removed topic or article raises the module's ordinary saved event (rule c).
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import ClassVar

from sqlalchemy import Select, delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import ScalarSelect

from app.modules.identity_access import ERASE_BATCH, ErasureBatch, register_person_data
from app.modules.knowledge.events import KbArticleSaved, KbTopicSaved
from app.modules.knowledge.infra.models import KbArticle, KbArticleVersion, KbTopic, KbVote
from app.shared.events import record_event

# A version's title must not be blank (a check); a removed draft is never shown, so a dash.
ERASED_TITLE = "-"
PHASES = ("votes", "topics", "articles", "drafts", "empty_articles")
KINDS = frozenset(
    {
        "kb_votes_deleted",
        "kb_topics_moved",
        "kb_articles_moved",
        "kb_drafts_removed",
        "kb_articles_removed",
    }
)


def _ids(statement: Select[uuid.UUID]) -> ScalarSelect[uuid.UUID]:
    """A bounded batch of IDs (the subquery a write uses)."""
    return statement.limit(ERASE_BATCH).scalar_subquery()


async def _saved(
    session: AsyncSession,
    rows: Sequence[tuple[uuid.UUID, uuid.UUID, int]],
    owner: uuid.UUID,
    changed: list[str],
) -> None:
    """Each changed article's ordinary saved event, so open screens follow (rule c)."""
    for article_id, topic_id, version in rows:
        await record_event(
            session,
            KbArticleSaved(
                article_id=article_id,
                topic_id=topic_id,
                owner_id=owner,
                language=None,
                created=False,
                changed_fields=changed,
            ),
            aggregate_id=article_id,
            aggregate_version=version,
        )


async def _votes(session: AsyncSession, person: uuid.UUID) -> int:
    batch = _ids(select(KbVote.id).where(KbVote.person_id == person))
    result = await session.execute(delete(KbVote).where(KbVote.id.in_(batch)))
    return int(getattr(result, "rowcount", 0) or 0)


async def _topics(
    session: AsyncSession, person: uuid.UUID, successor: uuid.UUID, now: datetime
) -> int:
    batch = _ids(select(KbTopic.id).where(KbTopic.owner_id == person))
    rows = (
        await session.execute(
            update(KbTopic)
            .where(KbTopic.id.in_(batch))
            .values(owner_id=successor, version=KbTopic.version + 1, updated_at=now)
            .returning(KbTopic.id, KbTopic.version)
            .execution_options(synchronize_session=False)
        )
    ).all()
    for topic_id, version in rows:
        await record_event(
            session,
            KbTopicSaved(topic_id=topic_id, created=False, changed_fields=["owner_id"]),
            aggregate_id=topic_id,
            aggregate_version=version,
        )
    return len(rows)


async def _articles(
    session: AsyncSession, person: uuid.UUID, successor: uuid.UUID, now: datetime
) -> int:
    batch = _ids(select(KbArticle.id).where(KbArticle.owner_id == person))
    rows = (
        await session.execute(
            update(KbArticle)
            .where(KbArticle.id.in_(batch))
            .values(owner_id=successor, version=KbArticle.version + 1, updated_at=now)
            .returning(KbArticle.id, KbArticle.topic_id, KbArticle.version)
            .execution_options(synchronize_session=False)
        )
    ).all()
    await _saved(session, rows, successor, ["owner_id"])
    return len(rows)


async def _drafts(session: AsyncSession, person: uuid.UUID, now: datetime) -> int:
    """Their never-submitted drafts: text blanked, soft-deleted (their unsent work)."""
    batch = _ids(
        select(KbArticleVersion.id).where(
            KbArticleVersion.created_by == person,
            KbArticleVersion.status == "draft",
            KbArticleVersion.submitted_at.is_(None),
            KbArticleVersion.deleted_at.is_(None),
        )
    )
    result = await session.execute(
        update(KbArticleVersion)
        .where(KbArticleVersion.id.in_(batch))
        .values(
            title=ERASED_TITLE,
            body_html="",
            keywords=[],
            change_note=None,
            internal_note=None,
            deleted_at=now,
            updated_at=now,
            version=KbArticleVersion.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _empty_articles(session: AsyncSession, person: uuid.UUID, now: datetime) -> int:
    """Articles they created that now hold no live version at all: soft-deleted with them."""
    live = exists().where(
        KbArticleVersion.article_id == KbArticle.id, KbArticleVersion.deleted_at.is_(None)
    )
    batch = _ids(
        select(KbArticle.id).where(
            KbArticle.created_by == person, KbArticle.deleted_at.is_(None), ~live
        )
    )
    rows = (
        await session.execute(
            update(KbArticle)
            .where(KbArticle.id.in_(batch))
            .values(deleted_at=now, updated_at=now, version=KbArticle.version + 1)
            .returning(KbArticle.id, KbArticle.topic_id, KbArticle.version, KbArticle.owner_id)
            .execution_options(synchronize_session=False)
        )
    ).all()
    for article_id, topic_id, version, owner_id in rows:
        await _saved(session, [(article_id, topic_id, version)], owner_id, ["deleted_at"])
    return len(rows)


class KnowledgeData:
    """knowledge: votes deleted, topics and articles moved, unsent drafts removed (band 500)."""

    module: ClassVar[str] = "knowledge"
    order: ClassVar[int] = 540
    kinds: ClassVar[frozenset[str]] = KINDS

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """One batch of the phase the cursor names (the first when None)."""
        del keep_files  # the knowledge base keeps no uploads of its own (files has its port)
        phase = cursor if cursor in PHASES else PHASES[0]
        if phase == "votes":
            done, kind = await _votes(session, person_id), "kb_votes_deleted"
        elif phase == "topics":
            done, kind = await _topics(session, person_id, successor_id, now), "kb_topics_moved"
        elif phase == "articles":
            done = await _articles(session, person_id, successor_id, now)
            kind = "kb_articles_moved"
        elif phase == "drafts":
            done, kind = await _drafts(session, person_id, now), "kb_drafts_removed"
        else:
            done, kind = await _empty_articles(session, person_id, now), "kb_articles_removed"
        if done >= ERASE_BATCH:
            return ErasureBatch({kind: done}, cursor=phase)  # more of this phase
        following = PHASES.index(phase) + 1
        return ErasureBatch(
            {kind: done}, cursor=PHASES[following] if following < len(PHASES) else None
        )


PORT = KnowledgeData()


def register() -> None:
    """Make the erasure job erase the knowledge base's slice (at module import)."""
    register_person_data(PORT)
