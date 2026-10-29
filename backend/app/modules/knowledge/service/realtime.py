"""Knowledge on realtime (WP-033 session 2; architecture.md §8, CLAUDE.md rule c).

Channels this module decides about:

    t:{tenant}:queue:knowledge…     staff lists (LiveList): one channel per technician group of
                                    the article's audience, plus `all` holders; the article's
                                    owner and author on their personal channels
    t:{tenant}:broadcast            "knowledge changed", no IDs: something readers see changed
                                    (published, withdrawn, trashed, restored, a topic), or an
                                    article open to every technician; screens refetch and the
                                    API applies who sees what, so nobody outside an audience
                                    ever learns an article's ID (REQ-KB-048 AC3)

The approval count ("awaiting my approval") refetches on the broadcast too.
"""

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.infra.models import KbArticle, KbTopic
from app.modules.knowledge.service.access import VIEW, article_audience
from app.shared.events import EventEnvelope
from app.shared.realtime import (
    LiveList,
    Publication,
    RealtimeEffects,
    RealtimeRoute,
    broadcast,
)

LIST = LiveList("knowledge", VIEW)
CHANGED = "knowledge.changed"


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


async def _article_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """An article or one of its versions changed: its staff audience, owner and author hear it."""
    tenant = envelope.tenant_id
    payload = envelope.payload
    article_id = uuid.UUID(str(payload["article_id"]))
    row = (
        await session.execute(
            select(KbArticle, KbTopic)
            .join(
                KbTopic,
                and_(KbTopic.id == KbArticle.topic_id, KbTopic.tenant_id == KbArticle.tenant_id),
            )
            .where(KbArticle.id == article_id)
        )
    ).first()
    owners = {uuid.UUID(str(payload["owner_id"]))}
    if payload.get("author_id"):
        owners.add(uuid.UUID(str(payload["author_id"])))
    if row is None:  # gone meanwhile: only its owner and author hear of it
        return RealtimeEffects(
            publications=LIST.publications(tenant, CHANGED, article_id, owners=owners)
        )
    article, topic = row
    if topic.owner_id is not None:
        owners.add(topic.owner_id)
    audience = article_audience(article, topic)
    publications = LIST.publications(
        tenant,
        CHANGED,
        article_id,
        groups=() if audience.tech_all else audience.tech_groups,
        owners=owners,
        actor_id=_actor(envelope),
    )
    # Readers' screens (and every technician's, for an article open to all) refetch: no IDs.
    if audience.tech_all or payload.get("readers_affected") or payload.get("step") == "submitted":
        publications.append(Publication(broadcast(tenant), CHANGED, coalesce=True))
    return RealtimeEffects(publications=publications)


async def _topic_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """The topic tree changed: every knowledge screen refetches it (no IDs)."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CHANGED, coalesce=True)]
    )


CHANNELS = [LIST.spec()]
ROUTES = [
    RealtimeRoute(("knowledge.article.saved", "knowledge.article.workflow"), _article_changed),
    RealtimeRoute(("knowledge.topic.saved", "knowledge.topic.deleted"), _topic_changed),
]
