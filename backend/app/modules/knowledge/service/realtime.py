"""Knowledge on realtime (WP-033 session 2; architecture.md §8, CLAUDE.md rule c).

Channels this module decides about:

    t:{tenant}:queue:knowledge…     staff lists (LiveList): one channel per technician group of
                                    the article's audience, plus `all` holders; the article's
                                    owner and author on their personal channels
    t:{tenant}:kb:{article}         the article page (session 3): IDs, changed step and version for
                                    whoever may read the article now (`get_article`, the same rule
                                    as the page); its files and delivery log are announced here too
    t:{tenant}:wi:{record}          a record's page, for its linked articles (D-121): IDs only
    t:{tenant}:broadcast            "knowledge changed", no IDs: something readers see changed
                                    (published, withdrawn, trashed, restored, a topic, a type,
                                    the settings), or an
                                    article open to every technician; screens refetch and the
                                    API applies who sees what, so nobody outside an audience
                                    ever learns an article's ID (REQ-KB-048 AC3)

The approval count ("awaiting my approval") refetches on the broadcast too.
"""

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.knowledge.infra.models import KbArticle, KbTopic
from app.modules.knowledge.service.access import VIEW, article_audience
from app.modules.knowledge.service.articles import get_article
from app.shared.events import EventEnvelope
from app.shared.files.ports import record_channel_kind
from app.shared.realtime import (
    ChannelAccess,
    ChannelRequest,
    ChannelSpec,
    LiveList,
    Publication,
    RealtimeEffects,
    RealtimeRoute,
    broadcast,
    record,
)

LIST = LiveList("knowledge", VIEW)
CHANGED = "knowledge.changed"
RECORD_KIND = "kb"  # the article page's channel, t:{tenant}:kb:{article}
ARTICLE_CHANGED = "knowledge.article_changed"


async def _record_channel(request: ChannelRequest) -> ChannelAccess | None:
    """Whoever may read the article now (drafts included where they may), with presence."""
    try:
        article_id = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    try:
        await get_article(request.session, request.subject, article_id)
    except (NotFound, PermissionDenied):
        return None
    return ChannelAccess(presence=True)


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
    # The article page: subscribers passed the reader rule when they joined.
    step = payload.get("step")
    changed = payload.get("changed_fields") or ()
    publications.append(
        Publication(
            record(tenant, RECORD_KIND, article_id),
            ARTICLE_CHANGED,
            ids=(str(article_id),),
            fields=(str(step),) if step else tuple(str(f) for f in changed),
            version=envelope.aggregate_version,
            actor_id=_actor(envelope),
        )
    )
    # Readers' screens (and every technician's, for an article open to all) refetch: no IDs.
    if audience.tech_all or payload.get("readers_affected") or payload.get("step") == "submitted":
        publications.append(Publication(broadcast(tenant), CHANGED, coalesce=True))
    return RealtimeEffects(publications=publications)


async def _topic_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Topics, types or settings changed: every knowledge screen refetches (no IDs)."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CHANGED, coalesce=True)]
    )


async def _link_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A link between an article and a record (D-121): both pages refetch their lists.

    The article page's subscribers passed the reader rule; the record's passed its owner's rule.
    Each screen then reads the links through the API, which shows only what both rules allow.
    """
    del session
    tenant, payload = envelope.tenant_id, envelope.payload
    article_id = uuid.UUID(str(payload["article_id"]))
    record_id = uuid.UUID(str(payload["record_id"]))
    publications = [
        Publication(
            record(tenant, RECORD_KIND, article_id),
            envelope.event_type,
            ids=(str(article_id),),
            fields=("links",),
            actor_id=_actor(envelope),
        )
    ]
    kind = record_channel_kind(str(payload["record_type"]))
    if kind is not None:
        publications.append(
            Publication(
                record(tenant, kind, record_id),
                envelope.event_type,
                ids=(str(record_id),),
                fields=("knowledge",),
                actor_id=_actor(envelope),
            )
        )
    return RealtimeEffects(publications=publications)


CHANNELS = [LIST.spec(), ChannelSpec(kind=RECORD_KIND, authorize=_record_channel)]
ROUTES = [
    RealtimeRoute(("knowledge.article.saved", "knowledge.article.workflow"), _article_changed),
    RealtimeRoute(("knowledge.link.saved", "knowledge.link.removed"), _link_changed),
    # Topics, types and settings: every knowledge screen refetches (no IDs; D-120).
    RealtimeRoute(
        (
            "knowledge.topic.saved",
            "knowledge.topic.deleted",
            "knowledge.type.saved",
            "knowledge.settings.changed",
        ),
        _topic_changed,
    ),
]
