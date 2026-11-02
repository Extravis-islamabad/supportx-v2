"""Knowledge on records (WP-033 session 4, D-121; REQ-KB-016, 063, 064).

Two rules meet here and both always apply: the article's reader rule (`get_article`) and the
record owner's read rule (the shared records port, `app/shared/records`). A link is shown only
to someone who may read both ends; the other end is counted ("N restricted"), never named.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.identity_access import Subject, subject_for
from app.modules.knowledge.domain.knowledge import VersionStatus
from app.modules.knowledge.events import KbLinkRemoved, KbLinkSaved
from app.modules.knowledge.infra.models import KbArticle, KbRecordLink
from app.modules.knowledge.service.access import is_staff
from app.modules.knowledge.service.articles import (
    RECORD_TYPE,
    ArticleView,
    get_article,
)
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.records.ports import (
    BATCH_MAX,
    RecordFacts,
    RecordSummary,
    UnknownRecordTypeError,
    record_facts,
)

SOURCES = ("link", "insert", "created_from")


def facts_for(record_type: str) -> RecordFacts:
    """Who answers for the record type; 404 for a type nobody owns (not built yet)."""
    try:
        return record_facts(record_type)
    except UnknownRecordTypeError:
        raise NotFound(code="kb_record_not_found") from None


async def visible_records(
    session: AsyncSession, subject: Subject, record_type: str, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, RecordSummary]:
    """List lines of the records the subject may open, asked in batches the port accepts."""
    facts = facts_for(record_type)
    found: dict[uuid.UUID, RecordSummary] = {}
    unique = list(dict.fromkeys(ids))
    for start in range(0, len(unique), BATCH_MAX):
        found.update(await facts.summaries(session, subject, unique[start : start + BATCH_MAX]))
    return found


async def require_record(
    session: AsyncSession, subject: Subject, record_type: str, record_id: uuid.UUID
) -> None:
    """404 unless the subject may open the record (never says whether it exists)."""
    if record_id not in await facts_for(record_type).visible(session, subject, [record_id]):
        raise NotFound(code="kb_record_not_found")


def require_staff(subject: Subject) -> None:
    """Links are staff work: requesters never link or see links."""
    if not is_staff(subject):
        raise PermissionDenied(params={"permission": "knowledge.view", "reason": "kb_staff_only"})


async def _live(
    session: AsyncSession, article_id: uuid.UUID, record_type: str, record_id: uuid.UUID
) -> KbRecordLink | None:
    found: KbRecordLink | None = await session.scalar(
        select(KbRecordLink).where(
            KbRecordLink.article_id == article_id,
            KbRecordLink.record_type == record_type,
            KbRecordLink.record_id == record_id,
            KbRecordLink.deleted_at.is_(None),
        )
    )
    return found


async def link(  # noqa: PLR0913 - which article, which record, how, explicit
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    *,
    how: str,
    source: Source,
) -> tuple[KbRecordLink, bool]:
    """Link once (a second time changes nothing); the link and whether it is new."""
    require_staff(subject)
    view = await get_article(session, subject, article_id)
    await require_record(session, subject, record_type, record_id)
    existing = await _live(session, article_id, record_type, record_id)
    if existing is not None:
        return existing, False
    row = KbRecordLink(
        tenant_id=subject.tenant_id,
        article_id=article_id,
        record_type=record_type,
        record_id=record_id,
        source=how,
        created_by=subject.user_id,
        updated_by=subject.user_id,
    )
    session.add(row)
    await session.flush()
    await _history(session, view.article, "link_added", row, source)
    await record_event(
        session,
        KbLinkSaved(
            link_id=row.id,
            article_id=article_id,
            record_type=record_type,
            record_id=record_id,
            source=how,
        ),
        aggregate_id=article_id,
    )
    return row, True


async def unlink(
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    link_id: uuid.UUID,
    *,
    source: Source,
) -> None:
    """Remove a link: needs edit rights on the article and sight of the record."""
    require_staff(subject)
    view = await get_article(session, subject, article_id)
    row: KbRecordLink | None = await session.scalar(
        select(KbRecordLink).where(
            KbRecordLink.id == link_id,
            KbRecordLink.article_id == article_id,
            KbRecordLink.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFound(code="kb_link_not_found")
    await require_record(session, subject, row.record_type, row.record_id)
    if not view.can_edit:
        raise PermissionDenied(
            params={"permission": "knowledge.edit_own", "reason": "kb_not_editor"}
        )
    from app.shared.clock import system_clock  # noqa: PLC0415 - one use

    row.deleted_at = system_clock.now()
    row.updated_by = subject.user_id
    await session.flush()
    await _history(session, view.article, "link_removed", row, source)
    await record_event(
        session,
        KbLinkRemoved(
            link_id=row.id,
            article_id=article_id,
            record_type=row.record_type,
            record_id=row.record_id,
        ),
        aggregate_id=article_id,
    )


async def _history(
    session: AsyncSession, article: KbArticle, kind: str, row: KbRecordLink, source: Source
) -> None:
    # The article's history names the link (record type and id), never the record's subject.
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=article.id,
        version=article.version,
        kind="child_added" if kind == "link_added" else "child_removed",
        changes=[
            Change(
                "record_link",
                None if kind == "link_added" else f"{row.record_type}:{row.record_id}",
                f"{row.record_type}:{row.record_id}" if kind == "link_added" else None,
            )
        ],
        source=source,
    )


@dataclass(frozen=True)
class ArticleLinks:
    """An article's links as one reader sees them."""

    shown: list[tuple[KbRecordLink, RecordSummary]]
    restricted: int


async def article_links(
    session: AsyncSession, subject: Subject, article_id: uuid.UUID
) -> ArticleLinks:
    """The records linked to the article that the reader may open, and how many others."""
    require_staff(subject)
    await get_article(session, subject, article_id)
    rows = list(
        await session.scalars(
            select(KbRecordLink)
            .where(KbRecordLink.article_id == article_id, KbRecordLink.deleted_at.is_(None))
            .order_by(KbRecordLink.created_at.desc())
        )
    )
    shown: list[tuple[KbRecordLink, RecordSummary]] = []
    for record_type in sorted({r.record_type for r in rows}):
        of_type = [r for r in rows if r.record_type == record_type]
        seen = await visible_records(session, subject, record_type, [r.record_id for r in of_type])
        shown += [(r, seen[r.record_id]) for r in of_type if r.record_id in seen]
    return ArticleLinks(shown, len(rows) - len(shown))


@dataclass(frozen=True)
class RecordArticles:
    """A record's linked articles as one reader sees them."""

    shown: list[tuple[KbRecordLink, ArticleView]]
    restricted: int


async def record_articles(
    session: AsyncSession, subject: Subject, record_type: str, record_id: uuid.UUID
) -> RecordArticles:
    """The articles linked to the record that the reader may read, and how many others."""
    await require_record(session, subject, record_type, record_id)
    rows = list(
        await session.scalars(
            select(KbRecordLink)
            .where(
                KbRecordLink.record_type == record_type,
                KbRecordLink.record_id == record_id,
                KbRecordLink.deleted_at.is_(None),
            )
            .order_by(KbRecordLink.created_at.desc())
        )
    )
    shown: list[tuple[KbRecordLink, ArticleView]] = []
    for row in rows:
        try:
            shown.append((row, await get_article(session, subject, row.article_id)))
        except NotFound:
            continue
    return RecordArticles(shown, len(rows) - len(shown))


async def visible_to_people(
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
) -> bool:
    """Whether everyone the record is for may read the article now (D-108 (3)).

    The server's answer, never the browser's: each person's own reader rule (published, their
    audience, requester knowledge on), as `get_article` applies it to them.
    """
    people = await facts_for(record_type).requester_of(session, subject, record_id)
    if people is None:
        raise NotFound(code="kb_record_not_found")
    for person in people.ids:
        reader = await subject_for(session, subject.tenant_id, person)
        try:
            view = await get_article(session, reader, article_id)
        except (NotFound, PermissionDenied):
            return False
        if not any(v.status == VersionStatus.PUBLISHED for v in view.published.values()):
            return False
    return True
