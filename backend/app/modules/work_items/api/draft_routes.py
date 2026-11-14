"""Kept drafts of unsent create forms (WP-046a S5c; REQ-INC-019).

    GET    /api/v1/drafts/{form_key}   your own draft of the form (404 when none)
    PUT    /api/v1/drafts/{form_key}   keep it (If-Match: 0 for a new one)
    DELETE /api/v1/drafts/{form_key}   discard it

Only the forms that keep drafts (`incident-new`) are accepted (422 otherwise), only by people who
may create that type, and only ever the caller's own draft: anyone else's is never reached, admins
included. Saves are limited per person (60 a minute: a save every 3 s from two tabs). No audit:
a draft is personal and unsent; the record it becomes is audited (lane B).
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.config import Settings
from app.core.database import TenantSession
from app.core.errors import FieldError, PermissionDenied, ProblemDetail, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.work_items.domain import drafts as rules
from app.modules.work_items.domain.types import TYPES
from app.modules.work_items.service import drafts as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/drafts",
    tags=["work-items"],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "May not create this type of record."},
        404: {"model": ProblemDetail, "description": "No draft (draft_not_found)."},
    },
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
# The request itself, before it is read as JSON: twice the values' cap leaves room for escaping.
REQUEST_MAX = rules.BODY_MAX * 2


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(_settings)]


class KeptDraftIn(BaseModel):
    """The form's values as typed (plain values only; checked again when the record is sent)."""

    values: dict[str, Any] = Field(description="Field name → value, as the form holds them.")


class KeptDraftOut(BaseModel):
    """Your kept draft: its values, or that it could not be read (then only Discard)."""

    form_key: str
    version: int
    updated_at: datetime
    unreadable: bool = Field(description="True: the draft could not be read; discard it.")
    values: dict[str, Any] | None


def _may_create(subject: Subject, form_key: str) -> None:
    code = rules.form_type(form_key)
    if code is None:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="path.form_key",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            ]
        )
    wtype = next(t for t in TYPES.values() if t.code == code)
    if not subject.holds(wtype.permission("create")):
        raise PermissionDenied(params={"permission": wtype.permission("create")})


@router.get(
    "/{form_key}",
    summary="Your kept draft of a form",
    dependencies=[Depends(rate_limit("work_items"))],
)
async def get_draft(
    form_key: str, session: TenantSession, subject: SignedIn, settings: AppSettings
) -> KeptDraftOut:
    """Only your own; values are null when it could not be read."""
    _may_create(subject, form_key)
    kept = await service.get(session, settings, subject.user_id, form_key)
    return KeptDraftOut(
        form_key=form_key,
        version=kept.version,
        updated_at=kept.updated_at,
        unreadable=kept.values is None,
        values=kept.values,
    )


@router.put(
    "/{form_key}",
    summary="Keep a draft of a form",
    responses={409: {"model": ProblemDetail, "description": "Stale If-Match."}},
    dependencies=[Depends(rate_limit("work_item_drafts"))],
)
async def put_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    form_key: str,
    body: KeptDraftIn,
    request: Request,
    session: TenantSession,
    subject: SignedIn,
    settings: AppSettings,
    version: ExpectedVersion,
    response: Response,
) -> KeptDraftOut:
    """If-Match: the version you have ("0" for a new draft). 64 KB of values at most."""
    _may_create(subject, form_key)
    if int(request.headers.get("content-length") or 0) > REQUEST_MAX:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.values",
                    code=rules.TOO_LARGE,
                    message_key=f"errors.field.{rules.TOO_LARGE}",
                )
            ]
        )
    kept = await service.put(
        session,
        settings,
        subject.tenant_id,
        subject.user_id,
        form_key,
        body.values,
        expected_version=version,
    )
    set_etag(response, kept)
    found = await service.get(session, settings, subject.user_id, form_key)
    return KeptDraftOut(
        form_key=form_key,
        version=found.version,
        updated_at=found.updated_at,
        unreadable=found.values is None,
        values=None,  # the caller has them: never sent back on a save
    )


@router.delete(
    "/{form_key}",
    summary="Discard a kept draft",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("work_items"))],
)
async def discard_draft(form_key: str, session: TenantSession, subject: SignedIn) -> None:
    """Nothing kept is fine."""
    _may_create(subject, form_key)
    await service.discard(session, subject.user_id, form_key)
