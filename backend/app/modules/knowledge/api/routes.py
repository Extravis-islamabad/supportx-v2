"""Knowledge over HTTP (WP-033 sessions 1-2): `/api/v1/knowledge`.

Topics, articles and their drafts (session 1); review and approval, withdrawal, "still
correct", trash, versions, settings and requesters' reading (session 2, D-108). Static paths
come before `/{id}`.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.knowledge.infra.models import KbArticleVersion, KbTopic, KbType
from app.modules.knowledge.service import articles, review, topics
from app.modules.knowledge.service.access import VIEW
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Responses = dict[int | str, dict[str, Any]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such topic or article visible to you."},
}
CONFLICT: Responses = {409: {"model": ProblemDetail, "description": "Stale If-Match."}}

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(rate_limit("knowledge"))],
    responses=RESPONSES,
)
Viewer = Annotated[Subject, Depends(require_permission(VIEW))]
Language = Literal["en", "ar"]


# --- schemas ------------------------------------------------------------------------------------


class AudienceIn(BaseModel):
    """Who may read (REQ-KB-044, 045): technicians (all or groups) and requesters."""

    model_config = ConfigDict(extra="forbid")

    tech_all: bool = True
    tech_groups: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    requesters: Literal["none", "all", "selected"] = "none"
    req_groups: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    req_sites: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    req_departments: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class TopicIn(AudienceIn):
    """A new topic: a name per language, optionally under a parent (REQ-KB-003)."""

    names: dict[Literal["en", "ar", "ur"], str]
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=1000)
    icon: str | None = Field(default=None, max_length=40)
    owner_id: uuid.UUID | None = None


class TopicPatch(BaseModel):
    """The fields to change (a move sends `parent_id`, null for the top)."""

    model_config = ConfigDict(extra="forbid")

    names: dict[Literal["en", "ar", "ur"], str] | None = None
    parent_id: uuid.UUID | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    description: str | None = Field(default=None, max_length=1000)
    icon: str | None = Field(default=None, max_length=40)
    owner_id: uuid.UUID | None = None
    tech_all: bool | None = None
    tech_groups: list[uuid.UUID] | None = Field(default=None, max_length=200)
    requesters: Literal["none", "all", "selected"] | None = None
    req_groups: list[uuid.UUID] | None = Field(default=None, max_length=200)
    req_sites: list[uuid.UUID] | None = Field(default=None, max_length=200)
    req_departments: list[uuid.UUID] | None = Field(default=None, max_length=200)


class TopicDeleteIn(BaseModel):
    """Where a topic's articles go before it goes to the trash (REQ-KB-004 AC2)."""

    model_config = ConfigDict(extra="forbid")

    move_to: uuid.UUID | None = None


class TopicOut(BaseModel):
    """A topic of the tree (names per language; the UI falls back to English)."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    depth: int
    sort_order: int
    names: dict[str, str]
    description: str | None
    icon: str | None
    owner_id: uuid.UUID | None
    tech_all: bool
    tech_groups: list[uuid.UUID]
    requesters: str
    req_groups: list[uuid.UUID]
    req_sites: list[uuid.UUID]
    req_departments: list[uuid.UUID]
    version: int

    @classmethod
    def of(cls, topic: KbTopic) -> "TopicOut":
        """From the row."""
        return cls(
            id=topic.id,
            parent_id=topic.parent_id,
            depth=topic.depth,
            sort_order=topic.sort_order,
            names=dict(topic.names),
            description=topic.description,
            icon=topic.icon,
            owner_id=topic.owner_id,
            tech_all=topic.tech_all,
            tech_groups=list(topic.tech_groups),
            requesters=topic.requesters,
            req_groups=list(topic.req_groups),
            req_sites=list(topic.req_sites),
            req_departments=list(topic.req_departments),
            version=topic.version,
        )


class ArticleTypeOut(BaseModel):
    """An article type (built-in ones are named by `kb_type.<code>`)."""

    code: str
    names: dict[str, str]
    review_months: int
    builtin: bool
    retired: bool

    @classmethod
    def of(cls, kind: KbType) -> "ArticleTypeOut":
        """From the row."""
        return cls(
            code=kind.code,
            names=dict(kind.names),
            review_months=kind.review_months,
            builtin=kind.builtin,
            retired=kind.retired_at is not None,
        )


class ArticleIn(AudienceIn):
    """A new article and its first draft (REQ-KB-001, 012)."""

    topic_id: uuid.UUID
    type_code: str = Field(max_length=40)
    language: Language = "en"
    title: str = Field(max_length=250)
    body_html: str = Field(default="", max_length=500000, description="Rich text, sanitised.")
    keywords: list[str] = Field(default_factory=list, max_length=30)
    internal_note: str | None = Field(default=None, max_length=2000)
    own_audience: bool = False
    review_on: date | None = None
    expires_on: date | None = None


class ArticlePatch(BaseModel):
    """What to change on the article itself (the fields sent)."""

    model_config = ConfigDict(extra="forbid")

    topic_id: uuid.UUID | None = None
    type_code: str | None = Field(default=None, max_length=40)
    owner_id: uuid.UUID | None = None
    own_audience: bool | None = None
    tech_all: bool | None = None
    tech_groups: list[uuid.UUID] | None = Field(default=None, max_length=200)
    requesters: Literal["none", "all", "selected"] | None = None
    req_groups: list[uuid.UUID] | None = Field(default=None, max_length=200)
    req_sites: list[uuid.UUID] | None = Field(default=None, max_length=200)
    req_departments: list[uuid.UUID] | None = Field(default=None, max_length=200)
    review_on: date | None = None
    expires_on: date | None = None


class DraftPatch(BaseModel):
    """Autosave of a draft (REQ-KB-013): the fields sent."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=250)
    body_html: str | None = Field(default=None, max_length=500000)
    keywords: list[str] | None = Field(default=None, max_length=30)
    internal_note: str | None = Field(default=None, max_length=2000)
    change_note: str | None = Field(default=None, max_length=500)


class VersionOut(BaseModel):
    """One version of one language. `internal_note` only for those who may edit (KB-001 AC2)."""

    id: uuid.UUID
    language: str
    number: int
    status: str
    title: str
    body_html: str
    keywords: list[str]
    change_note: str | None
    internal_note: str | None
    reject_reason: str | None
    version: int
    updated_at: datetime
    published_at: datetime | None

    @classmethod
    def of(cls, version: KbArticleVersion, *, editor: bool) -> "VersionOut":
        """From the row; the internal note left out for readers."""
        return cls(
            id=version.id,
            language=version.language,
            number=version.number,
            status=version.status,
            title=version.title,
            body_html=version.body_html,
            keywords=list(version.keywords),
            change_note=version.change_note,
            internal_note=version.internal_note if editor else None,
            reject_reason=version.reject_reason if editor else None,
            version=version.version,
            updated_at=version.updated_at,
            published_at=version.published_at,
        )


class ArticleOut(BaseModel):
    """An article as you see it: its published versions, and its drafts if you may see them."""

    id: uuid.UUID
    display_id: str
    topic_id: uuid.UUID
    type_code: str
    owner_id: uuid.UUID
    default_language: str
    audience: dict[str, Any]
    review_on: date | None
    expires_on: date | None
    expired: bool
    review_due: bool
    withdrawn: bool
    withdrawn_reason: str | None = Field(description="For editors and withdrawers only.")
    published: dict[str, VersionOut]
    drafts: dict[str, VersionOut]
    can_edit: bool
    can_approve: bool
    can_withdraw: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, view: articles.ArticleView) -> "ArticleOut":
        """From the service view."""
        article = view.article
        return cls(
            id=article.id,
            display_id=article.display_id,
            topic_id=article.topic_id,
            type_code=article.type_code,
            owner_id=article.owner_id,
            default_language=article.default_language,
            audience=articles.audience_text(view),
            review_on=article.review_on,
            expires_on=article.expires_on,
            expired=view.expired,
            review_due=view.review_due,
            withdrawn=article.withdrawn_at is not None,
            withdrawn_reason=(
                article.withdrawn_reason if view.can_edit or view.can_withdraw else None
            ),
            published={
                k: VersionOut.of(v, editor=view.can_edit) for k, v in view.published.items()
            },
            drafts={k: VersionOut.of(v, editor=True) for k, v in view.drafts.items()},
            can_edit=view.can_edit,
            can_approve=view.can_approve,
            can_withdraw=view.can_withdraw,
            version=article.version,
            created_at=article.created_at,
            updated_at=article.updated_at,
        )


class ArticleRowOut(BaseModel):
    """One line of the knowledge list."""

    id: uuid.UUID
    display_id: str
    topic_id: uuid.UUID
    type_code: str
    language: str
    title: str
    status: str
    review_on: date | None
    updated_at: datetime


# --- topics ---------------------------------------------------------------------------------------


@router.get("/topics", summary="The topic tree")
async def list_topics(session: TenantSession, subject: Viewer) -> list[TopicOut]:
    """Topics you may see, parents first, in their order."""
    return [TopicOut.of(t) for t in await topics.list_topics(session, subject)]


@router.post("/topics", summary="Create a topic", status_code=status.HTTP_201_CREATED)
async def create_topic(
    body: TopicIn,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
) -> Response:
    """Needs `knowledge.manage_topics`. At the top, or under `parent_id` (≤ 6 levels)."""

    async def go() -> Created:
        topic = await topics.create_topic(
            session, subject, body.model_dump(), source=source_of(request)
        )
        out = TopicOut.of(topic)
        return Created(body=out, headers={"ETag": f'"{out.version}"'})

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.patch("/topics/{topic_id}", summary="Change a topic", responses=CONFLICT)
async def update_topic(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    topic_id: uuid.UUID,
    body: TopicPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> TopicOut:
    """Rename, reorder, move (with its subtopics) or change its audience. Needs If-Match."""
    topic = await topics.update_topic(
        session,
        subject,
        topic_id,
        {name: getattr(body, name) for name in body.model_fields_set},
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, topic.version)
    return TopicOut.of(topic)


@router.delete(
    "/topics/{topic_id}",
    summary="Delete a topic",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_topic(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    topic_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    move_to: Annotated[uuid.UUID | None, Query(description="Where its articles go.")] = None,
) -> None:
    """To the trash with its subtopics; their articles move to `move_to` first."""
    await topics.delete_topic(
        session,
        subject,
        topic_id,
        move_to=move_to,
        expected_version=version,
        source=source_of(request),
    )


# --- types ----------------------------------------------------------------------------------------


@router.get("/types", summary="Article types")
async def list_types(session: TenantSession, subject: Viewer) -> list[ArticleTypeOut]:
    """The organisation's article types (file 08 Appendix A defaults on first use)."""
    del subject
    return [ArticleTypeOut.of(t) for t in await articles.article_types(session)]


# --- articles -------------------------------------------------------------------------------------


@router.get("/articles", summary="Articles")
async def list_articles(  # noqa: PLR0913, PLR0917 - FastAPI query parameters
    session: TenantSession,
    subject: Viewer,
    view: Annotated[
        Literal[
            "published",
            "my_drafts",
            "in_review",
            "awaiting_approval",
            "review_due",
            "expired",
            "trash",
        ],
        Query(),
    ] = "published",
    language: Annotated[Language, Query()] = "en",
    topic_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200, description="Search words.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ArticleRowOut]:
    """Published articles you may read, or the drafts you may work on; searchable."""
    rows = await articles.list_articles(
        session, subject, view=view, language=language, topic_id=topic_id, query=q, limit=limit
    )
    return [
        ArticleRowOut(
            id=r.article.id,
            display_id=r.article.display_id,
            topic_id=r.article.topic_id,
            type_code=r.article.type_code,
            language=r.version.language,
            title=r.version.title,
            status=r.version.status,
            review_on=r.article.review_on,
            updated_at=r.article.updated_at,
        )
        for r in rows
    ]


@router.post("/articles", summary="Write an article", status_code=status.HTTP_201_CREATED)
async def create_article(
    body: ArticleIn,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
) -> Response:
    """Needs `knowledge.create`. Creates the article and its first draft."""

    async def go() -> Created:
        view = await articles.create_article(
            session, subject, body.model_dump(), source=source_of(request)
        )
        out = ArticleOut.of(view)
        return Created(
            body=out,
            headers={
                "Location": f"/api/v1/knowledge/articles/{out.id}",
                "ETag": f'"{out.version}"',
            },
        )

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.get("/articles/{article_id}", summary="Get an article")
async def get_article(
    article_id: uuid.UUID, session: TenantSession, subject: Viewer, response: Response
) -> ArticleOut:
    """Published versions for its audience; drafts for its author, owners and approvers."""
    view = await articles.get_article(session, subject, article_id)
    set_etag(response, view.article.version)
    return ArticleOut.of(view)


@router.patch("/articles/{article_id}", summary="Change an article", responses=CONFLICT)
async def update_article(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    body: ArticlePatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> ArticleOut:
    """Topic, type, owner, its own audience and dates. Needs If-Match."""
    view = await articles.update_article(
        session,
        subject,
        article_id,
        {name: getattr(body, name) for name in body.model_fields_set},
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, view.article.version)
    return ArticleOut.of(view)


@router.post(
    "/articles/{article_id}/drafts/{language}",
    summary="Start a draft",
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ProblemDetail, "description": "kb_draft_exists."}},
)
async def new_draft(
    article_id: uuid.UUID,
    language: Language,
    session: TenantSession,
    subject: Viewer,
    request: Request,
) -> VersionOut:
    """A new version from the published one, or a translation (same ID, topic and audience)."""
    draft = await articles.new_draft(
        session, subject, article_id, language, source=source_of(request)
    )
    return VersionOut.of(draft, editor=True)


@router.patch(
    "/articles/{article_id}/drafts/{language}", summary="Save a draft", responses=CONFLICT
)
async def save_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    language: Language,
    body: DraftPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> VersionOut:
    """Autosave (REQ-KB-013). If-Match carries the draft's own version."""
    draft = await articles.save_draft(
        session,
        subject,
        article_id,
        language,
        {name: getattr(body, name) for name in body.model_fields_set},
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, draft.version)
    return VersionOut.of(draft, editor=True)


# --- session 2: review and approval (REQ-KB-027, 028) ---------------------------------------------


class SubmitIn(BaseModel):
    """Send a draft to review, with an optional note for the approver."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    """A reason, required (sending back, withdrawing)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=2000)


@router.post(
    "/articles/{article_id}/drafts/{language}/submit",
    summary="Send a draft to review",
    responses=CONFLICT,
)
async def submit_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    language: Language,
    body: SubmitIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> VersionOut:
    """If-Match carries the draft's version. Approvers see it at once (no mail needed)."""
    submitted = await review.submit(
        session,
        subject,
        article_id,
        language,
        note=body.note,
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, submitted.version)
    return VersionOut.of(submitted, editor=True)


@router.post(
    "/articles/{article_id}/drafts/{language}/approve",
    summary="Approve and publish",
    responses=CONFLICT,
    dependencies=[
        audited(
            "knowledge.article_approved",
            object_type="kb_article",
            object_param="article_id",
            detail_params=("language",),
        )
    ],
)
async def approve_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    language: Language,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> ArticleOut:
    """Publishes the version in review; the previous one is replaced at the same moment."""
    view = await review.approve(
        session, subject, article_id, language, expected_version=version, source=source_of(request)
    )
    set_etag(response, view.article.version)
    return ArticleOut.of(view)


@router.post(
    "/articles/{article_id}/drafts/{language}/reject",
    summary="Send back to the author",
    responses=CONFLICT,
)
async def reject_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    language: Language,
    body: ReasonIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> VersionOut:
    """The version becomes a draft again; the author sees the reason."""
    rejected = await review.reject(
        session,
        subject,
        article_id,
        language,
        reason=body.reason,
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, rejected.version)
    return VersionOut.of(rejected, editor=True)


# --- session 2: withdraw, still correct, trash, versions (REQ-KB-020, 031, 034, 079) --------------


@router.post(
    "/articles/{article_id}/withdraw",
    summary="Withdraw",
    responses=CONFLICT,
    dependencies=[
        audited("knowledge.article_withdrawn", object_type="kb_article", object_param="article_id")
    ],
)
async def withdraw_article(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    body: ReasonIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> ArticleOut:
    """Off every reader path at once; approving a new version brings it back."""
    view = await review.withdraw(
        session,
        subject,
        article_id,
        reason=body.reason,
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, view.article.version)
    return ArticleOut.of(view)


@router.post("/articles/{article_id}/still-correct", summary="Still correct", responses=CONFLICT)
async def still_correct(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> ArticleOut:
    """Records a review; the review date moves on, with no new version."""
    view = await review.still_correct(
        session, subject, article_id, expected_version=version, source=source_of(request)
    )
    set_etag(response, view.article.version)
    return ArticleOut.of(view)


@router.delete(
    "/articles/{article_id}",
    summary="Move to the trash",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[
        audited("knowledge.article_deleted", object_type="kb_article", object_param="article_id")
    ],
)
async def delete_article(
    article_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
) -> None:
    """Restorable; nothing is deleted for good here (GDPR erasure jobs only)."""
    await review.delete_article(
        session, subject, article_id, expected_version=version, source=source_of(request)
    )


@router.post(
    "/articles/{article_id}/restore",
    summary="Restore from the trash",
    responses=CONFLICT,
    dependencies=[
        audited("knowledge.article_restored", object_type="kb_article", object_param="article_id")
    ],
)
async def restore_article(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> ArticleOut:
    """Back into its topic (409 kb_topic_in_trash while the topic is in the trash)."""
    view = await review.restore_article(
        session, subject, article_id, expected_version=version, source=source_of(request)
    )
    set_etag(response, view.article.version)
    return ArticleOut.of(view)


@router.get("/articles/{article_id}/versions", summary="Versions")
async def article_versions(
    article_id: uuid.UUID, session: TenantSession, subject: Viewer
) -> list[VersionOut]:
    """Published and earlier versions; drafts and reviews for those who may see them."""
    view = await articles.get_article(session, subject, article_id)
    found = await review.list_versions(session, subject, article_id)
    return [VersionOut.of(v, editor=view.can_edit or view.can_approve) for v in found]


# --- session 2: the approval count and settings (REQ-KB-086, 090) ---------------------------------


class CountOut(BaseModel):
    """A number for a menu badge."""

    count: int


@router.get("/approvals/count", summary="Articles awaiting my approval")
async def approvals_count(session: TenantSession, subject: Viewer) -> CountOut:
    """The live count in the Knowledge menu (refreshed by realtime)."""
    return CountOut(count=await review.awaiting_count(session, subject))


class SettingsOut(BaseModel):
    """Knowledge settings (REQ-KB-090)."""

    prefix: str
    self_approval: bool
    requesters_enabled: bool
    version: int


class SettingsPatch(BaseModel):
    """Change knowledge settings (If-Match)."""

    model_config = ConfigDict(extra="forbid")

    self_approval: bool | None = None
    requesters_enabled: bool | None = None


@router.get("/settings", summary="Knowledge settings")
async def get_settings(session: TenantSession, subject: Viewer, response: Response) -> SettingsOut:
    """Read by every reader (the screens need self-approval); changed by settings managers."""
    del subject
    found = await articles.settings_row(session)
    set_etag(response, found.version)
    return SettingsOut(
        prefix=found.prefix,
        self_approval=found.self_approval,
        requesters_enabled=found.requesters_enabled,
        version=found.version,
    )


@router.patch(
    "/settings",
    summary="Change knowledge settings",
    responses=CONFLICT,
    dependencies=[audited("knowledge.settings_changed", object_type="kb_settings")],
)
async def patch_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: SettingsPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> SettingsOut:
    """Needs `knowledge.manage_settings`."""
    values = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    found = await review.update_settings(
        session, subject, values, expected_version=version, source=source_of(request)
    )
    set_etag(response, found.version)
    return SettingsOut(
        prefix=found.prefix,
        self_approval=found.self_approval,
        requesters_enabled=found.requesters_enabled,
        version=found.version,
    )
