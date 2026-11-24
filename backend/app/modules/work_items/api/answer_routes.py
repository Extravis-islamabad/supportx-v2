"""Changing a service request's answers after submitting (WP-047a S3b; REQ-SR-041).

    PATCH /service-requests/{id}/answers    the answers given and/or the quantity (If-Match)

Staff with the request's edit right. A change the item marks as "restarts approval" starts the
approval again from its first stage (the answer says which keys did); any other change is
recorded only.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import RequestFacts
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import restarts
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of


class AnswersIn(BaseModel):
    """What changes: the answers given replace those keys; the quantity, if the item asks it."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, Any] | None = Field(default=None, description="Question key → answer.")
    quantity: int | None = Field(default=None, ge=1)


class AnswersOut(BaseModel):
    """The request's new version, and what restarted its approval (empty: nothing did)."""

    version: int
    restarted: list[str] = Field(
        description="The changed keys that restarted approval (answer keys, quantity, "
        "requested_for)."
    )


def add_answer_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The request's answers after submitting."""
    Edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]  # noqa: N806 - type alias

    @router.patch("/{record_id}/answers", summary="Change a request's answers")
    async def change_answers(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: AnswersIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Edit,
        request: Request,
        response: Response,
    ) -> AnswersOut:
        """If-Match: the request's version; its new version comes back as the ETag."""
        record, keys = await restarts.change_answers(
            session,
            subject,
            wtype,
            record_id,
            answers=body.answers,
            quantity=body.quantity,
            expected_version=version,
            source=source_of(request),
            facts=RequestFacts.of(request),
        )
        set_etag(response, record.version)
        return AnswersOut(version=record.version, restarted=keys)


__all__ = ["add_answer_routes"]
