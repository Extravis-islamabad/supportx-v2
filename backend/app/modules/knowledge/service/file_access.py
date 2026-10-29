"""Who may see and attach an article's files (WP-033 session 2; files port, ADR-028 item 5).

The files service never reads knowledge tables: it asks here. One rule with the article page
(REQ-KB-048): whoever may read the article sees its files, so a withdrawn, expired or
out-of-audience article's images are hidden exactly as its text is. Attaching and removing are
for those who may edit it.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.identity_access import Subject
from app.modules.knowledge.service.articles import RECORD_TYPE, get_article
from app.modules.knowledge.service.notifications import RECORD_KIND
from app.shared.files.ports import Action, Actor, Owner, OwnerType


def _not_found() -> NotFound:
    return NotFound(code="file_owner_not_found")


def _subject(actor: Actor) -> Subject:
    if not isinstance(actor, Subject):  # the files routes always pass the caller's Subject
        raise _not_found()
    return actor


class ArticleFileAccess:
    """`FileOwnerAccess` for knowledge articles."""

    owner_types = frozenset({OwnerType.KB_ARTICLE})
    record_types = frozenset({RECORD_TYPE})
    channel_kind: str | None = RECORD_KIND

    async def check(
        self,
        session: AsyncSession,
        actor: Actor,
        owner_type: OwnerType,
        owner_id: uuid.UUID,
        action: Action,
    ) -> Owner:
        """The article, if `actor` may read it (view) or edit it (attach, remove)."""
        if owner_type != OwnerType.KB_ARTICLE:
            raise _not_found()
        subject = _subject(actor)
        try:
            view = await get_article(session, subject, owner_id)
        except (NotFound, PermissionDenied):
            raise _not_found() from None
        if action != Action.VIEW and not view.can_edit:
            raise PermissionDenied(code="permission_denied")
        return Owner(OwnerType.KB_ARTICLE, owner_id, RECORD_TYPE, owner_id)

    async def visible_owners(
        self, session: AsyncSession, actor: Actor, record_type: str, record_id: uuid.UUID
    ) -> set[tuple[OwnerType, uuid.UUID]]:
        """The article's files, for its readers; NotFound when the article is hidden."""
        if record_type != RECORD_TYPE:
            raise _not_found()
        try:
            await get_article(session, _subject(actor), record_id)
        except (NotFound, PermissionDenied):
            raise _not_found() from None
        return {(OwnerType.KB_ARTICLE, record_id)}


FILE_ACCESS = ArticleFileAccess()
