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
from datetime import date
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


# --- session 2: withdrawing, the approval inbox and requester reading -----------------------------


def may_withdraw(subject: Subject, article: KbArticle, topic: KbTopic) -> bool:
    """`knowledge.withdraw` within its scope, or the topic's owner (REQ-KB-031)."""
    if topic.owner_id == subject.user_id:
        return True
    scope = subject.broadest_scope(WITHDRAW)
    if scope == "all":
        return True
    if scope == "group":
        audience = article_audience(article, topic)
        return audience.tech_all or bool(audience.tech_groups & subject.group_ids)
    return False


def withdrawals_visible(subject: Subject) -> ColumnElement[bool]:
    """SQL counterpart of `may_withdraw` or `sees_drafts`: who sees withdrawn articles."""
    scope = subject.broadest_scope(WITHDRAW)
    if scope == "all":
        return true()
    mine: ColumnElement[bool] = KbTopic.owner_id == subject.user_id
    if scope == "group":
        return or_(mine, staff_sees(subject), drafts_visible(subject))
    return or_(mine, drafts_visible(subject))


def awaiting_approval(subject: Subject) -> ColumnElement[bool]:
    """SQL counterpart of `may_approve`: the versions in review this subject may decide."""
    mine: ColumnElement[bool] = KbTopic.owner_id == subject.user_id
    scope = subject.broadest_scope(APPROVE)
    if scope == "all":
        return true()
    if scope == "group":
        tech_all, tech_groups = _audience_columns(article=True)
        groups = list(subject.group_ids)
        in_group = tech_all.is_(True)
        if groups:
            in_group = or_(in_group, tech_groups.overlap(groups))
        return or_(mine, in_group)
    return mine


def _audience_overlap(
    article_column: Any,  # noqa: ANN401 - an ARRAY(Uuid) column of KbArticle
    topic_column: Any,  # noqa: ANN401 - the same column of KbTopic
    values: list[uuid.UUID],
) -> ColumnElement[bool]:
    """The effective (article's own, else topic's) list shares a value with `values`."""
    if not values:
        return false()
    own = KbArticle.own_audience
    return or_(
        and_(own.is_(True), article_column.overlap(values)),
        and_(own.is_(False), topic_column.overlap(values)),
    )


def requester_sees(
    subject: Subject, department_id: uuid.UUID | None, today: date
) -> ColumnElement[bool]:
    """SQL: a requester may read the article (REQ-KB-045, 048; D-108 (1)).

    Inside its requester audience (all, or one of the requester's groups, sites or department),
    not withdrawn and not expired. The published version is chosen by the caller; drafts and
    versions in review never reach a requester.
    """
    own = KbArticle.own_audience
    audience = case((own.is_(True), KbArticle.requesters), else_=KbTopic.requesters)
    selected = or_(
        _audience_overlap(KbArticle.req_groups, KbTopic.req_groups, list(subject.group_ids)),
        _audience_overlap(KbArticle.req_sites, KbTopic.req_sites, list(subject.site_ids)),
        _audience_overlap(
            KbArticle.req_departments,
            KbTopic.req_departments,
            [department_id] if department_id is not None else [],
        ),
    )
    return and_(
        KbArticle.withdrawn_at.is_(None),
        or_(KbArticle.expires_on.is_(None), KbArticle.expires_on > today),
        or_(
            audience == RequesterAudience.ALL.value,
            and_(audience == RequesterAudience.SELECTED.value, selected),
        ),
    )
