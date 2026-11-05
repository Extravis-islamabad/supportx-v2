"""Approval routes of a work item type (WP-030 s2; REQ-SR-024, -025, -028, -061).

    GET  /{type}/my-approvals                                the signed-in approver's inbox
    GET  /{type}/{id}/approvals                              a record's approvals
    POST /{type}/{id}/approvals/{approval_id}/decision      approve or reject (If-Match)
    POST /{type}/{id}/withdraw                               the requester withdraws (If-Match)

Any signed-in person reaches these: the service decides (the approver of that approval, the
approval administrators, the record's own requester), so a requester-only manager can approve
(REQ-SR-022 AC2). A person who is none of those gets 404 or 403 from the service.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import audited
from app.modules.identity_access import Subject, user_contacts
from app.modules.work_items.api.people import PersonOut, people_out
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import approvals as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of

CONSOLE = "console"


class ApprovalOut(BaseModel):
    """One approver's entry (REQ-SR-024): who, the decision, when, where and the comment."""

    id: uuid.UUID
    stage: int = Field(description="The level (from 1).")
    record_stage: str | None = Field(
        default=None, description="Staged records: the stage it belongs to (WP-058a)."
    )
    rule: rules.LevelRule | None = Field(
        default=None, description="Staged records: how the level is decided."
    )
    approver_id: uuid.UUID | None = Field(
        description="None: the tenant's approval administrators hold it (REQ-SR-023)."
    )
    origin: rules.ApproverOrigin
    route_reason: rules.RouteReason | None = Field(
        description="Why it went to the backup or the administrators."
    )
    state: rules.ApprovalState
    decided_at: datetime | None
    decided_by: uuid.UUID | None
    channel: rules.DecisionChannel | None
    comment: str | None = Field(description="Hidden when private and you are not staff.")
    comment_private: bool
    comments_required: bool
    self_approved: bool = Field(description="Decided by the requester or the person it is for.")
    can_decide: bool
    created_at: datetime
    version: int

    @classmethod
    def of(cls, view: service.ApprovalView) -> "ApprovalOut":
        """From the service's view."""
        row = view.row
        return cls(
            id=row.id,
            stage=row.stage,
            record_stage=row.record_stage,
            rule=rules.LevelRule(row.rule) if row.rule else None,
            approver_id=row.approver_id,
            origin=rules.ApproverOrigin(row.origin),
            route_reason=rules.RouteReason(row.route_reason) if row.route_reason else None,
            state=rules.ApprovalState(row.state),
            decided_at=row.decided_at,
            decided_by=row.decided_by,
            channel=rules.DecisionChannel(row.channel) if row.channel else None,
            comment=view.comment,
            comment_private=row.comment_private,
            comments_required=row.comments_required,
            self_approved=view.self_approved,
            can_decide=view.can_decide,
            created_at=row.created_at,
            version=row.version,
        )


class PendingApprovalOut(BaseModel):
    """An approval waiting for you, with the request's summary (REQ-SR-025)."""

    approval_id: uuid.UUID
    approval_version: int
    record_id: uuid.UUID
    display_id: str
    subject: str
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None
    catalog_item_id: uuid.UUID | None
    comments_required: bool
    created_at: datetime


class ApprovalsOut(BaseModel):
    """A record's approvals with the names of the people in them."""

    items: list[ApprovalOut]
    people: dict[str, PersonOut]


class MyApprovalsOut(BaseModel):
    """Your waiting approvals with the names of the people they are for."""

    items: list[PendingApprovalOut]
    people: dict[str, PersonOut]


class DecisionIn(BaseModel):
    """Approve or reject; a rejection needs a reason (REQ-SR-028)."""

    decision: rules.Decision
    comment: str | None = Field(default=None, max_length=rules.COMMENT_MAX)
    private: bool = Field(default=False, description="Hidden from the requester (REQ-SR-028 AC3).")


def add_approval_routes(router: APIRouter, wtype: WorkItemType, *, withdraw: bool = True) -> None:
    """The approval routes of `wtype` on its router (before the `/{record_id}` routes).

    `withdraw`: the requester's withdrawal (service requests; releases have none).
    """
    SignedIn = Annotated[Subject, Depends(require_signed_in())]  # noqa: N806 - type alias
    audit = wtype.code.value

    @router.get("/my-approvals", summary="Approvals waiting for you")
    async def my_approvals(session: TenantSession, subject: SignedIn) -> MyApprovalsOut:
        """Oldest first; the console drawer and the portal inbox show these."""
        found = await service.mine(session, subject, wtype)
        names = {p for f in found for p in (f.record.requester_id, f.record.on_behalf_of_id) if p}
        return MyApprovalsOut(
            items=[
                PendingApprovalOut(
                    approval_id=p.approval.id,
                    approval_version=p.approval.version,
                    record_id=p.record.id,
                    display_id=p.record.display_id,
                    subject=p.record.subject,
                    requester_id=p.record.requester_id,
                    on_behalf_of_id=p.record.on_behalf_of_id,
                    catalog_item_id=p.record.catalog_item_id,
                    comments_required=p.approval.comments_required,
                    created_at=p.approval.created_at,
                )
                for p in found
            ],
            people=people_out(await user_contacts(session, sorted(str(n) for n in names))),
        )

    @router.get("/{record_id}/approvals", summary="Approvals of the record")
    async def approvals(
        record_id: uuid.UUID, session: TenantSession, subject: SignedIn
    ) -> ApprovalsOut:
        """Every approver's entry; for those who see the record and for its approvers."""
        found = await service.list_for_record(session, subject, wtype, record_id)
        names = {p for v in found for p in (v.row.approver_id, v.row.decided_by) if p}
        return ApprovalsOut(
            items=[ApprovalOut.of(v) for v in found],
            people=people_out(await user_contacts(session, sorted(str(n) for n in names))),
        )

    @router.post(
        "/{record_id}/approvals/{approval_id}/decision",
        summary="Approve or reject",
        dependencies=[
            audited(f"{audit}.approval_decided", object_type=audit, object_param="record_id")
        ],
    )
    async def decide(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        approval_id: uuid.UUID,
        body: DecisionIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: SignedIn,
        request: Request,
        response: Response,
    ) -> ApprovalOut:
        """If-Match carries the approval's version; the first decision decides the stage."""
        client = request.headers.get("X-SupportX-Client")
        channel = rules.DecisionChannel.APP if client == CONSOLE else rules.DecisionChannel.PORTAL
        view = await service.decide(
            session,
            subject,
            wtype,
            record_id,
            approval_id,
            decision=body.decision,
            comment=body.comment,
            private=body.private,
            expected_version=version,
            channel=channel,
            source=source_of(request),
        )
        set_etag(response, view.row.version)
        return ApprovalOut.of(view)

    if withdraw:

        @router.post(
            "/{record_id}/withdraw",
            summary="Withdraw a request awaiting approval",
            dependencies=[
                audited(f"{audit}.withdrawn", object_type=audit, object_param="record_id")
            ],
        )
        async def withdraw_request(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            version: ExpectedVersion,
            session: TenantSession,
            subject: SignedIn,
            request: Request,
            response: Response,
        ) -> dict[Literal["id", "status", "version"], str | int]:
            """The requester (or the person it is for) withdraws it; pending approvals close."""
            record = await service.withdraw(
                session,
                subject,
                wtype,
                record_id,
                expected_version=version,
                source=source_of(request),
            )
            set_etag(response, record.version)
            return {"id": str(record.id), "status": record.status, "version": record.version}


__all__ = ["add_approval_routes"]
