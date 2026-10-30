"""Knowledge notifications: what the notification engine may know of an article (REQ-KB-086).

Registered through `app.shared.notifications.ports` (D-108 (5)); the engine in the notifications
module does rules, recipients, preferences, templates and channels. Everything here follows the
knowledge module's own rules:

- which steps notify (file 08, REQ-KB-086): submitted → the approvers; approved, rejected and
  withdrawn → the author and the owner; review due → the owner;
- who may see what, at send time: `get_article`, the same reader rule as the article's page,
  list and search (REQ-KB-048). Review notifications are for staff: a requester never sees a
  draft, so they get nothing (`RecordAccess.NONE`), not even word that it happened.

The review-due reminder comes from an hourly sweep (`review_due_sweep`): each review date
reminds its owner once.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import and_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.errors import NotFound, PermissionDenied
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for, user_names, worker_policy
from app.modules.knowledge.domain.knowledge import VersionStatus, WorkflowStep
from app.modules.knowledge.events import KbArticleWorkflow
from app.modules.knowledge.infra.models import KbArticle, KbArticleVersion, KbTopic
from app.modules.knowledge.service.access import APPROVE, is_staff, may_approve
from app.modules.knowledge.service.articles import RECORD_TYPE, get_article
from app.modules.knowledge.service.realtime import RECORD_KIND
from app.shared.clock import system_clock
from app.shared.events import EventEnvelope, record_event
from app.shared.notifications.ports import (
    EventDefault,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

log = get_logger(__name__)

# Approvers are found among holders of `knowledge.approve`; a tenant has a handful at most.
APPROVER_LIMIT = 500

_REASON = Variable("article.reason", "notification_variable.article.reason")
_REVIEW_ON = Variable("article.review_on", "notification_variable.article.review_on")

EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        "kb_article.submitted",
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=("approvers",)),
        required=True,  # approvals are never switched off (Appendix A)
    ),
    NotificationEvent(
        "kb_article.approved",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("author", "owner")),
    ),
    NotificationEvent(
        "kb_article.rejected",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("author", "owner")),
        variables=(_REASON,),
    ),
    NotificationEvent(
        "kb_article.withdrawn",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("author", "owner")),
        variables=(_REASON,),
    ),
    NotificationEvent(
        "kb_article.review_due",
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=("owner",)),
        variables=(_REVIEW_ON,),
    ),
)
_CODES: Mapping[str, str] = {
    WorkflowStep.SUBMITTED: "kb_article.submitted",
    WorkflowStep.APPROVED: "kb_article.approved",
    WorkflowStep.REJECTED: "kb_article.rejected",
    WorkflowStep.WITHDRAWN: "kb_article.withdrawn",
    WorkflowStep.REVIEW_DUE: "kb_article.review_due",
}

RECIPIENT_KINDS = ("approvers", "author", "owner", "topic_owner")

VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("actor.name", "notification_variable.actor.name"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


def _uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


def _actor(envelope: EventEnvelope) -> uuid.UUID | None:
    if envelope.actor.type != "user":
        return None
    try:
        return uuid.UUID(envelope.actor.id)
    except ValueError:
        return None


async def _version(
    session: AsyncSession, article: KbArticle, payload: Mapping[str, object]
) -> KbArticleVersion | None:
    """The version the step is about, else the published one in the article's language."""
    query = select(KbArticleVersion).where(
        KbArticleVersion.article_id == article.id, KbArticleVersion.deleted_at.is_(None)
    )
    if payload.get("language") and payload.get("version_number"):
        found = await session.scalar(
            query.where(
                KbArticleVersion.language == str(payload["language"]),
                KbArticleVersion.number == int(str(payload["version_number"])),
            )
        )
        if found is not None:
            return found
    published = list(
        await session.scalars(query.where(KbArticleVersion.status == VersionStatus.PUBLISHED))
    )
    preferred = [v for v in published if v.language == article.default_language]
    candidates = preferred or published
    return candidates[0] if candidates else None


async def _approvers(session: AsyncSession, article: KbArticle, topic: KbTopic) -> set[uuid.UUID]:
    """The topic's owner and everyone whose `knowledge.approve` scope covers the article."""
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    people = {topic.owner_id} if topic.owner_id is not None else set()
    holders = await worker_policy().holders(session, tenant, APPROVE, limit=APPROVER_LIMIT)
    for user_id, _ in holders:
        if may_approve(await subject_for(session, tenant, user_id), article, topic):
            people.add(user_id)
    return people


class ArticleNotifications:
    """`RecordSource` for knowledge articles."""

    record_type = RECORD_TYPE
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = RECIPIENT_KINDS
    variables = VARIABLES
    conditions: tuple[str, ...] = ()  # no rule conditions yet (the rules screen tests priority)
    event_types = (KbArticleWorkflow.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """The notification event of one workflow step (trash and "still correct" notify nobody)."""
        code = _CODES.get(str(envelope.payload.get("step")))
        return (code,) if code else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The article as it is now, with the people relative to it for this step."""
        payload = envelope.payload
        row = (
            await session.execute(
                select(KbArticle, KbTopic)
                .join(
                    KbTopic,
                    and_(
                        KbTopic.id == KbArticle.topic_id, KbTopic.tenant_id == KbArticle.tenant_id
                    ),
                )
                .where(
                    KbArticle.id == uuid.UUID(str(payload["article_id"])),
                    KbArticle.deleted_at.is_(None),
                )
            )
        ).first()
        if row is None:
            return None
        article, topic = row
        version = await _version(session, article, payload)
        author = _uuid(payload.get("author_id")) or (version.created_by if version else None)
        relatives: dict[str, frozenset[uuid.UUID]] = {
            "author": frozenset({author} if author else ()),
            "owner": frozenset({article.owner_id}),
            "topic_owner": frozenset({topic.owner_id} if topic.owner_id else ()),
        }
        if event_code == "kb_article.submitted":
            relatives["approvers"] = frozenset(await _approvers(session, article, topic))
        actor = _actor(envelope)
        names = await user_names(session, [str(actor)] if actor else [])
        link = f"/knowledge/articles/{article.id}"
        variables: dict[str, VariableValue] = {
            "record.display_id": article.display_id,
            "record.title": version.title if version else article.display_id,
            "record.link": link,
            "actor.name": names.get(str(actor)) if actor else None,
        }
        if event_code == "kb_article.rejected":
            variables["article.reason"] = version.reject_reason if version else None
        if event_code == "kb_article.withdrawn":
            variables["article.reason"] = article.withdrawn_reason
        if event_code == "kb_article.review_due":
            variables["article.review_on"] = (
                article.review_on.isoformat() if article.review_on else None
            )
        return RecordContext(
            record_id=article.id,
            display_id=article.display_id,
            link=link,
            variables=variables,
            # Nobody reads review notifications with public access (see `access`); kept empty
            # of reasons all the same.
            public_variables={k: v for k, v in variables.items() if k != "article.reason"},
            relatives=relatives,
            conditions={},
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for staff who may read the article now (drafts where they may); NONE otherwise."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        if not is_staff(subject):
            return RecordAccess.NONE
        try:
            await get_article(session, subject, record_id)
        except (NotFound, PermissionDenied):
            return RecordAccess.NONE
        return RecordAccess.FULL


SOURCE = ArticleNotifications()


def register() -> None:
    """Make knowledge articles notify (idempotent; called when knowledge is imported)."""
    register_record_source(SOURCE)


# --- review due -----------------------------------------------------------------------------------


async def remind_due_reviews(session: AsyncSession) -> int:
    """Remind each owner once per review date that came (REQ-KB-034, 086); how many reminded.

    `review_reminded_on` is bookkeeping, not the article's content: it does not bump `version`,
    so nobody's open edit meets a conflict because of a reminder.
    """
    today = system_clock.now().date()
    due = list(
        await session.scalars(
            select(KbArticle).where(
                KbArticle.deleted_at.is_(None),
                KbArticle.withdrawn_at.is_(None),
                KbArticle.review_on.is_not(None),
                KbArticle.review_on <= today,
                KbArticle.review_reminded_on.is_distinct_from(KbArticle.review_on),
            )
        )
    )
    for article in due:
        await session.execute(
            update(KbArticle)
            .where(KbArticle.id == article.id)
            .values(review_reminded_on=article.review_on)
            .execution_options(synchronize_session=False)
        )
        await record_event(
            session,
            KbArticleWorkflow(
                article_id=article.id,
                topic_id=article.topic_id,
                owner_id=article.owner_id,
                step=WorkflowStep.REVIEW_DUE.value,
                language=None,
                version_number=None,
                author_id=None,
                readers_affected=False,
            ),
            aggregate_id=article.id,
            aggregate_version=article.version,
        )
    return len(due)


async def review_due_sweep(database: Database, settings: Settings) -> None:
    """Hourly, in every tenant: owners hear of reviews that came due (one reminder per date)."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            count = await remind_due_reviews(session)
        if count:
            log.info("knowledge_review_due_reminded", tenant_id=str(tenant), articles=count)
