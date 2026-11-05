"""Known errors (WP-044b s3; REQ-PRB-036, -037, -038, -042).

- `mark` / `unmark`: the flag, with `problems.mark_known_error`. Marking needs a workaround or
  a root cause written first (Appendix A default), and the refusal names what is missing.
  Removing the flag needs a reason. Both are in history with the comment or reason.
- `retire_on_resolve`: resolving a known error retires it (the closing step sets the time).
- `database`: the known error database, the flagged problems the subject may see, searched in
  their subject, symptoms and workaround (never the root cause, D-140 Q7). Retired ones stay,
  marked, and each carries its live count of caused incidents.
- `suggestions`: open known errors whose words match an incident's text, for that incident's
  technician. Only problems they may see, never the root cause.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied
from app.modules.identity_access import Subject
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.plain import plain_text
from app.modules.work_items.domain.types import INCIDENT, PROBLEM
from app.modules.work_items.infra.models import WorkItem, WorkItemLink
from app.modules.work_items.service import work_items as items
from app.shared.history import Source
from app.shared.richtext import is_blank

MARK = "mark_known_error"
DATABASE_LIMIT = 100
SUGGESTION_LIMIT = 5
WORDS_MIN = 3  # shorter texts match almost anything


async def _for_marking(session: AsyncSession, subject: Subject, problem_id: uuid.UUID) -> WorkItem:
    record = await items.visible_record(session, subject, PROBLEM, problem_id)
    if not await items.may(session, subject, PROBLEM, MARK, record.id):
        raise PermissionDenied(
            params={"permission": PROBLEM.permission(MARK), "reason": "no_permission"}
        )
    return record


async def mark(  # noqa: PLR0913 - the problem, its version, the comment and the source
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    *,
    expected_version: int,
    comment: str | None,
    source: Source,
) -> WorkItem:
    """Mark it a known error (409 `already_known_error`, 422 naming what must be written)."""
    record = await _for_marking(session, subject, problem_id)
    if record.known_error_at is not None and record.known_error_retired_at is None:
        raise Conflict(code="already_known_error", params={"display_id": record.display_id})
    if is_blank(record.workaround or "") and is_blank(record.root_cause or ""):
        raise items.field_errors(
            [("workaround", "required_for_known_error"), ("root_cause", "required_for_known_error")]
        )
    return await items.set_fields(
        session,
        record,
        {"known_error_at": datetime.now(UTC), "known_error_retired_at": None},
        expected_version=expected_version,
        source=source,
        reason=(comment or "").strip() or None,
    )


async def unmark(  # noqa: PLR0913 - the problem, its version, the reason and the source
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    *,
    expected_version: int,
    reason: str,
    source: Source,
) -> WorkItem:
    """Remove the flag; a reason is required (REQ-PRB-036 AC4)."""
    record = await _for_marking(session, subject, problem_id)
    if not reason.strip():
        raise items.field_errors([("reason", "required")])
    if record.known_error_at is None:
        raise Conflict(code="not_known_error", params={"display_id": record.display_id})
    return await items.set_fields(
        session,
        record,
        {"known_error_at": None, "known_error_retired_at": None},
        expected_version=expected_version,
        source=source,
        reason=reason.strip(),
    )


@dataclass(frozen=True)
class KnownError:
    """One entry of the known error database."""

    record: WorkItem
    incidents: int  # caused incidents (live links), counted whatever the reader may see


def _caused_count() -> object:
    return (
        select(func.count())
        .select_from(WorkItemLink)
        .where(
            WorkItemLink.target_id == WorkItem.id,
            WorkItemLink.kind == LinkKind.CAUSED_BY.value,
            WorkItemLink.deleted_at.is_(None),
        )
        .scalar_subquery()
    )


def _matching(text: str) -> object:
    like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return or_(
        WorkItem.subject.ilike(like, escape="\\"),
        WorkItem.symptoms.ilike(like, escape="\\"),
        WorkItem.workaround.ilike(like, escape="\\"),
    )


async def database(
    session: AsyncSession,
    subject: Subject,
    *,
    search: str,
    include_retired: bool,
) -> list[KnownError]:
    """The known errors the subject may see, newest marking first (≤ DATABASE_LIMIT)."""
    query = (
        items.staff_rows(subject, PROBLEM)
        .where(WorkItem.known_error_at.is_not(None))
        .add_columns(_caused_count())  # type: ignore[arg-type]  # a scalar subquery
        .order_by(WorkItem.known_error_at.desc(), WorkItem.id)
        .limit(DATABASE_LIMIT)
    )
    if not include_retired:
        query = query.where(WorkItem.known_error_retired_at.is_(None))
    if search.strip():
        query = query.where(_matching(search.strip()))  # type: ignore[arg-type]  # a clause
    rows = await session.execute(query)
    return [KnownError(record, int(count or 0)) for record, count in rows]


async def suggestions(
    session: AsyncSession, subject: Subject, incident_id: uuid.UUID
) -> list[KnownError]:
    """Open known errors matching the incident's subject or description (REQ-PRB-038).

    Each word of four letters or more is tried against the known error's subject, symptoms and
    workaround; the best are those matching most words. Only problems the subject may see.
    """
    incident = await items.visible_record(session, subject, INCIDENT, incident_id)
    text = f"{incident.subject} {plain_text(incident.description)}"
    words = sorted({w.lower() for w in text.split() if len(w) > WORDS_MIN and w.isalnum()})[:20]
    if not words:
        return []
    found = await database(session, subject, search="", include_retired=False)
    scored = []
    for entry in found:
        haystack = " ".join(
            plain_text(v)
            for v in (entry.record.subject, entry.record.symptoms, entry.record.workaround)
        ).lower()
        hits = sum(1 for w in words if w in haystack)
        if hits:
            scored.append((hits, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].record.display_id))
    return [entry for _, entry in scored[:SUGGESTION_LIMIT]]
