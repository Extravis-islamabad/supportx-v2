"""Repeat incident rules without AI (WP-044c S3, D16; REQ-PRB-068).

Admins set rules like "10 or more incidents in the same category and site within 24 hours".
Every 15 minutes, per tenant (app.tenant_id set by the tenant session), the evaluator finds the
sets that match. A new set opens one hit and tells the group (the outbox event the problem
notification source turns into "problem.repeat_detected"); a set that keeps growing joins its
open hit and tells nobody again (AC2) until someone creates a problem from it or dismisses it.
No AI anywhere (AC3).

- One open hit per rule and key, enforced by a unique partial index: two evaluations that
  overlap insert with ON CONFLICT DO NOTHING, so neither opens a second.
- A hit keeps at most REPEAT_MEMBERS_MAX incidents (the newest); its count keeps the total.
- Incidents already caused by a problem are left out: they are handled.
- The feature is the problem module (D-140 item 5: not in Essentials): the schedule skips a
  tenant without it, the API refuses, and the notification says nothing.
- The default rule is made per tenant on first use, like system roles: no data migration.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, literal, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound
from app.modules import licensing
from app.modules.identity_access import Subject
from app.modules.organization import existing_unit_ids
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import INCIDENT, PROBLEM
from app.modules.work_items.events import ProblemRepeatChanged, ProblemRepeatDetected
from app.modules.work_items.infra.models import (
    REPEAT_MATCHES,
    REPEAT_MEMBERS_MAX,
    REPEAT_OUTCOMES,
    ProblemRepeatHit,
    ProblemRepeatHitIncident,
    ProblemRepeatRule,
    WorkItem,
    WorkItemLink,
)
from app.modules.work_items.service import work_items as items
from app.shared.events import record_event
from app.shared.ids import new_id

FEATURE = PROBLEM.feature
DEFAULT_NAME = "Same category and site"  # labelled `repeat_rule.default` in the UI
DEFAULT_RULE: Mapping[str, Any] = {
    "match": "category_site",
    "threshold": 10,
    "window_hours": 24,
}


@dataclass(frozen=True)
class FoundSet:
    """One set of matching incidents now."""

    key: str
    category_id: uuid.UUID
    site_id: uuid.UUID | None
    group_id: uuid.UUID | None
    count: int
    first_at: datetime
    last_at: datetime


def match_key(category_id: uuid.UUID, site_id: uuid.UUID | None) -> str:
    """The stable key of a set: its category, and its site when the rule matches on both."""
    return f"category:{category_id}" + (f"|site:{site_id}" if site_id is not None else "")


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


async def entitled(session: AsyncSession) -> bool:
    """Whether the tenant has repeat incident rules (the problem module; D-140 item 5)."""
    return await licensing.has_feature(_tenant(session), FEATURE)


# --- rules ----------------------------------------------------------------------------------


async def ensure_default(session: AsyncSession) -> None:
    """The tenant's default rule, made once (idempotent; the partial unique index decides)."""
    await session.execute(
        insert(ProblemRepeatRule)
        .values(
            id=new_id(),
            tenant_id=_tenant(session),
            name=DEFAULT_NAME,
            is_default=True,
            enabled=True,
            **DEFAULT_RULE,
        )
        .on_conflict_do_nothing(
            index_elements=[ProblemRepeatRule.tenant_id],
            # The index's own predicate, word for word (Postgres matches it as written).
            index_where=text("is_default AND deleted_at IS NULL"),
        )
    )


async def list_rules(session: AsyncSession) -> list[ProblemRepeatRule]:
    """Every live rule, the default first, then by name."""
    await ensure_default(session)
    rows = await session.scalars(
        select(ProblemRepeatRule)
        .where(ProblemRepeatRule.deleted_at.is_(None))
        .order_by(ProblemRepeatRule.is_default.desc(), func.lower(ProblemRepeatRule.name))
    )
    return list(rows)


async def rule_problems(
    session: AsyncSession, values: Mapping[str, Any], *, current: ProblemRepeatRule | None
) -> list[tuple[str, str]]:
    """Field problems of a rule's values (the API's 422)."""
    problems: list[tuple[str, str]] = []
    name = values.get("name", current.name if current else None)
    if name is None or not str(name).strip():
        problems.append(("name", "required"))
    if values.get("match", current.match if current else None) not in REPEAT_MATCHES:
        problems.append(("match", "invalid_choice"))
    group = values.get("notify_group_id")
    if group is not None and not await existing_unit_ids(session, "group", [uuid.UUID(str(group))]):
        problems.append(("notify_group_id", "group_not_found"))
    if name is not None and str(name).strip():
        taken = await session.scalar(
            select(ProblemRepeatRule.id).where(
                func.lower(ProblemRepeatRule.name) == str(name).strip().lower(),
                ProblemRepeatRule.deleted_at.is_(None),
                ProblemRepeatRule.id != (current.id if current else uuid.uuid4()),
            )
        )
        if taken is not None:
            problems.append(("name", "duplicate_name"))
    return problems


async def changed(session: AsyncSession, kind: str, row_id: uuid.UUID, version: int) -> None:
    """The screens' live signal for one rule or hit."""
    await record_event(
        session,
        ProblemRepeatChanged(kind=kind, id=row_id),  # type: ignore[arg-type]  # kind is "rule" | "hit"
        aggregate_id=row_id,
        aggregate_version=version,
    )


# --- evaluation -----------------------------------------------------------------------------


def _caused_already() -> Any:  # noqa: ANN401 - a SQL predicate
    """Incidents a problem already causes (handled: never counted again)."""
    return (
        select(literal(1))
        .where(
            WorkItemLink.source_id == WorkItem.id,
            WorkItemLink.kind == LinkKind.CAUSED_BY.value,
            WorkItemLink.deleted_at.is_(None),
        )
        .exists()
    )


async def found_sets(
    session: AsyncSession, rule: ProblemRepeatRule, now: datetime
) -> list[FoundSet]:
    """The rule's sets that reach its threshold now, newest activity first."""
    since = now - timedelta(hours=rule.window_hours)
    by_site = rule.match == "category_site"
    site = WorkItem.site_id if by_site else literal(None)
    conditions = [
        WorkItem.type == INCIDENT.code.value,
        WorkItem.deleted_at.is_(None),
        WorkItem.created_at >= since,
        WorkItem.category_id.is_not(None),
        ~_caused_already(),
    ]
    if by_site:
        conditions.append(WorkItem.site_id.is_not(None))
    keys = [WorkItem.category_id, WorkItem.site_id] if by_site else [WorkItem.category_id]
    rows = await session.execute(
        select(
            WorkItem.category_id,
            site.label("site_id"),
            func.mode().within_group(WorkItem.group_id).label("group_id"),
            func.count().label("n"),
            func.min(WorkItem.created_at),
            func.max(WorkItem.created_at),
        )
        .where(*conditions)
        .group_by(*keys)
        .having(func.count() >= rule.threshold)
        .order_by(func.max(WorkItem.created_at).desc())
    )
    found: list[FoundSet] = []
    for category, site_id, group, n, first, last in rows.all():
        found.append(
            FoundSet(match_key(category, site_id), category, site_id, group, n, first, last)
        )
    return found


async def _members(
    session: AsyncSession, rule: ProblemRepeatRule, found: FoundSet, now: datetime
) -> list[uuid.UUID]:
    since = now - timedelta(hours=rule.window_hours)
    query = select(WorkItem.id).where(
        WorkItem.type == INCIDENT.code.value,
        WorkItem.deleted_at.is_(None),
        WorkItem.created_at >= since,
        WorkItem.category_id == found.category_id,
        ~_caused_already(),
    )
    if found.site_id is not None:
        query = query.where(WorkItem.site_id == found.site_id)
    rows = await session.scalars(
        query.order_by(WorkItem.created_at.desc()).limit(REPEAT_MEMBERS_MAX)
    )
    return list(rows)


async def _new_since_handled(
    session: AsyncSession, rule: ProblemRepeatRule, found: FoundSet
) -> bool:
    """Whether enough incidents came since this key's last handled set (AC2: once per set).

    A dismissed or solved set never comes back on the same incidents; it opens again only
    when the threshold is reached again by incidents created after it was handled.
    """
    handled = await session.scalar(
        select(func.max(ProblemRepeatHit.handled_at)).where(
            ProblemRepeatHit.rule_id == rule.id,
            ProblemRepeatHit.match_key == found.key,
            ProblemRepeatHit.handled_at.is_not(None),
        )
    )
    if handled is None or handled < found.first_at:
        return True
    query = select(func.count()).where(
        WorkItem.type == INCIDENT.code.value,
        WorkItem.deleted_at.is_(None),
        WorkItem.created_at > handled,
        WorkItem.category_id == found.category_id,
        ~_caused_already(),
    )
    if found.site_id is not None:
        query = query.where(WorkItem.site_id == found.site_id)
    return int(await session.scalar(query) or 0) >= rule.threshold


async def _keep_members(
    session: AsyncSession, hit_id: uuid.UUID, incident_ids: Sequence[uuid.UUID]
) -> None:
    """Add members up to the cap (the newest first); the ones there stay."""
    held = int(
        await session.scalar(select(func.count()).where(ProblemRepeatHitIncident.hit_id == hit_id))
        or 0
    )
    room = REPEAT_MEMBERS_MAX - held
    if room <= 0 or not incident_ids:
        return
    await session.execute(
        insert(ProblemRepeatHitIncident)
        .values(
            [
                {"tenant_id": _tenant(session), "hit_id": hit_id, "work_item_id": i}
                for i in incident_ids[:room]
            ]
        )
        .on_conflict_do_nothing()
    )


async def evaluate(session: AsyncSession, now: datetime | None = None) -> int:
    """Run the tenant's enabled rules once; returns how many new hits were opened.

    Idempotent and safe to overlap: an open hit is found by rule and key, and a new one is
    inserted with ON CONFLICT DO NOTHING on the open-hit index, so a second run adds nothing.
    """
    if not await entitled(session):
        return 0
    when = now or datetime.now(UTC)
    opened = 0
    for rule in await list_rules(session):
        if not rule.enabled:
            continue
        for found in await found_sets(session, rule, when):
            group = rule.notify_group_id or found.group_id
            open_hit = await session.scalar(
                select(ProblemRepeatHit).where(
                    ProblemRepeatHit.rule_id == rule.id,
                    ProblemRepeatHit.match_key == found.key,
                    ProblemRepeatHit.handled_at.is_(None),
                    ProblemRepeatHit.deleted_at.is_(None),
                )
            )
            if open_hit is None and not await _new_since_handled(session, rule, found):
                continue  # what made the last set was handled: only new incidents count
            members = await _members(session, rule, found, when)
            if open_hit is not None:  # the set grew: it joins, nobody is told again (AC2)
                if found.count != open_hit.incident_count or found.last_at != open_hit.last_at:
                    open_hit.incident_count = max(found.count, open_hit.incident_count)
                    open_hit.last_at = max(found.last_at, open_hit.last_at)
                    open_hit.version += 1
                    await _keep_members(session, open_hit.id, members)
                    await changed(session, "hit", open_hit.id, open_hit.version)
                continue
            hit_id = new_id()
            inserted = await session.scalar(
                insert(ProblemRepeatHit)
                .values(
                    id=hit_id,
                    tenant_id=_tenant(session),
                    rule_id=rule.id,
                    match_key=found.key,
                    category_id=found.category_id,
                    site_id=found.site_id,
                    group_id=group,
                    incident_count=found.count,
                    first_at=found.first_at,
                    last_at=found.last_at,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ProblemRepeatHit.tenant_id,
                        ProblemRepeatHit.rule_id,
                        ProblemRepeatHit.match_key,
                    ],
                    index_where=text("handled_at IS NULL AND deleted_at IS NULL"),
                )
                .returning(ProblemRepeatHit.id)
            )
            if inserted is None:  # another run opened it first
                continue
            await _keep_members(session, hit_id, members)
            await record_event(
                session,
                ProblemRepeatDetected(
                    hit_id=hit_id, rule_id=rule.id, group_id=group, incident_count=found.count
                ),
                aggregate_id=hit_id,
                aggregate_version=1,
            )
            opened += 1
    return opened


# --- hits -----------------------------------------------------------------------------------


async def open_hits(session: AsyncSession, subject: Subject) -> list[ProblemRepeatHit]:
    """The open hits, newest first, for those who may create problems."""
    if not subject.holds(PROBLEM.permission("create")):
        return []
    rows = await session.scalars(
        select(ProblemRepeatHit)
        .where(ProblemRepeatHit.handled_at.is_(None), ProblemRepeatHit.deleted_at.is_(None))
        .order_by(ProblemRepeatHit.last_at.desc())
    )
    return list(rows)


async def hit_incidents(
    session: AsyncSession, subject: Subject, hit_id: uuid.UUID
) -> list[WorkItem]:
    """The hit's incidents the subject may see (the incidents' own scope applies)."""
    hit = await session.get(ProblemRepeatHit, hit_id)
    if hit is None or hit.deleted_at is not None:
        raise NotFound(code="repeat_hit_not_found")
    ids = list(
        await session.scalars(
            select(ProblemRepeatHitIncident.work_item_id).where(
                ProblemRepeatHitIncident.hit_id == hit_id
            )
        )
    )
    if not ids:
        return []
    rows = await session.scalars(
        items.staff_rows(subject, INCIDENT)
        .where(WorkItem.id.in_(ids))
        .order_by(WorkItem.created_at.desc())
    )
    return list(rows)


async def handle(  # noqa: PLR0913 - the hit, the outcome and who handles it, explicit
    session: AsyncSession,
    subject: Subject,
    hit_id: uuid.UUID,
    *,
    outcome: str,
    expected_version: int,
    problem_id: uuid.UUID | None = None,
) -> ProblemRepeatHit:
    """Mark the hit handled: a problem was created from it, or it was dismissed."""
    if outcome not in REPEAT_OUTCOMES:
        raise items.field_errors([("outcome", "invalid_choice")])
    hit = await session.get(ProblemRepeatHit, hit_id, with_for_update=True)
    if hit is None or hit.deleted_at is not None:
        raise NotFound(code="repeat_hit_not_found")
    if hit.version != expected_version:
        raise Conflict(code="version_conflict")
    if hit.handled_at is not None:
        return hit
    hit.handled_at = datetime.now(UTC)
    hit.handled_by = subject.user_id
    hit.outcome = outcome
    hit.problem_id = problem_id
    hit.version += 1
    await changed(session, "hit", hit.id, hit.version)
    return hit
