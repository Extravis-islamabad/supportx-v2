"""When an article's owner is deactivated, the topic owner takes over (REQ-KB-033 AC2).

A consumer of identity's `identity_access.user.status_changed`: for a person who became
`disabled`, each of their live articles moves to its topic's owner, with history (source
`system`) and a `knowledge.article.saved` event, so lists and pages update live. Articles whose
topic has no owner (or whose topic owner is the same person) keep their owner; the list's owner
filter finds them. Idempotent: a second delivery finds nothing left to move.
"""

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.knowledge.infra.models import KbArticle, KbTopic
from app.modules.knowledge.service.articles import RECORD_TYPE, saved_event
from app.modules.knowledge.service.repos import ArticleRepository
from app.shared.events import ConsumerSpec, EventEnvelope
from app.shared.history import Change, record_changes

log = get_logger(__name__)


async def hand_over(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Move a deactivated person's articles to their topics' owners; how many moved."""
    rows = (
        await session.execute(
            select(KbArticle, KbTopic.owner_id)
            .join(
                KbTopic,
                and_(KbTopic.id == KbArticle.topic_id, KbTopic.tenant_id == KbArticle.tenant_id),
            )
            .where(
                KbArticle.owner_id == user_id,
                KbArticle.deleted_at.is_(None),
                KbTopic.owner_id.is_not(None),
                KbTopic.owner_id != user_id,
            )
        )
    ).all()
    repository = ArticleRepository(session)
    for article, new_owner in rows:
        moved = await repository.update(
            article.id, expected_version=article.version, changes={"owner_id": new_owner}
        )
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=moved.id,
            version=moved.version,
            kind="updated",
            changes=[Change("owner_id", str(user_id), str(new_owner))],
            source="system",
        )
        await saved_event(session, moved, None, created=False, changed=["owner_id"])
    return len(rows)


async def on_status_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a person was disabled, so their articles get a new owner."""
    assert session is not None  # noqa: S101 - transactional consumer
    if envelope.payload.get("status") != "disabled":
        return
    moved = await hand_over(session, uuid.UUID(str(envelope.payload["user_id"])))
    if moved:
        log.info("knowledge_owner_handed_over", articles=moved)


OWNER_DEACTIVATED = ConsumerSpec(
    name="knowledge__owner_deactivated",
    event_types=("identity_access.user.status_changed",),
    handler=on_status_changed,
)
