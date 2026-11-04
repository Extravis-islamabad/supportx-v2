"""Possible duplicates while an incident is being written (WP-038, REQ-INC-022, D-134).

- AI on (plan, switch, the person's permission): open incidents near the text by meaning,
  through the AI gateway's similar search (embeddings; logged as an AI call).
- AI off, or the model failing: trigram similarity of the subject in PostgreSQL (pg_trgm, the
  search index of WP-027), with no model and no gateway call.
- Either way: only open incidents the person may see (the lists' own scope, AC3). The same
  requester's incidents from the last hour are added and weighted up. Five at most, best first.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import Select, func, literal, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai import Gateway
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.plain import plain_text
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import work_items as items
from app.shared.clock import Clock, system_clock

FEATURE = "possible_duplicates"
LIMIT = 5
# Below these, a match is noise: cosine of the embedding model's vectors (unrelated support
# texts score about 0.5 with bge-m3), and pg_trgm's similarity of normalised subjects.
MEANING_MIN = 0.7
TEXT_MIN = 0.3
SAME_REQUESTER_WINDOW = timedelta(hours=1)
SAME_REQUESTER_WEIGHT = 0.2
TEXT_MIN_LENGTH = 6

Method = Literal["meaning", "text"]
Reason = Literal["similar_meaning", "similar_subject", "same_requester"]
_DONE = frozenset({StatusCategory.RESOLVED, *FINAL_CATEGORIES})


@dataclass(frozen=True, slots=True)
class Candidate:
    """An open incident that may be the same issue, and why."""

    record: WorkItem
    score: float
    reasons: tuple[Reason, ...]


def _open(subject: Subject) -> Select[Any]:
    return items.staff_rows(subject, INCIDENT).where(
        WorkItem.status_category.not_in([c.value for c in _DONE])
    )


async def _by_text(session: AsyncSession, subject: Subject, title: str) -> dict[uuid.UUID, float]:
    """Trigram similarity of the subject (no model): the open, visible incidents above TEXT_MIN.

    The `%` operator, so the subject's trigram index serves it (WP-027), with its threshold set
    for this transaction only, as the search engine does.
    """
    await session.execute(
        text("SELECT set_config('pg_trgm.similarity_threshold', :value, true)"),
        {"value": str(TEXT_MIN)},
    )
    # The generated, trigram-indexed subject column (WP-027); not an ORM attribute.
    column = WorkItem.__table__.c.search_subject
    query_text = func.sx_search_normalize(literal(title))
    similarity = func.similarity(column, query_text)
    query = (
        _open(subject)
        .with_only_columns(WorkItem.id, similarity)
        .where(column.op("%")(query_text))
        .order_by(similarity.desc())
        .limit(LIMIT * 2)
    )
    return {record_id: round(float(v), 4) for record_id, v in (await session.execute(query)).all()}


async def _same_requester(
    session: AsyncSession, subject: Subject, requester_id: uuid.UUID, clock: Clock
) -> list[uuid.UUID]:
    since = clock.now() - SAME_REQUESTER_WINDOW
    recent = (
        _open(subject)
        .with_only_columns(WorkItem.id)
        .where(WorkItem.requester_id == requester_id, WorkItem.created_at >= since)
    )
    return [record_id for (record_id,) in (await session.execute(recent)).all()]


async def possible_duplicates(  # noqa: PLR0913 - the draft's parts and the clock, explicit
    session: AsyncSession,
    subject: Subject,
    gateway: Gateway,
    *,
    title: str,
    description: str | None = None,
    requester_id: uuid.UUID | None = None,
    exclude: uuid.UUID | None = None,
    clock: Clock = system_clock,
) -> tuple[list[Candidate], Method]:
    """The open incidents the person may see that look like this draft, and how they were found."""
    text = f"{title}\n{plain_text(description)}".strip()
    scores: dict[uuid.UUID, float] = {}
    reasons: dict[uuid.UUID, list[Reason]] = {}
    method: Method = "text"
    if len(text) >= TEXT_MIN_LENGTH:
        hits = await gateway.similar(
            session,
            subject,
            feature=FEATURE,
            source_type=INCIDENT.code,
            query=text,
            limit=LIMIT * 2,
            exclude=exclude,
        )
        if hits is not None:
            method = "meaning"
            found = {h.source_id: h.score for h in hits if h.score >= MEANING_MIN}
            reason: Reason = "similar_meaning"
        else:
            found = await _by_text(session, subject, title) if title.strip() else {}
            reason = "similar_subject"
        for record_id, value in found.items():
            scores[record_id] = value
            reasons[record_id] = [reason]
    if requester_id is not None:
        for record_id in await _same_requester(session, subject, requester_id, clock):
            scores[record_id] = scores.get(record_id, 0.0) + SAME_REQUESTER_WEIGHT
            reasons.setdefault(record_id, []).append("same_requester")
    if exclude is not None:
        scores.pop(exclude, None)
    if not scores:
        return [], method
    # Only those still open and visible (a meaning hit was checked, but may have closed since).
    records = {
        r.id: r for r in await session.scalars(_open(subject).where(WorkItem.id.in_(list(scores))))
    }
    ranked = sorted(
        (
            Candidate(records[i], round(s, 4), tuple(reasons[i]))
            for i, s in scores.items()
            if i in records
        ),
        key=lambda c: (-c.score, c.record.display_id),
    )
    return ranked[:LIMIT], method
