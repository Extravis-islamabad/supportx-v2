"""Signed one-time action links over HTTP (WP-030 s3; REQ-NTF-024; app/shared/action_links).

    POST /api/v1/action-links/peek   {token}        what the link would do (never acts)
    POST /api/v1/action-links/use    {token, ...}   take its action once (audited, refusals too)

Both are POSTs with the token in the body: it never sits in a URL the server logs, and the
link's page reads it from the URL fragment (lane B's conditions 1 and 3). Both need the
recipient to be signed in (the interim default, plan D7) and are rate-limited (condition 4).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.shared import action_links
from app.shared.action_links.domain import TOKEN_LENGTH
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/action-links",
    tags=["action-links"],
    dependencies=[Depends(rate_limit("action_links"))],
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
NO_REFERRER = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


class TokenIn(BaseModel):
    """The link's token, from the page's URL fragment."""

    token: str = Field(min_length=TOKEN_LENGTH, max_length=TOKEN_LENGTH)


class UseIn(TokenIn):
    """The token, and what the action takes (e.g. a decision and its comment)."""

    body: dict[str, Any] = Field(default_factory=dict)


class OpenedOut(BaseModel):
    """What the link does, on what, until when, and what its page may show."""

    action: str
    object_type: str
    object_id: uuid.UUID
    expires_at: datetime
    summary: dict[str, Any]


@router.post("/peek", summary="What an action link would do")
async def peek(
    payload: TokenIn, session: TenantSession, subject: SignedIn, response: Response
) -> OpenedOut:
    """Never acts. 404 for an unknown link, 403 for someone else's, 409 used/expired/revoked."""
    response.headers.update(NO_REFERRER)
    opened = await action_links.peek(session, payload.token, subject)
    return OpenedOut(
        action=opened.action,
        object_type=opened.object_type,
        object_id=opened.object_id,
        expires_at=opened.expires_at,
        summary=dict(opened.summary),
    )


@router.post("/use", summary="Take an action link's action")
async def use(
    payload: UseIn,
    session: TenantSession,
    subject: SignedIn,
    response: Response,
    note: Annotated[AuditNote, audited("action_link.used", object_type="action_link")],
) -> dict[str, Any]:
    """Once: the link is marked used in the same transaction as the action."""
    response.headers.update(NO_REFERRER)
    opened, result = await action_links.use(session, payload.token, subject, payload.body)
    note.object_type = opened.object_type
    note.object_id = str(opened.object_id)
    note.details = {"action": opened.action}
    return dict(result)


__all__ = ["router"]
