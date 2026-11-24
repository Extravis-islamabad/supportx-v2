"""Asking for clarification on a request approval (WP-047a S3a; REQ-SR-037).

    POST /service-requests/{id}/approvals/{approval_id}/clarification    ask (If-Match)

Whoever may decide the approval may ask instead, in the console, the portal or the mobile app;
If-Match carries the approval's version, as a decision does, and the answer is the approval
with its question, its new version as the ETag.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import RequestFacts
from app.modules.identity_access import Subject
from app.modules.work_items.api.approval_routes import ApprovalOut
from app.modules.work_items.domain.clarifications import QUESTION_MAX, Addressee
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import clarifications
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of


class ClarificationIn(BaseModel):
    """The question, and whom it is for."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=QUESTION_MAX)
    addressee: Addressee = Field(
        default=Addressee.REQUESTER,
        description="requester (a public reply) or technician (a private note to them).",
    )


def add_clarification_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The clarification route of a request approval."""
    SignedIn = Annotated[Subject, Depends(require_signed_in())]  # noqa: N806 - type alias

    @router.post(
        "/{record_id}/approvals/{approval_id}/clarification", summary="Ask instead of deciding"
    )
    async def ask(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        approval_id: uuid.UUID,
        body: ClarificationIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: SignedIn,
        request: Request,
        response: Response,
    ) -> ApprovalOut:
        """The stage stays pending and its reminders pause until the answer comes (AC3)."""
        view = await clarifications.ask(
            session,
            subject,
            wtype,
            record_id,
            approval_id,
            question=body.question,
            addressee=body.addressee,
            expected_version=version,
            source=source_of(request),
            facts=RequestFacts.of(request),
        )
        record = await session.get(WorkItem, record_id)
        asked = (
            await clarifications.shown(session, subject, wtype, record)
            if record is not None
            else {}
        )
        set_etag(response, view.row.version)
        return ApprovalOut.of(view, asked.get(view.row.id))


__all__ = ["add_clarification_routes"]
