"""Search work items, for pickers and quick search (WP-027, REQ-INC-085, ADR-029).

Search starts from the list's own query (`staff_rows`: type, not deleted, the view scope with the
unassigned site queue and followers, D-052, D-068), so it can never show a record the list would
not. On top of it, a record matches when any of these does:
- its display ID ("INC-12", "inc-12", "12", also typed with Arabic or Urdu digits), whatever its
  status or assignee; an exact ID always ranks first;
- its subject and description words (prefixes, English and Arabic word forms, Urdu prefixes;
  typos in the subject);
- its requester's or on-behalf-of person's name or email.
"""

import uuid
from collections.abc import Collection, Sequence

from sqlalchemy import ColumnElement, and_, case, false, literal, or_, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject, people_matching
from app.modules.work_items.domain.types import WorkItemType, parse_display_id
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service.work_items import staff_rows
from app.shared.search import ENGINE, SearchDocument, normalize

_COLUMNS = WorkItem.__table__.c
TEXT = SearchDocument(vector=_COLUMNS.search_vector, short_text=_COLUMNS.search_subject)
# An exact display ID outranks any text match; a requester match outranks weak text matches.
ID_RANK = 100.0
PERSON_RANK = 0.3
MAX_RESULTS = 50


async def _id_match(session: AsyncSession, wtype: WorkItemType, text: str) -> ColumnElement[bool]:
    cat = await config.load(session, wtype)
    prefix, number = parse_display_id(normalize(text), cat.prefix)
    if number is None:
        return false()
    # Like lookup: the current prefix, or the one the record was created with (renames).
    known_prefix = (
        true()
        if prefix is None or prefix == cat.prefix
        else WorkItem.display_id.startswith(f"{prefix}-")
    )
    return and_(WorkItem.display_number == number, known_prefix)


async def search(  # noqa: PLR0913 - the query and its narrowing options, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    text: str | None,
    *,
    status_categories: Collection[str] = (),
    requester_id: uuid.UUID | None = None,
    ids: Sequence[uuid.UUID] | None = None,
    limit: int = 20,
) -> list[WorkItem]:
    """Records the subject may see, best match first (or most recently updated without text).

    `ids` narrows to those records (recently viewed ones, kept in the browser); records the
    subject can no longer see are left out silently, like everywhere else.
    """
    statement = staff_rows(subject, wtype)
    if status_categories:
        statement = statement.where(WorkItem.status_category.in_(list(status_categories)))
    if requester_id is not None:
        statement = statement.where(WorkItem.requester_id == requester_id)
    if ids is not None:
        statement = statement.where(WorkItem.id.in_(list(ids)))
    limit = max(1, min(limit, MAX_RESULTS))
    if not text:
        rows = await session.scalars(
            statement.order_by(WorkItem.updated_at.desc(), WorkItem.id).limit(limit)
        )
        return list(rows)
    by_id = await _id_match(session, wtype, text)
    words = await ENGINE.match(session, TEXT, text)
    people = await people_matching(session, text)
    by_person = (
        or_(WorkItem.requester_id.in_(people), WorkItem.on_behalf_of_id.in_(people))
        if people
        else false()
    )
    matches = [by_id, by_person] + ([words.predicate] if words is not None else [])
    rank = (
        case((by_id, ID_RANK), else_=0.0)
        + case((by_person, PERSON_RANK), else_=0.0)
        + (words.rank if words is not None else literal(0.0))
    )
    rows = await session.scalars(
        statement.where(or_(*matches))
        .order_by(rank.desc(), WorkItem.updated_at.desc(), WorkItem.id)
        .limit(limit)
    )
    return list(rows)
