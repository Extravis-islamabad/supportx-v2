"""Review, approval and the article's life after publishing (WP-033 session 2; D-108).

REQ-KB-020, 021, 027, 028, 031, 034, 079, 080, 090.

Fully in-app: nothing in the flow depends on mail (the SDP Area 8 lesson). Every step is one
transaction: the rows, their field history and the workflow event (outbox, rule b).

- **Submit:** a draft goes to review.
- **Approve:** publishes it to its audience, replacing the previous published version of that
  language in the same transaction, so readers never see a gap (REQ-KB-021). The topic's
  owner, or `knowledge.approve` within its scope.
- **Reject:** sends the version back to its author as a draft, with the reason.
- **Withdraw:** with a reason, takes the article off every reader path at once (REQ-KB-031).
  Approving a new version brings it back.
- **Still correct:** records a review and moves the review date forward, with no new version
  (REQ-KB-034).
- **Delete / restore:** the trash (REQ-KB-079). Nothing is ever deleted for good here: hard
  deletes only through GDPR erasure jobs (CLAUDE.md §6). An article in the trash keeps its files
  (restoring brings them back with it); whatever purges an article for good must take its files
  along with `app.shared.files.service.cleanup.purge_record("kb_article", id)`.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules.identity_access import Subject, user_names
from app.modules.knowledge.domain.knowledge import (
    VersionStatus,
    WorkflowStep,
    add_months,
    decide_problem,
    self_approval_problem,
    submit_problem,
)
from app.modules.knowledge.events import KbArticleWorkflow
from app.modules.knowledge.infra.models import (
    KbArticle,
    KbArticleVersion,
    KbReview,
    KbSettings,
    KbTopic,
    KbType,
)
from app.modules.knowledge.service.access import (
    APPROVE,
    DELETE,
    MANAGE_SETTINGS,
    SUBMIT,
    article_audience,
    awaiting_approval,
    require,
    staff_sees,
)
from app.modules.knowledge.service.articles import (
    RECORD_TYPE,
    ArticleView,
    get_article,
    settings_row,
)
from app.modules.knowledge.service.repos import (
    ArticleRepository,
    ReviewRepository,
    VersionRepository,
)
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.history import Change, HistoryEntry, Source, history_page, record_changes

REASON_MAX = 2000


def _today() -> date:
    return system_clock.now().date()


def _reason(value: str | None, field: str) -> str:
    """A reason is required and kept short (rejections and withdrawals)."""
    text = (value or "").strip()
    if not text:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field=field,
                    code="reason_required",
                    message_key="errors.field.reason_required",
                )
            ]
        )
    if len(text) > REASON_MAX:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field=field,
                    code="value_too_long_max",
                    message_key="errors.field.value_too_long_max",
                    params={"max_length": REASON_MAX},
                )
            ]
        )
    return text


async def _step(
    session: AsyncSession,
    article: KbArticle,
    step: WorkflowStep,
    *,
    version: KbArticleVersion | None = None,
    readers_affected: bool = False,
) -> None:
    """The outbox event of one workflow step (IDs only, rule c)."""
    await record_event(
        session,
        KbArticleWorkflow(
            article_id=article.id,
            topic_id=article.topic_id,
            owner_id=article.owner_id,
            step=step.value,
            language=version.language if version is not None else None,
            version_number=version.number if version is not None else None,
            author_id=version.created_by if version is not None else None,
            readers_affected=readers_affected,
        ),
        aggregate_id=article.id,
        aggregate_version=article.version,
    )


async def _history(
    session: AsyncSession,
    article: KbArticle,
    changes: Sequence[Change],
    *,
    source: Source,
    reason: str | None = None,
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=article.id,
        version=article.version,
        kind="updated",
        changes=changes,
        source=source,
        reason=reason,
    )


def _draft(view: ArticleView, language: str) -> KbArticleVersion:
    draft = view.drafts.get(language)
    if draft is None:
        raise NotFound(code="kb_draft_not_found")
    return draft


# --- submit, approve, reject (REQ-KB-027, 028) ---------------------------------------------------


async def submit(  # noqa: PLR0913 - the step, explicit
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    language: str,
    *,
    note: str | None,
    expected_version: int,
    source: Source,
) -> KbArticleVersion:
    """A draft goes to review; the approvers see it at once (REQ-KB-027, 086)."""
    require(subject, SUBMIT)
    view = await get_article(session, subject, article_id)
    if not view.can_edit:
        raise PermissionDenied(code="kb_article_not_editable")
    draft = _draft(view, language)
    problem = submit_problem(VersionStatus(draft.status))
    if problem is not None:
        raise Conflict(code=problem)
    note_text = (note or "").strip()[:500] or None
    updated = await VersionRepository(session).update(
        draft.id,
        expected_version=expected_version,
        changes={
            "status": VersionStatus.IN_REVIEW.value,
            "submitted_by": subject.user_id,
            "submitted_at": system_clock.now(),
            "change_note": note_text,
            "reject_reason": None,
        },
    )
    await _history(
        session,
        view.article,
        [Change(f"version.{language}.status", draft.status, updated.status)],
        source=source,
    )
    await _step(session, view.article, WorkflowStep.SUBMITTED, version=updated)
    return updated


async def _in_review(view: ArticleView, subject: Subject, language: str) -> KbArticleVersion:
    if not view.can_approve:
        raise PermissionDenied(code="kb_cannot_approve", params={"permission": APPROVE})
    version = _draft(view, language)
    problem = decide_problem(VersionStatus(version.status))
    if problem is not None:
        raise Conflict(code=problem)
    del subject
    return version


async def approve(  # noqa: PLR0913 - the step, explicit
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    language: str,
    *,
    expected_version: int,
    source: Source,
) -> ArticleView:
    """Publish a version in review: the previous one is superseded in the same transaction."""
    view = await get_article(session, subject, article_id)
    version = await _in_review(view, subject, language)
    settings = await settings_row(session)
    author = version.submitted_by or version.created_by
    problem = self_approval_problem(
        allowed=settings.self_approval, author_id=author, approver=subject.user_id
    )
    if problem is not None:
        raise PermissionDenied(code=problem)
    versions = VersionRepository(session)
    previous = view.published.get(language)
    if previous is not None:
        await versions.update(
            previous.id,
            expected_version=previous.version,
            changes={"status": VersionStatus.SUPERSEDED.value},
        )
    now = system_clock.now()
    published = await versions.update(
        version.id,
        expected_version=expected_version,
        changes={
            "status": VersionStatus.PUBLISHED.value,
            "published_at": now,
            "decided_by": subject.user_id,
            "decided_at": now,
            "self_approved": author == subject.user_id,
        },
    )
    article = view.article
    changes = [
        Change(
            f"version.{language}.published", previous.number if previous else None, published.number
        )
    ]
    if article.withdrawn_at is not None:  # approving a new version brings a withdrawn one back
        article = await ArticleRepository(session).update(
            article.id,
            expected_version=article.version,
            changes={"withdrawn_at": None, "withdrawn_reason": None},
        )
        changes.append(Change(field="withdrawn", old=True, new=False))
    await _history(session, article, changes, source=source)
    await _step(session, article, WorkflowStep.APPROVED, version=published, readers_affected=True)
    await session.flush()
    return await get_article(session, subject, article_id)


async def reject(  # noqa: PLR0913 - the step, explicit
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    language: str,
    *,
    reason: str | None,
    expected_version: int,
    source: Source,
) -> KbArticleVersion:
    """Send a version back to its author as a draft, with the reason they will see."""
    text = _reason(reason, "body.reason")
    view = await get_article(session, subject, article_id)
    version = await _in_review(view, subject, language)
    now = system_clock.now()
    updated = await VersionRepository(session).update(
        version.id,
        expected_version=expected_version,
        changes={
            "status": VersionStatus.DRAFT.value,
            "reject_reason": text,
            "decided_by": subject.user_id,
            "decided_at": now,
        },
    )
    await _history(
        session,
        view.article,
        [Change(f"version.{language}.status", version.status, updated.status)],
        source=source,
        reason=text,
    )
    await _step(session, view.article, WorkflowStep.REJECTED, version=updated)
    return updated


# --- withdraw (REQ-KB-031) ---------------------------------------------------------------------


async def withdraw(  # noqa: PLR0913 - the step, explicit
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    *,
    reason: str | None,
    expected_version: int,
    source: Source,
) -> ArticleView:
    """Take a published article off every reader path, with a reason."""
    text = _reason(reason, "body.reason")
    view = await get_article(session, subject, article_id)
    if not view.can_withdraw:
        raise PermissionDenied(code="kb_cannot_withdraw")
    if view.article.withdrawn_at is not None:
        raise Conflict(code="kb_article_withdrawn")
    if not view.published:
        raise Conflict(code="kb_not_published")
    article = await ArticleRepository(session).update(
        article_id,
        expected_version=expected_version,
        changes={"withdrawn_at": system_clock.now(), "withdrawn_reason": text},
    )
    await _history(
        session,
        article,
        [Change(field="withdrawn", old=False, new=True)],
        source=source,
        reason=text,
    )
    await _step(session, article, WorkflowStep.WITHDRAWN, readers_affected=True)
    await session.flush()
    return await get_article(session, subject, article_id)


# --- still correct (REQ-KB-034) ------------------------------------------------------------------


async def still_correct(
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> ArticleView:
    """Record a review: the date moves on by the type's interval, with no new version."""
    view = await get_article(session, subject, article_id)
    if not (view.can_edit or view.article.owner_id == subject.user_id):
        raise PermissionDenied(code="kb_article_not_editable")
    kind = await session.scalar(select(KbType).where(KbType.code == view.article.type_code))
    months = kind.review_months if kind is not None else 12
    next_review = add_months(_today(), months)
    before = view.article.review_on
    article = await ArticleRepository(session).update(
        article_id, expected_version=expected_version, changes={"review_on": next_review}
    )
    await ReviewRepository(session).add(
        KbReview(article_id=article.id, reviewed_by=subject.user_id, next_review_on=next_review)
    )
    await _history(
        session,
        article,
        [
            Change(
                "review_on",
                before.isoformat() if before is not None else None,
                next_review.isoformat(),
            )
        ],
        source=source,
    )
    await _step(session, article, WorkflowStep.REVIEWED)
    await session.flush()
    return await get_article(session, subject, article_id)


# --- trash (REQ-KB-079) --------------------------------------------------------------------------


def _may_delete(subject: Subject, article: KbArticle, topic: KbTopic) -> bool:
    scope = subject.broadest_scope(DELETE)
    if scope == "all":
        return True
    if scope == "group":
        audience = article_audience(article, topic)
        return audience.tech_all or bool(audience.tech_groups & subject.group_ids)
    return False


async def delete_article(
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """To the trash: off every path at once, restorable."""
    view = await get_article(session, subject, article_id)
    if not _may_delete(subject, view.article, view.topic):
        raise PermissionDenied(code="kb_cannot_delete", params={"permission": DELETE})
    article = await ArticleRepository(session).soft_delete(
        article_id, expected_version=expected_version
    )
    await _history(session, article, [Change(field="deleted", old=False, new=True)], source=source)
    await _step(session, article, WorkflowStep.DELETED, readers_affected=bool(view.published))


async def restore_article(
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> ArticleView:
    """Back from the trash, into its topic (which must be there)."""
    row = (
        await session.execute(
            select(KbArticle, KbTopic)
            .join(
                KbTopic,
                and_(KbTopic.id == KbArticle.topic_id, KbTopic.tenant_id == KbArticle.tenant_id),
            )
            .where(
                KbArticle.id == article_id,
                KbArticle.deleted_at.is_not(None),
                staff_sees(subject),
            )
        )
    ).first()
    if row is None or not _may_delete(subject, row[0], row[1]):
        raise NotFound(code="kb_article_not_found")
    if row[1].deleted_at is not None:
        raise Conflict(code="kb_topic_in_trash")
    article = await ArticleRepository(session).restore(
        article_id, expected_version=expected_version
    )
    await _history(session, article, [Change(field="deleted", old=True, new=False)], source=source)
    await _step(session, article, WorkflowStep.RESTORED, readers_affected=True)
    await session.flush()
    return await get_article(session, subject, article_id)


# --- versions (REQ-KB-020) -----------------------------------------------------------------------


async def list_versions(
    session: AsyncSession, subject: Subject, article_id: uuid.UUID
) -> list[KbArticleVersion]:
    """Every published and earlier version; drafts and reviews for those who may see them."""
    view = await get_article(session, subject, article_id)
    shown = {VersionStatus.PUBLISHED.value, VersionStatus.SUPERSEDED.value}
    if view.can_edit or view.can_approve or view.drafts:
        shown |= {VersionStatus.DRAFT.value, VersionStatus.IN_REVIEW.value}
    rows = await session.scalars(
        select(KbArticleVersion)
        .where(
            KbArticleVersion.article_id == article_id,
            KbArticleVersion.deleted_at.is_(None),
            KbArticleVersion.status.in_(shown),
        )
        .order_by(KbArticleVersion.language, KbArticleVersion.number.desc())
    )
    return list(rows.all())


# --- the approval inbox's count and settings (REQ-KB-086, 090) ------------------------------------


async def awaiting_count(session: AsyncSession, subject: Subject) -> int:
    """How many articles wait for this subject's decision (the live count in the menu)."""
    count = await session.scalar(
        select(func.count(func.distinct(KbArticle.id)))
        .select_from(KbArticle)
        .join(
            KbTopic,
            and_(KbTopic.id == KbArticle.topic_id, KbTopic.tenant_id == KbArticle.tenant_id),
        )
        .join(
            KbArticleVersion,
            and_(
                KbArticleVersion.article_id == KbArticle.id,
                KbArticleVersion.tenant_id == KbArticle.tenant_id,
                KbArticleVersion.deleted_at.is_(None),
                KbArticleVersion.status == VersionStatus.IN_REVIEW.value,
            ),
        )
        .where(KbArticle.deleted_at.is_(None), staff_sees(subject), awaiting_approval(subject))
    )
    return int(count or 0)


async def update_settings(
    session: AsyncSession,
    subject: Subject,
    values: dict[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> KbSettings:
    """Change knowledge settings with If-Match (REQ-KB-090)."""
    require(subject, MANAGE_SETTINGS)
    current = await settings_row(session)
    if current.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    changes = [
        Change(k, getattr(current, k), v) for k, v in values.items() if getattr(current, k) != v
    ]
    for key, value in values.items():
        setattr(current, key, value)
    if changes:
        current.version += 1
        current.updated_by = subject.user_id
        await record_changes(
            session,
            record_type="kb_settings",
            record_id=current.tenant_id,
            version=current.version,
            kind="updated",
            changes=changes,
            source=source,
        )
    await session.flush()
    return current


# --- history (REQ-KB-080) -------------------------------------------------------------------------


async def history(
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    *,
    before_version: int | None,
    limit: int,
) -> tuple[list[HistoryEntry], int | None, dict[str, str]]:
    """Saves of an article, for those who may work on it: its editors, approvers and withdrawers.

    Readers get 404: the history names drafts, reasons for sending back and withdrawing.
    """
    view = await get_article(session, subject, article_id)
    if not (view.can_edit or view.can_approve or view.can_withdraw):
        raise NotFound(code="kb_article_not_found")
    entries, cursor = await history_page(
        session, RECORD_TYPE, article_id, before_version=before_version, limit=limit
    )
    names = await user_names(session, sorted({e.actor_id for e in entries if e.actor_id}))
    return entries, cursor, names
