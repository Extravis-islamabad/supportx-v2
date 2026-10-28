"""Articles and their drafts (WP-033 session 1).

REQ-KB-001, 002, 005, 006, 008, 012, 013, 020, 021, 033, 034, 035, 049.

- Creating an article creates its first draft (version 1) in the author's language.
- A draft is saved in place, again and again (autosave, If-Match on the draft's version).
- Editing a published article starts a new draft from it; readers keep the published one until
  the new version is approved (session 2), so a published article never goes offline.
- A translation is a draft of another language of the same article (same ID, topic, audience).
- Settings and article types are created on first use (D-041: seed data, editable).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.knowledge.domain.knowledge import (
    BUILTIN_TYPES,
    ID_PREFIX,
    KbLanguage,
    VersionStatus,
    date_problems,
    default_review,
)
from app.modules.knowledge.events import KbArticleSaved
from app.modules.knowledge.infra.models import (
    KbArticle,
    KbArticleVersion,
    KbSettings,
    KbTopic,
    KbType,
)
from app.modules.knowledge.service.access import (
    CREATE,
    VIEW,
    article_audience,
    drafts_visible,
    is_staff,
    require,
    sees_drafts,
    staff_may_edit,
    staff_sees,
    topic_audience,
)
from app.modules.knowledge.service.repos import ArticleRepository, VersionRepository
from app.modules.knowledge.service.topics import (
    AUDIENCE_FIELDS,
    audience_columns,
    audience_of,
    check_audience,
    get_topic,
)
from app.shared.clock import system_clock
from app.shared.db.display_ids import next_display_id
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.richtext import sanitize_html
from app.shared.search import ENGINE, SearchDocument

RECORD_TYPE = "kb_article"
KEYWORD_MAX = 60
OPEN = (VersionStatus.DRAFT, VersionStatus.IN_REVIEW)
_VERSION_COLUMNS = KbArticleVersion.__table__.c
TEXT = SearchDocument(
    vector=_VERSION_COLUMNS.search_vector, short_text=_VERSION_COLUMNS.search_title
)


# --- settings and types (first use) ---------------------------------------------------------------


async def settings_row(session: AsyncSession) -> KbSettings:
    """The tenant's knowledge settings, created with the defaults on first use."""
    found: KbSettings | None = await session.scalar(select(KbSettings))
    if found is not None:
        return found
    await session.execute(
        insert(KbSettings).values(tenant_id=_tenant(session)).on_conflict_do_nothing()
    )
    created: KbSettings | None = await session.scalar(select(KbSettings))
    assert created is not None  # noqa: S101 - just inserted in this transaction
    return created


async def article_types(session: AsyncSession) -> Sequence[KbType]:
    """The tenant's article types; built-in ones seeded on first use (file 08 Appendix A).

    Workaround and known issue need problems (Professional, D-044): seeded when problems exist.
    """
    rows = (await session.scalars(select(KbType).order_by(KbType.sort_order, KbType.code))).all()
    if rows:
        return rows
    tenant = _tenant(session)
    for order, kind in enumerate(t for t in BUILTIN_TYPES if not t.needs_problems):
        await session.execute(
            insert(KbType)
            .values(
                tenant_id=tenant,
                code=kind.code,
                review_months=kind.review_months,
                builtin=True,
                sort_order=order,
            )
            .on_conflict_do_nothing()
        )
    return (await session.scalars(select(KbType).order_by(KbType.sort_order, KbType.code))).all()


def _tenant(session: AsyncSession) -> uuid.UUID:
    from app.core.database import SESSION_TENANT_KEY  # noqa: PLC0415 - session info key

    context = session.info[SESSION_TENANT_KEY]
    tenant: uuid.UUID = context.tenant_id
    return tenant


# --- views ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArticleView:
    """An article as one reader sees it: its versions they may see, and what they may do."""

    article: KbArticle
    topic: KbTopic
    published: dict[str, KbArticleVersion]
    drafts: dict[str, KbArticleVersion]
    can_edit: bool
    expired: bool
    review_due: bool


def _today() -> date:
    return system_clock.now().date()


async def _versions(session: AsyncSession, article_id: uuid.UUID) -> list[KbArticleVersion]:
    return list(
        (
            await session.scalars(
                select(KbArticleVersion)
                .where(
                    KbArticleVersion.article_id == article_id,
                    KbArticleVersion.deleted_at.is_(None),
                )
                .order_by(KbArticleVersion.language, KbArticleVersion.number)
            )
        ).all()
    )


async def _load(
    session: AsyncSession, subject: Subject, article_id: uuid.UUID
) -> tuple[KbArticle, KbTopic]:
    """The article and its topic, if the subject reaches it as staff; 404 otherwise."""
    require(subject, VIEW)
    if not is_staff(subject):
        raise NotFound(code="kb_article_not_found")  # requesters read published (session 2)
    row = (
        await session.execute(
            select(KbArticle, KbTopic)
            .join(
                KbTopic,
                and_(KbTopic.id == KbArticle.topic_id, KbTopic.tenant_id == KbArticle.tenant_id),
            )
            .where(KbArticle.id == article_id, KbArticle.deleted_at.is_(None), staff_sees(subject))
        )
    ).first()
    if row is None:
        raise NotFound(code="kb_article_not_found")
    return row[0], row[1]


async def get_article(
    session: AsyncSession, subject: Subject, article_id: uuid.UUID
) -> ArticleView:
    """One article: published versions for its audience; drafts only for those who may (D-108)."""
    article, topic = await _load(session, subject, article_id)
    versions = await _versions(session, article.id)
    drafts_ok = sees_drafts(subject, article, topic)
    published = {v.language: v for v in versions if v.status == VersionStatus.PUBLISHED}
    drafts = {v.language: v for v in versions if v.status in OPEN} if drafts_ok else {}
    if not published and not drafts:
        raise NotFound(code="kb_article_not_found")  # nothing this reader may see yet
    today = _today()
    return ArticleView(
        article=article,
        topic=topic,
        published=published,
        drafts=drafts,
        can_edit=staff_may_edit(subject, article, topic),
        expired=article.expires_on is not None and article.expires_on <= today,
        review_due=article.review_on is not None and article.review_on <= today,
    )


# --- create ---------------------------------------------------------------------------------------


def _keywords(values: Sequence[str]) -> list[str]:
    """Separate tags; a pasted "vpn, remote access" becomes two (REQ-KB-005 AC2)."""
    found: list[str] = []
    for value in values:
        for part in value.split(","):
            word = part.strip()[:KEYWORD_MAX]
            if word and word.lower() not in {f.lower() for f in found}:
                found.append(word)
    return found


def _title(value: str) -> str:
    title = value.strip()
    if not title:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.title",
                    code="title_required",
                    message_key="errors.field.title_required",
                )
            ]
        )
    return title


def _check_dates(
    review_on: date | None, expires_on: date | None, *, review_changed: bool = True
) -> None:
    """Both dates are always compared; a review date already past only matters when set now."""
    for problem in date_problems(review_on, expires_on, _today()):
        if problem == "review_date_past":
            if not review_changed:
                continue
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="body.review_on",
                        code="review_date_past",
                        message_key="errors.field.review_date_past",
                    )
                ]
            )
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.expires_on",
                    code="expiry_before_review",
                    message_key="errors.field.expiry_before_review",
                )
            ]
        )


async def _type(session: AsyncSession, code: str) -> KbType:
    found = next((t for t in await article_types(session) if t.code == code), None)
    if found is None or found.retired_at is not None:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.type_code",
                    code="unknown_article_type",
                    message_key="errors.field.unknown_article_type",
                )
            ]
        )
    return found


def _own_audience(values: Mapping[str, Any], topic: KbTopic) -> dict[str, Any]:
    """The article's own audience, narrower than its topic's, or none (REQ-KB-044 AC3)."""
    if not values.get("own_audience"):
        return {"own_audience": False}
    audience = audience_of(values)
    check_audience(audience)
    if audience.within(topic_audience(topic)):
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.tech_groups",
                    code="wider_than_topic",
                    message_key="errors.field.wider_than_topic",
                )
            ]
        )
    return {"own_audience": True, **audience_columns(audience)}


def _draft_snapshot(version: KbArticleVersion) -> dict[str, Any]:
    return {
        "title": version.title,
        "body_html": version.body_html,
        "keywords": list(version.keywords),
        "internal_note": version.internal_note,
        "change_note": version.change_note,
    }


async def create_article(
    session: AsyncSession,
    subject: Subject,
    values: Mapping[str, Any],
    *,
    source: Source,
) -> ArticleView:
    """A new article and its first draft (REQ-KB-001, 012); its owner is its author (KB-033)."""
    require(subject, CREATE)
    topic = await get_topic(session, subject, values["topic_id"])
    kind = await _type(session, values["type_code"])
    review_on = values.get("review_on") or default_review(_today(), kind.review_months)
    expires_on = values.get("expires_on")
    _check_dates(review_on, expires_on)
    settings = await settings_row(session)
    language = KbLanguage(values.get("language", "en"))
    article = KbArticle(
        display_id=await next_display_id(session, settings.prefix or ID_PREFIX),
        topic_id=topic.id,
        type_code=kind.code,
        owner_id=subject.user_id,
        default_language=language.value,
        review_on=review_on,
        expires_on=expires_on,
        **_own_audience(values, topic),
    )
    await ArticleRepository(session).add(article)
    draft = KbArticleVersion(
        article_id=article.id,
        language=language.value,
        number=1,
        status=VersionStatus.DRAFT.value,
        title=_title(values["title"]),
        body_html=sanitize_html(values.get("body_html") or ""),
        keywords=_keywords(values.get("keywords") or ()),
        internal_note=(values.get("internal_note") or "").strip() or None,
    )
    await VersionRepository(session).add(draft)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=article.id,
        version=article.version,
        kind="created",
        changes=[
            Change("topic_id", None, str(topic.id)),
            Change("type_code", None, kind.code),
            Change("review_on", None, review_on.isoformat()),
            *[Change(k, None, v) for k, v in _draft_snapshot(draft).items() if k != "body_html"],
        ],
        source=source,
    )
    await _saved(session, article, draft.language, created=True, changed=[])
    await session.flush()
    return await get_article(session, subject, article.id)


async def _saved(
    session: AsyncSession,
    article: KbArticle,
    language: str | None,
    *,
    created: bool,
    changed: list[str],
) -> None:
    """The outbox event of a change to the article or one of its drafts (ids and names only)."""
    await record_event(
        session,
        KbArticleSaved(
            article_id=article.id,
            topic_id=article.topic_id,
            owner_id=article.owner_id,
            language=language,
            created=created,
            changed_fields=changed,
        ),
        aggregate_id=article.id,
        aggregate_version=article.version,
    )


# --- change the article ---------------------------------------------------------------------------


async def _editable(session: AsyncSession, subject: Subject, article_id: uuid.UUID) -> ArticleView:
    view = await get_article(session, subject, article_id)
    if not view.can_edit:
        raise PermissionDenied(code="kb_article_not_editable")
    return view


def _article_snapshot(article: KbArticle) -> dict[str, Any]:
    return {
        "topic_id": str(article.topic_id),
        "type_code": article.type_code,
        "owner_id": str(article.owner_id),
        "review_on": article.review_on.isoformat() if article.review_on else None,
        "expires_on": article.expires_on.isoformat() if article.expires_on else None,
        "own_audience": article.own_audience,
        **{
            k: sorted(str(v) for v in getattr(article, k))
            if isinstance(getattr(article, k), list)
            else getattr(article, k)
            for k in AUDIENCE_FIELDS
        },
    }


async def update_article(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> ArticleView:
    """Topic, type, owner, own audience, review and expiry dates (the fields given)."""
    view = await _editable(session, subject, article_id)
    article, topic = view.article, view.topic
    columns: dict[str, Any] = {}
    if "topic_id" in values and values["topic_id"] != article.topic_id:
        topic = await get_topic(session, subject, values["topic_id"])
        columns["topic_id"] = topic.id
    if "type_code" in values:
        columns["type_code"] = (await _type(session, values["type_code"])).code
    if "owner_id" in values:
        columns["owner_id"] = values["owner_id"]
    if "own_audience" in values or any(k in values for k in AUDIENCE_FIELDS):
        current = {k: getattr(article, k) for k in ("own_audience", *AUDIENCE_FIELDS)}
        columns |= _own_audience({**current, **values}, topic)
    review_on = values.get("review_on", article.review_on)
    expires_on = values.get("expires_on", article.expires_on)
    if "review_on" in values or "expires_on" in values:
        _check_dates(review_on, expires_on, review_changed="review_on" in values)
        columns |= {"review_on": review_on, "expires_on": expires_on}
    columns = {k: v for k, v in columns.items() if getattr(article, k) != v}
    if not columns:
        if article.version != expected_version:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": article.version},
            )
        return view
    before = _article_snapshot(article)
    updated = await ArticleRepository(session).update(
        article.id, expected_version=expected_version, changes=columns
    )
    after = _article_snapshot(updated)
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
    await _saved(session, updated, None, created=False, changed=[c.field for c in changes])
    return await get_article(session, subject, updated.id)


async def save_draft(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    language: str,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> KbArticleVersion:
    """Autosave of a draft in place (REQ-KB-013): title, body, keywords and notes.

    `expected_version` is the draft's own version (If-Match). A version in review is no longer
    a draft: changing it needs it back from the approver (session 2).
    """
    view = await _editable(session, subject, article_id)
    draft = view.drafts.get(language)
    if draft is None:
        raise NotFound(code="kb_draft_not_found")
    if draft.status != VersionStatus.DRAFT:
        raise Conflict(code="kb_draft_in_review")
    columns: dict[str, Any] = {}
    if "title" in values:
        columns["title"] = _title(values["title"])
    if "body_html" in values:
        columns["body_html"] = sanitize_html(values["body_html"] or "")
    if "keywords" in values:
        columns["keywords"] = _keywords(values["keywords"] or ())
    for name in ("internal_note", "change_note"):
        if name in values:
            columns[name] = (values[name] or "").strip() or None
    columns = {k: v for k, v in columns.items() if getattr(draft, k) != v}
    if not columns:
        return draft
    before = _draft_snapshot(draft)
    saved = await VersionRepository(session).update(
        draft.id, expected_version=expected_version, changes=columns
    )
    after = _draft_snapshot(saved)
    changes = [Change(k, before[k], v) for k, v in after.items() if before[k] != v]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=view.article.id,
        version=view.article.version,
        kind="updated",
        # The body's text is in the version itself; history names the change, not the HTML.
        changes=[c if c.field != "body_html" else Change("body_html", None, None) for c in changes],
        source=source,
    )
    await _saved(session, view.article, language, created=False, changed=[c.field for c in changes])
    return saved


async def new_draft(
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    language: str,
    *,
    source: Source,
) -> KbArticleVersion:
    """A new draft: from the published version of `language` (REQ-KB-021), or a translation.

    A translation starts from the default language's latest text, to be translated (REQ-KB-049).
    One open draft per language: asking again returns 409 with the existing one.
    """
    view = await _editable(session, subject, article_id)
    lang = KbLanguage(language).value
    if lang in view.drafts:
        raise Conflict(code="kb_draft_exists", params={"language": lang})
    versions = await _versions(session, view.article.id)
    base = view.published.get(lang) or view.published.get(view.article.default_language)
    if base is None:
        own = [v for v in versions if v.language == view.article.default_language]
        base = own[-1] if own else None
    if base is None:
        raise NotFound(code="kb_draft_not_found")
    number = max((v.number for v in versions if v.language == lang), default=0) + 1
    draft = KbArticleVersion(
        article_id=view.article.id,
        language=lang,
        number=number,
        status=VersionStatus.DRAFT.value,
        title=base.title,
        body_html=base.body_html,
        keywords=list(base.keywords),
        internal_note=base.internal_note if base.language == lang else None,
    )
    await VersionRepository(session).add(draft)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=view.article.id,
        version=view.article.version,
        kind="updated",
        changes=[Change("draft", None, f"{lang}:{number}")],
        source=source,
    )
    await _saved(session, view.article, lang, created=False, changed=["draft"])
    return draft


# --- lists ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArticleRow:
    """One line of a list: the article, and the version shown for it.

    In the reader's language when there is one, else its default language.
    """

    article: KbArticle
    version: KbArticleVersion


async def list_articles(  # noqa: PLR0913 - the list's filters, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    view: str,
    language: str,
    topic_id: uuid.UUID | None = None,
    query: str | None = None,
    limit: int = 50,
) -> list[ArticleRow]:
    """Articles of one view (REQ-KB-013, 077).

    `published`: what readers see; `my_drafts`: open drafts the subject may work on. Searched
    through the search port (WP-027) when `query` is given.
    """
    require(subject, VIEW)
    if not is_staff(subject):
        return []
    statuses = [VersionStatus.PUBLISHED.value] if view == "published" else [s.value for s in OPEN]
    statement = (
        select(KbArticle, KbArticleVersion)
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
                KbArticleVersion.status.in_(statuses),
            ),
        )
        .where(KbArticle.deleted_at.is_(None), staff_sees(subject))
    )
    if view != "published":
        statement = statement.where(drafts_visible(subject))
    if topic_id is not None:
        statement = statement.where(KbArticle.topic_id == topic_id)
    order: list[Any] = [KbArticle.updated_at.desc(), KbArticle.id]
    if query:
        found = await ENGINE.match(session, TEXT, query)
        if found is not None:
            statement = statement.where(found.predicate)
            order = [found.rank.desc(), *order]
    rows = (await session.execute(statement.order_by(*order).limit(limit * 2))).all()
    chosen: dict[uuid.UUID, ArticleRow] = {}
    for article, version in rows:
        current = chosen.get(article.id)
        if current is None or (
            version.language == language and current.version.language != language
        ):
            chosen[article.id] = ArticleRow(article, version)
    return list(chosen.values())[:limit]


def audience_text(view: ArticleView) -> dict[str, Any]:
    """The article's effective audience, for the screen to put in words (REQ-KB-045, 078)."""
    audience = article_audience(view.article, view.topic)
    return {
        "inherited": not view.article.own_audience,
        "tech_all": audience.tech_all,
        "tech_groups": sorted(str(g) for g in audience.tech_groups),
        "requesters": audience.requesters.value,
        "req_groups": sorted(str(g) for g in audience.req_groups),
        "req_sites": sorted(str(g) for g in audience.req_sites),
        "req_departments": sorted(str(g) for g in audience.req_departments),
    }
