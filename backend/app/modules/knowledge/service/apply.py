"""Knowledge into a record's reply, and a record's resolution into knowledge (D-121).

- `check`: before anything is inserted, whether the people the record is for may read the
  article (the server's answer for the composer's warning, D-108 (3)). No side effects.
- `apply`: the article's published content (its images copied into the actor's drafts, lane B's
  `copy_to_drafts`) or its link, and the link recorded (`insert` / `link`).
- `from_record`: a new article from a resolved record, its link recorded (`created_from`), and
  what looks like personal data named for the author.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.identity_access import Subject
from app.modules.knowledge.domain.personal_data import Finding, find_personal_data
from app.modules.knowledge.service import links
from app.modules.knowledge.service.articles import ArticleView, create_article, get_article
from app.shared.files.ports import OwnerType
from app.shared.files.service.copies import NotCopied, copy_to_drafts
from app.shared.files.service.core import FileServices
from app.shared.history import Source
from app.shared.richtext import image_file_ids

Audience = Literal["public", "private"]
Mode = Literal["content", "link"]
TITLE_MAX = 250


@dataclass(frozen=True)
class Check:
    """What the composer needs before inserting."""

    visible_to_requester: bool | None  # None for a private note: nobody else reads it


async def check(  # noqa: PLR0913, PLR0917 - which article, which record, which audience
    session: AsyncSession,
    subject: Subject,
    article_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    audience: Audience,
) -> Check:
    """The warning's answer (D-108 (3)); 404 unless the actor may read both."""
    links.require_staff(subject)
    await get_article(session, subject, article_id)
    await links.require_record(session, subject, record_type, record_id)
    if audience == "private":
        return Check(None)
    return Check(
        await links.visible_to_people(session, subject, article_id, record_type, record_id)
    )


@dataclass(frozen=True)
class Applied:
    """What goes into the editor."""

    html: str
    title: str
    language: str
    fallback: bool  # the wanted language was not published: the other one is used
    visible_to_requester: bool | None
    not_copied: list[NotCopied]


def _published(view: ArticleView, language: str) -> tuple[str, bool]:
    if language in view.published:
        return language, False
    if not view.published:
        raise NotFound(code="kb_article_not_published")
    return min(view.published), True


async def apply(  # noqa: PLR0913, PLR0917 - which article, where, how, explicit
    session: AsyncSession,
    services: FileServices,
    subject: Subject,
    article_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    *,
    audience: Audience,
    mode: Mode,
    language: str,
    source: Source,
) -> Applied:
    """The article for the reply; nothing is copied for an article the actor cannot read."""
    answer = await check(session, subject, article_id, record_type, record_id, audience)
    view = await get_article(session, subject, article_id)
    shown, fallback = _published(view, language)
    version = view.published[shown]
    html, not_copied = "", []
    if mode == "content":
        html = version.body_html
        ids = [uuid.UUID(i) for i in image_file_ids(html)]
        copies = await copy_to_drafts(
            session,
            services,
            subject,
            owner_type=OwnerType.KB_ARTICLE,
            owner_id=article_id,
            file_ids=ids,
        )
        for old, new in copies.copied.items():
            html = html.replace(f'data-file-id="{old}"', f'data-file-id="{new}"')
        for missing in copies.not_copied:
            # An image that may not be copied now is left out, and named for the technician.
            html = _drop_image(html, missing.file_id)
        not_copied = copies.not_copied
    await links.link(
        session,
        subject,
        article_id,
        record_type,
        record_id,
        how="insert" if mode == "content" else "link",
        source=source,
    )
    return Applied(html, version.title, shown, fallback, answer.visible_to_requester, not_copied)


def _drop_image(html: str, file_id: uuid.UUID) -> str:
    return re.sub(rf'<img[^>]*\bdata-file-id="{file_id}"[^>]*>', "", html)


@dataclass(frozen=True)
class FromRecord:
    """The new draft, and what looks like personal data in it."""

    view: ArticleView
    findings: list[Finding]


async def from_record(  # noqa: PLR0913 - the record and the new article's place
    session: AsyncSession,
    subject: Subject,
    record_type: str,
    record_id: uuid.UUID,
    *,
    topic_id: uuid.UUID,
    type_code: str,
    source: Source,
) -> FromRecord:
    """A draft from the record's subject and resolution (REQ-KB-016); 404 without one."""
    links.require_staff(subject)
    found = await links.facts_for(record_type).resolution_of(session, subject, record_id)
    if found is None:
        raise NotFound(code="kb_record_has_no_resolution")
    title = " ".join(found.subject.split())[:TITLE_MAX]
    view = await create_article(
        session,
        subject,
        {
            "topic_id": topic_id,
            "type_code": type_code,
            "language": found.language,
            "title": title,
            "body_html": found.resolution_html,
        },
        source=source,
    )
    await links.link(
        session, subject, view.article.id, record_type, record_id, how="created_from", source=source
    )
    return FromRecord(view, find_personal_data(title, found.resolution_html))
