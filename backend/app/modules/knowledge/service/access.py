"""Who may do what with knowledge (WP-033; D-108 (1), (4), (7); REQ-KB-043, 044, 048).

Permissions (D-108 (7)): `knowledge.view`, `create`, `edit_own`, `edit_any`, `delete`, `submit`,
`approve`, `withdraw`, `manage_topics`, `manage_types`, `manage_settings`.

`knowledge.view` scopes:
- `all`: every article (knowledge managers, admins);
- `group`: articles whose technician audience is everyone or one of the reader's groups
  (technicians, D-108 (4): groups only for technicians);
- `own`: the requester's reading: published articles addressed to requesters they belong to.

Drafts and versions in review are seen only by their author, the article's owner, the topic's
owner and approvers (D-108 (1)); published versions by the audience.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, case, false, or_, true

from app.core.errors import PermissionDenied
from app.modules.identity_access import Subject
from app.modules.knowledge.domain.knowledge import Audience, RequesterAudience
from app.modules.knowledge.infra.models import KbArticle, KbTopic

VIEW = "knowledge.view"
CREATE = "knowledge.create"
EDIT_OWN = "knowledge.edit_own"
EDIT_ANY = "knowledge.edit_any"
DELETE = "knowledge.delete"
SUBMIT = "knowledge.submit"
APPROVE = "knowledge.approve"
WITHDRAW = "knowledge.withdraw"
MANAGE_TOPICS = "knowledge.manage_topics"
MANAGE_TYPES = "knowledge.manage_types"
MANAGE_SETTINGS = "knowledge.manage_settings"


def require(subject: Subject, permission: str) -> None:
    """403 naming the permission when the subject does not hold it at all."""
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission})


def is_staff(subject: Subject) -> bool:
    """Staff read knowledge at `group` or `all`; requesters at `own`."""
    return subject.broadest_scope(VIEW) in ("all", "group")


def topic_audience(topic: KbTopic) -> Audience:
    """A topic's audience as the domain sees it."""
    return Audience(
        tech_all=topic.tech_all,
        tech_groups=frozenset(topic.tech_groups),
        requesters=RequesterAudience(topic.requesters),
        req_groups=frozenset(topic.req_groups),
        req_sites=frozenset(topic.req_sites),
        req_departments=frozenset(topic.req_departments),
    )


def article_audience(article: KbArticle, topic: KbTopic) -> Audience:
    """The article's own (narrower) audience, or its topic's (REQ-KB-044)."""
    if not article.own_audience:
        return topic_audience(topic)
    return Audience(
        tech_all=article.tech_all,
        tech_groups=frozenset(article.tech_groups),
        requesters=RequesterAudience(article.requesters),
        req_groups=frozenset(article.req_groups),
        req_sites=frozenset(article.req_sites),
        req_departments=frozenset(article.req_departments),
    )


def _audience_columns(*, article: bool) -> tuple[Any, Any]:
    """(tech_all, tech_groups) of the article where it has its own audience, else the topic's."""
    if not article:
        return KbTopic.tech_all, KbTopic.tech_groups
    own = KbArticle.own_audience
    return (
        case((own, KbArticle.tech_all), else_=KbTopic.tech_all),
        case((own, KbArticle.tech_groups), else_=KbTopic.tech_groups),
    )


def staff_sees(subject: Subject, *, article: bool = True) -> ColumnElement[bool]:
    """SQL: the technician audience includes the subject (scope `group`), or scope `all`.

    Used on articles (joined with their topic) and on topics (`article=False`). This one
    predicate serves every staff path: lists, counts, pages and search (REQ-KB-048).
    """
    scope = subject.broadest_scope(VIEW)
    if scope == "all":
        return true()
    if scope != "group":
        return false()
    tech_all, tech_groups = _audience_columns(article=article)
    groups = list(subject.group_ids)
    if not groups:
        everyone: ColumnElement[bool] = tech_all.is_(True)
        return everyone
    condition: ColumnElement[bool] = or_(tech_all.is_(True), tech_groups.overlap(groups))
    return condition


def staff_may_edit(subject: Subject, article: KbArticle, topic: KbTopic) -> bool:
    """`edit_any` within its scope, or `edit_own` for the article's owner or author."""
    if subject.holds(EDIT_OWN) and subject.user_id in (article.owner_id, article.created_by):
        return True
    scope = subject.broadest_scope(EDIT_ANY)
    if scope == "all":
        return True
    if scope == "group":
        audience = article_audience(article, topic)
        return audience.tech_all or bool(audience.tech_groups & subject.group_ids)
    return False


def may_approve(subject: Subject, article: KbArticle, topic: KbTopic) -> bool:
    """The topic's owner, or `knowledge.approve` within its scope (REQ-KB-027)."""
    if topic.owner_id == subject.user_id:
        return True
    scope = subject.broadest_scope(APPROVE)
    if scope == "all":
        return True
    if scope == "group":
        audience = article_audience(article, topic)
        return audience.tech_all or bool(audience.tech_groups & subject.group_ids)
    return False


def sees_drafts(subject: Subject, article: KbArticle, topic: KbTopic) -> bool:
    """Drafts and versions in review: their author, owners and approvers only (D-108 (1))."""
    return (
        subject.user_id in (article.owner_id, article.created_by, topic.owner_id)
        or staff_may_edit(subject, article, topic)
        or may_approve(subject, article, topic)
    )


def drafts_visible(subject: Subject) -> ColumnElement[bool]:
    """SQL counterpart of `sees_drafts` for lists ("my drafts", "awaiting my approval")."""
    mine = or_(
        KbArticle.owner_id == subject.user_id,
        KbArticle.created_by == subject.user_id,
        KbTopic.owner_id == subject.user_id,
    )
    wide = [
        scope
        for scope in (subject.broadest_scope(EDIT_ANY), subject.broadest_scope(APPROVE))
        if scope is not None
    ]
    if "all" in wide:
        return true()
    if "group" in wide:
        return or_(mine, staff_sees(subject))
    return and_(mine, staff_sees(subject)) if is_staff(subject) else false()


def owner_ids(*ids: uuid.UUID | None) -> set[uuid.UUID]:
    """The non-empty ids among `ids`."""
    return {i for i in ids if i is not None}
