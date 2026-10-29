"""Topics (REQ-KB-003, 004, 044): the tree, its audiences, moves and deletion with a target.

Every write: permission, rules (codes), versioned change, field history, outbox event.
Deleting a topic that holds articles needs a target topic; its articles move there and every
article's history records the new topic (REQ-KB-004 AC1, AC2). Subtopics move with it.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, NotFound, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.knowledge.domain.knowledge import (
    MAX_TOPIC_DEPTH,
    Audience,
    RequesterAudience,
    depth_problem,
)
from app.modules.knowledge.events import KbArticleSaved, KbTopicDeleted, KbTopicSaved
from app.modules.knowledge.infra.models import KbArticle, KbTopic
from app.modules.knowledge.service.access import MANAGE_TOPICS, VIEW, require, staff_sees
from app.modules.knowledge.service.repos import ArticleRepository, TopicRepository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

RECORD_TYPE = "kb_topic"
NAME_MAX = 120
AUDIENCE_FIELDS = (
    "tech_all",
    "tech_groups",
    "requesters",
    "req_groups",
    "req_sites",
    "req_departments",
)
_PLAIN_FIELDS = ("description", "icon", "owner_id", "sort_order")
PARENT_FIELD = "body.parent_id"
MOVE_TO_FIELD = "body.move_to"


def audience_of(values: Mapping[str, Any]) -> Audience:
    """The audience in a request body (missing parts: all technicians, no requesters)."""
    return Audience(
        tech_all=bool(values.get("tech_all", True)),
        tech_groups=frozenset(values.get("tech_groups") or ()),
        requesters=RequesterAudience(values.get("requesters", "none")),
        req_groups=frozenset(values.get("req_groups") or ()),
        req_sites=frozenset(values.get("req_sites") or ()),
        req_departments=frozenset(values.get("req_departments") or ()),
    )


def audience_columns(audience: Audience) -> dict[str, Any]:
    """The columns that store an audience (topics and articles alike)."""
    return {
        "tech_all": audience.tech_all,
        "tech_groups": sorted(audience.tech_groups),
        "requesters": audience.requesters.value,
        "req_groups": sorted(audience.req_groups),
        "req_sites": sorted(audience.req_sites),
        "req_departments": sorted(audience.req_departments),
    }


def check_audience(audience: Audience) -> None:
    """An audience must reach someone (REQ-KB-044, 045)."""
    problems = audience.problems()
    if "technician_audience_empty" in problems:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.tech_groups",
                    code="technician_audience_empty",
                    message_key="errors.field.technician_audience_empty",
                )
            ]
        )
    if "requester_audience_empty" in problems:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.requesters",
                    code="requester_audience_empty",
                    message_key="errors.field.requester_audience_empty",
                )
            ]
        )


def _names(names: Mapping[str, str]) -> dict[str, str]:
    cleaned = {k: v.strip() for k, v in names.items() if v and v.strip()}
    if not cleaned:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.names",
                    code="name_required",
                    message_key="errors.field.name_required",
                )
            ]
        )
    if any(len(v) > NAME_MAX for v in cleaned.values()):
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.names",
                    code="value_too_long_max",
                    message_key="errors.field.value_too_long_max",
                    params={"max_length": NAME_MAX},
                )
            ]
        )
    return cleaned


def _too_deep() -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(
                field="body.parent_id",
                code="topic_too_deep",
                message_key="errors.field.topic_too_deep",
                params={"max": MAX_TOPIC_DEPTH},
            )
        ]
    )


def _under_itself(field: str) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(
                field=field,
                code="topic_under_itself",
                message_key="errors.field.topic_under_itself",
            )
        ]
    )


async def list_topics(session: AsyncSession, subject: Subject) -> Sequence[KbTopic]:
    """Every topic the subject's technician audience reaches, in tree order."""
    require(subject, VIEW)
    return (
        await session.scalars(
            select(KbTopic)
            .where(KbTopic.deleted_at.is_(None), staff_sees(subject, article=False))
            .order_by(KbTopic.depth, KbTopic.sort_order, KbTopic.id)
        )
    ).all()


async def get_topic(session: AsyncSession, subject: Subject, topic_id: uuid.UUID) -> KbTopic:
    """One topic the subject may see; 404 otherwise."""
    require(subject, VIEW)
    found = await session.scalar(
        select(KbTopic).where(
            KbTopic.id == topic_id,
            KbTopic.deleted_at.is_(None),
            staff_sees(subject, article=False),
        )
    )
    if found is None:
        raise NotFound(code="kb_topic_not_found")
    return found


async def _subtree(session: AsyncSession, root: uuid.UUID) -> list[KbTopic]:
    """The topic and every live topic under it."""
    rows = list((await session.scalars(select(KbTopic).where(KbTopic.deleted_at.is_(None)))).all())
    children: dict[uuid.UUID | None, list[KbTopic]] = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row)
    found = [r for r in rows if r.id == root]
    index = 0
    while index < len(found):
        found.extend(children.get(found[index].id, []))
        index += 1
    return found


def _snapshot(topic: KbTopic) -> dict[str, Any]:
    return {
        "names": topic.names,
        "description": topic.description,
        "icon": topic.icon,
        "parent_id": str(topic.parent_id) if topic.parent_id else None,
        "sort_order": topic.sort_order,
        "owner_id": str(topic.owner_id) if topic.owner_id else None,
        "tech_all": topic.tech_all,
        "tech_groups": sorted(str(g) for g in topic.tech_groups),
        "requesters": topic.requesters,
        "req_groups": sorted(str(g) for g in topic.req_groups),
        "req_sites": sorted(str(g) for g in topic.req_sites),
        "req_departments": sorted(str(g) for g in topic.req_departments),
    }


async def create_topic(
    session: AsyncSession,
    subject: Subject,
    values: Mapping[str, Any],
    *,
    source: Source,
) -> KbTopic:
    """A topic at the top or under a parent, in one step (REQ-KB-003 AC1); no icon needed."""
    require(subject, MANAGE_TOPICS)
    names = _names(values["names"])
    audience = audience_of(values)
    check_audience(audience)
    parent_id: uuid.UUID | None = values.get("parent_id")
    depth = 1
    if parent_id is not None:
        parent = await get_topic(session, subject, parent_id)
        if depth_problem(parent.depth):
            raise _too_deep()
        depth = parent.depth + 1
    siblings = KbTopic.parent_id.is_(None) if parent_id is None else KbTopic.parent_id == parent_id
    order = await session.scalar(
        select(func.coalesce(func.max(KbTopic.sort_order), 0) + 1).where(
            siblings, KbTopic.deleted_at.is_(None)
        )
    )
    topic = KbTopic(
        parent_id=parent_id,
        depth=depth,
        sort_order=int(order or 1),
        names=names,
        description=(values.get("description") or "").strip() or None,
        icon=values.get("icon"),
        owner_id=values.get("owner_id"),
        **audience_columns(audience),
    )
    await TopicRepository(session).add(topic)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=topic.id,
        version=topic.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in _snapshot(topic).items()],
        source=source,
    )
    await record_event(
        session,
        KbTopicSaved(topic_id=topic.id, created=True, changed_fields=[]),
        aggregate_id=topic.id,
        aggregate_version=topic.version,
    )
    return topic


async def _move(
    session: AsyncSession, subject: Subject, topic: KbTopic, parent_id: uuid.UUID | None
) -> tuple[dict[str, Any], list[KbTopic]]:
    """The columns of a move under `parent_id`, and the subtree that moves with it."""
    subtree = await _subtree(session, topic.id)
    if parent_id in {t.id for t in subtree}:
        raise _under_itself(PARENT_FIELD)
    parent_depth = 0 if parent_id is None else (await get_topic(session, subject, parent_id)).depth
    height = max(t.depth for t in subtree) - topic.depth + 1
    if depth_problem(parent_depth, height):
        raise _too_deep()
    return {"parent_id": parent_id, "depth": parent_depth + 1}, subtree


async def update_topic(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    topic_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> KbTopic:
    """Rename, describe, reorder, move (with its subtree, ≤ 6 levels) or change the audience."""
    require(subject, MANAGE_TOPICS)
    topic = await get_topic(session, subject, topic_id)
    before = _snapshot(topic)
    columns: dict[str, Any] = {k: values[k] for k in _PLAIN_FIELDS if k in values}
    if "names" in values:
        columns["names"] = _names(values["names"])
    if any(name in values for name in AUDIENCE_FIELDS):
        audience = audience_of({**{k: getattr(topic, k) for k in AUDIENCE_FIELDS}, **values})
        check_audience(audience)
        columns |= audience_columns(audience)
    subtree: list[KbTopic] = []
    if "parent_id" in values and values["parent_id"] != topic.parent_id:
        moved, subtree = await _move(session, subject, topic, values["parent_id"])
        columns |= moved
    columns = {k: v for k, v in columns.items() if getattr(topic, k) != v}
    if not columns:
        return topic
    shift = columns.get("depth", topic.depth) - topic.depth
    updated = await TopicRepository(session).update(
        topic.id, expected_version=expected_version, changes=columns
    )
    others = [t.id for t in subtree if t.id != topic.id]
    if shift and others:
        # Subtopics keep their place in the moved subtree (REQ-KB-004 AC1).
        await session.execute(
            update(KbTopic)
            .where(KbTopic.id.in_(others))
            .values(depth=KbTopic.depth + shift, version=KbTopic.version + 1)
        )
    after = _snapshot(updated)
    changes = [Change(k, before[k], v) for k, v in after.items() if before[k] != v]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        KbTopicSaved(topic_id=updated.id, created=False, changed_fields=[c.field for c in changes]),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return updated


async def _move_articles(
    session: AsyncSession, articles: list[KbArticle], target: uuid.UUID, source: Source
) -> None:
    """Every article to `target`, each with history and an event (REQ-KB-004 AC1, AC2)."""
    for article in articles:
        old = article.topic_id
        moved = await ArticleRepository(session).update(
            article.id, expected_version=article.version, changes={"topic_id": target}
        )
        await record_changes(
            session,
            record_type="kb_article",
            record_id=moved.id,
            version=moved.version,
            kind="updated",
            changes=[Change("topic_id", str(old), str(target))],
            source=source,
        )
        await record_event(
            session,
            KbArticleSaved(
                article_id=moved.id,
                topic_id=target,
                owner_id=moved.owner_id,
                language=None,
                created=False,
                changed_fields=["topic_id"],
            ),
            aggregate_id=moved.id,
            aggregate_version=moved.version,
        )


async def delete_topic(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    topic_id: uuid.UUID,
    *,
    move_to: uuid.UUID | None,
    expected_version: int,
    source: Source,
) -> None:
    """To the trash with its subtopics; their articles move to `move_to` first (REQ-KB-004)."""
    require(subject, MANAGE_TOPICS)
    topic = await get_topic(session, subject, topic_id)
    ids = [t.id for t in await _subtree(session, topic.id)]
    articles = list(
        (
            await session.scalars(
                select(KbArticle).where(KbArticle.topic_id.in_(ids), KbArticle.deleted_at.is_(None))
            )
        ).all()
    )
    if articles:
        if move_to is None:
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="body.move_to",
                        code="move_articles_first",
                        message_key="errors.field.move_articles_first",
                        params={"count": len(articles)},
                    )
                ]
            )
        if move_to in ids:
            raise _under_itself(MOVE_TO_FIELD)
        target = await get_topic(session, subject, move_to)
        await _move_articles(session, articles, target.id, source)
    deleted = await TopicRepository(session).soft_delete(
        topic.id, expected_version=expected_version
    )
    others = [i for i in ids if i != topic.id]
    if others:
        await session.execute(
            update(KbTopic)
            .where(KbTopic.id.in_(others))
            .values(deleted_at=deleted.deleted_at, version=KbTopic.version + 1)
        )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=topic.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        KbTopicDeleted(topic_id=topic.id, moved_to=move_to if articles else None),
        aggregate_id=topic.id,
        aggregate_version=deleted.version,
    )
