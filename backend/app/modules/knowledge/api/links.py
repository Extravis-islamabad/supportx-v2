"""Knowledge on records over HTTP (WP-033 session 4, D-121; REQ-KB-016, 063, 064).

Mounted on the knowledge router. Every route checks both ends: the article's reader rule and
the record owner's read rule (the shared records port). 404, never 403, for either one hidden.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import TenantSession
from app.modules.identity_access import user_names
from app.modules.knowledge.api.routes import ArticleOut, Viewer, router
from app.modules.knowledge.service import apply, articles, links
from app.modules.knowledge.service.articles import ArticleView
from app.shared.api.idempotency import Created, Idempotency
from app.shared.files.service.core import FileServices
from app.shared.history import source_of

FILES_STATE = "files"  # the system module keeps the API's FileServices on app.state
RecordType = Annotated[str, Field(pattern=r"^[a-z][a-z_]{1,29}$")]


def _files(request: Request) -> FileServices:
    """The API's file services (set by the system module at startup; built once otherwise)."""
    found: FileServices | None = getattr(request.app.state, FILES_STATE, None)
    if found is None:
        found = FileServices.from_settings(request.app.state.settings)
        setattr(request.app.state, FILES_STATE, found)
    return found


Files = Annotated[FileServices, Depends(_files)]


class RecordRef(BaseModel):
    """A record: its type (the work-item type code, `incident`) and id."""

    model_config = ConfigDict(extra="forbid")

    record_type: RecordType
    record_id: uuid.UUID


class LinkedRecordOut(BaseModel):
    """A record linked to an article, as a line of its Links tab."""

    link_id: uuid.UUID
    source: str
    linked_at: datetime
    record_type: str
    record_id: uuid.UUID
    display_id: str
    subject: str
    status_category: str


class ArticleLinksOut(BaseModel):
    """An article's links that you may see, and how many others."""

    items: list[LinkedRecordOut]
    restricted: int


class LinkedArticleOut(BaseModel):
    """An article linked to a record, as a line of the record's Knowledge card."""

    link_id: uuid.UUID
    source: str
    linked_at: datetime
    article: ArticleOut


class RecordArticlesOut(BaseModel):
    """A record's linked articles that you may read, and how many others."""

    items: list[LinkedArticleOut]
    restricted: int


@router.post(
    "/articles/{article_id}/links",
    summary="Link an article to a record",
    status_code=status.HTTP_201_CREATED,
    response_model=LinkedRecordOut,
)
async def create_link(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    body: RecordRef,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
) -> Response:
    """Staff who may read the article and open the record. Linking twice changes nothing."""

    async def go() -> Created:
        row, _ = await links.link(
            session,
            subject,
            article_id,
            body.record_type,
            body.record_id,
            how="link",
            source=source_of(request),
        )
        seen = await links.visible_records(session, subject, row.record_type, [row.record_id])
        summary = seen[row.record_id]
        return Created(
            body=LinkedRecordOut(
                link_id=row.id,
                source=row.source,
                linked_at=row.created_at,
                record_type=row.record_type,
                record_id=row.record_id,
                display_id=summary.display_id,
                subject=summary.subject,
                status_category=summary.status_category,
            )
        )

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.delete(
    "/articles/{article_id}/links/{link_id}",
    summary="Remove a link",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_link(
    article_id: uuid.UUID,
    link_id: uuid.UUID,
    session: TenantSession,
    subject: Viewer,
    request: Request,
) -> Response:
    """Needs edit rights on the article and sight of the record."""
    await links.unlink(session, subject, article_id, link_id, source=source_of(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/articles/{article_id}/links", summary="An article's linked records")
async def list_article_links(
    article_id: uuid.UUID, session: TenantSession, subject: Viewer
) -> ArticleLinksOut:
    """The records you may open; the others are only counted."""
    found = await links.article_links(session, subject, article_id)
    return ArticleLinksOut(
        items=[
            LinkedRecordOut(
                link_id=row.id,
                source=row.source,
                linked_at=row.created_at,
                record_type=row.record_type,
                record_id=row.record_id,
                display_id=summary.display_id,
                subject=summary.subject,
                status_category=summary.status_category,
            )
            for row, summary in found.shown
        ],
        restricted=found.restricted,
    )


async def _article_out(session: TenantSession, views: list[ArticleView]) -> list[ArticleOut]:
    owners = await user_names(session, sorted({str(v.article.owner_id) for v in views}))
    return [ArticleOut.of(v, owners.get(str(v.article.owner_id))) for v in views]


@router.get("/records/{record_type}/{record_id}/articles", summary="A record's linked articles")
async def list_record_articles(
    record_type: RecordType, record_id: uuid.UUID, session: TenantSession, subject: Viewer
) -> RecordArticlesOut:
    """The articles you may read; the others are only counted. 404 without sight of the record."""
    found = await links.record_articles(session, subject, record_type, record_id)
    shown = await _article_out(session, [view for _, view in found.shown])
    return RecordArticlesOut(
        items=[
            LinkedArticleOut(
                link_id=row.id, source=row.source, linked_at=row.created_at, article=article
            )
            for (row, _), article in zip(found.shown, shown, strict=True)
        ],
        restricted=found.restricted,
    )


class ApplyCheckOut(BaseModel):
    """The composer's warning, decided by the server (D-108 (3))."""

    visible_to_requester: bool | None = Field(
        description="False: the people the record is for cannot read this article. None: a "
        "private note, read by staff only."
    )


@router.get("/articles/{article_id}/apply-check", summary="May the requester read it?")
async def apply_check(  # noqa: PLR0913, PLR0917 - FastAPI query parameters
    article_id: uuid.UUID,
    record_type: RecordType,
    record_id: uuid.UUID,
    audience: Literal["public", "private"],
    session: TenantSession,
    subject: Viewer,
) -> ApplyCheckOut:
    """Before inserting into a reply; changes nothing."""
    found = await apply.check(session, subject, article_id, record_type, record_id, audience)
    return ApplyCheckOut(visible_to_requester=found.visible_to_requester)


class ApplyIn(RecordRef):
    """Insert an article into a reply (REQ-KB-063)."""

    audience: Literal["public", "private"]
    mode: Literal["content", "link"]
    language: Literal["en", "ar"] = "en"


class NotCopiedOut(BaseModel):
    """An image of the article that was left out, and why."""

    file_id: uuid.UUID
    reason: str


class AppliedOut(BaseModel):
    """What goes into the editor: content with copied images, or the article's title for a link."""

    article_id: uuid.UUID
    display_id: str
    title: str
    language: str
    fallback: bool = Field(description="The wanted language is not published: the other one.")
    html: str = Field(description="Sanitised; empty for a link.")
    visible_to_requester: bool | None
    images_not_copied: list[NotCopiedOut]


@router.post("/articles/{article_id}/apply", summary="Insert an article into a reply")
async def apply_article(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    article_id: uuid.UUID,
    body: ApplyIn,
    session: TenantSession,
    subject: Viewer,
    files: Files,
    request: Request,
) -> AppliedOut:
    """Content (its images copied into your drafts) or a link; the link to the record is kept."""
    done = await apply.apply(
        session,
        files,
        subject,
        article_id,
        body.record_type,
        body.record_id,
        audience=body.audience,
        mode=body.mode,
        language=body.language,
        source=source_of(request),
    )
    view = await articles.get_article(session, subject, article_id)
    return AppliedOut(
        article_id=article_id,
        display_id=view.article.display_id,
        title=done.title,
        language=done.language,
        fallback=done.fallback,
        html=done.html,
        visible_to_requester=done.visible_to_requester,
        images_not_copied=[
            NotCopiedOut(file_id=n.file_id, reason=n.reason) for n in done.not_copied
        ],
    )


class FromRecordIn(RecordRef):
    """Save a record's resolution as knowledge (REQ-KB-016)."""

    topic_id: uuid.UUID
    type_code: str = Field(default="how_to", max_length=40)


class FindingOut(BaseModel):
    """Something that looks like personal data: where, and what kind."""

    field: Literal["title", "body"]
    kind: Literal["email", "phone", "account_number", "password"]


class FromRecordOut(BaseModel):
    """The new article and draft, and what the author should look at before submitting."""

    article: ArticleOut
    personal_data: list[FindingOut]


@router.post(
    "/articles/from-record",
    summary="Save a resolution as knowledge",
    status_code=status.HTTP_201_CREATED,
    response_model=FromRecordOut,
)
async def create_from_record(
    body: FromRecordIn,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
) -> Response:
    """Needs `knowledge.create` and sight of the record; it must have a resolution."""

    async def go() -> Created:
        made = await apply.from_record(
            session,
            subject,
            body.record_type,
            body.record_id,
            topic_id=body.topic_id,
            type_code=body.type_code,
            source=source_of(request),
        )
        (article,) = await _article_out(session, [made.view])
        return Created(
            body=FromRecordOut(
                article=article,
                personal_data=[FindingOut(field=f.field, kind=f.kind) for f in made.findings],
            ),
            headers={"ETag": f'"{article.version}"'},
        )

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)
