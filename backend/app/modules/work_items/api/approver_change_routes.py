"""Adjusting a service request's running approval (WP-047a S2b; REQ-SR-042).

Each action needs `requests.modify_approvers` on the request and a reason; it answers with the
request's approvals as `GET /{record_id}/approvals` does, so the screen replaces its list.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import RequestFacts
from app.modules.identity_access import Subject
from app.modules.work_items.api.approval_routes import ApprovalsOut, approvals_out
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import approver_changes as changes
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of

REASON = Field(min_length=1, max_length=changes.REASON_MAX, description="Why; in the history.")


class AddApproverIn(BaseModel):
    """A person for a stage that is open now."""

    model_config = ConfigDict(extra="forbid")

    stage: int = Field(ge=1, le=changes.MAX_STAGES)
    approver_id: uuid.UUID
    reason: str = REASON


class ReplaceApproverIn(BaseModel):
    """The person to ask instead (AC1)."""

    model_config = ConfigDict(extra="forbid")

    approver_id: uuid.UUID
    reason: str = REASON


class AddStageIn(BaseModel):
    """A stage after the last one: its people and how they decide (Professional)."""

    model_config = ConfigDict(extra="forbid")

    approver_ids: list[uuid.UUID] = Field(min_length=1, max_length=changes.MAX_APPROVERS)
    rule: rules.LevelRule = rules.LevelRule.ANY
    reason: str = REASON


class RemindIn(BaseModel):
    """Why the open stage's approvers are asked again."""

    model_config = ConfigDict(extra="forbid")

    reason: str = REASON


async def _answer(
    session: TenantSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    response: Response,
) -> ApprovalsOut:
    """The approvals, with the request's new version as the ETag (the next If-Match)."""
    record = await session.get(WorkItem, record_id)
    if record is not None:
        set_etag(response, record.version)
    return await approvals_out(session, subject, wtype, record_id)


def add_approver_change_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The four actions on a request's running approval (If-Match: the request's version).

    Each answers with the new version as its ETag.
    """
    Modify = Annotated[  # noqa: N806 - type alias
        Subject, Depends(require_permission(wtype.permission(changes.MODIFY)))
    ]

    @router.post("/{record_id}/approvals/approvers", summary="Add an approver to an open stage")
    async def add_approver(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: AddApproverIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Modify,
        request: Request,
        response: Response,
    ) -> ApprovalsOut:
        """They are asked at once; the reason goes in the history."""
        await changes.add_approver(
            session,
            subject,
            record_id,
            stage=body.stage,
            approver_id=body.approver_id,
            reason=body.reason,
            expected_version=version,
            source=source_of(request),
            facts=RequestFacts.of(request),
        )
        return await _answer(session, subject, wtype, record_id, response)

    @router.post("/{record_id}/approvals/{approval_id}/replace", summary="Ask someone else instead")
    async def replace_approver(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        approval_id: uuid.UUID,
        body: ReplaceApproverIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Modify,
        request: Request,
        response: Response,
    ) -> ApprovalsOut:
        """The old approval is withdrawn as `replaced`, its link revoked; the new person asked."""
        await changes.replace_approver(
            session,
            subject,
            record_id,
            approval_id,
            approver_id=body.approver_id,
            reason=body.reason,
            expected_version=version,
            source=source_of(request),
            facts=RequestFacts.of(request),
        )
        return await _answer(session, subject, wtype, record_id, response)

    @router.post("/{record_id}/approvals/stages", summary="Add a stage after the last one")
    async def add_stage(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: AddStageIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Modify,
        request: Request,
        response: Response,
    ) -> ApprovalsOut:
        """It opens when the stages before it pass (Professional: `catalog`)."""
        await changes.add_stage(
            session,
            subject,
            record_id,
            approver_ids=body.approver_ids,
            rule=body.rule,
            reason=body.reason,
            expected_version=version,
            source=source_of(request),
            facts=RequestFacts.of(request),
        )
        return await _answer(session, subject, wtype, record_id, response)

    @router.post("/{record_id}/approvals/reminders", summary="Remind the open stage's approvers")
    async def remind(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: RemindIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Modify,
        request: Request,
        response: Response,
    ) -> ApprovalsOut:
        """At most once every 10 minutes and 10 times per request."""
        await changes.remind(
            session,
            subject,
            record_id,
            reason=body.reason,
            expected_version=version,
            source=source_of(request),
            facts=RequestFacts.of(request),
        )
        return await _answer(session, subject, wtype, record_id, response)


__all__ = ["add_approver_change_routes"]
