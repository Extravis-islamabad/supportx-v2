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
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import AuditNote, RequestFacts, audited
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject, user_contacts
from app.modules.work_items.api.people import PersonOut, people_out
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.change_boards import BoardChoice
from app.modules.work_items.domain.clarifications import Addressee, ClarificationState, state_of
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import approvals as service
from app.modules.work_items.service import bulk_approvals, clarifications
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import CLIENT_HEADER, source_of

# Our staff apps: the console and the mobile app (REQ-CHG-110, REQ-SR-024 AC2). Anything else
# that decides, the portal included, is recorded as the portal.
APP_CLIENTS = frozenset({"console", "mobile"})


def _channel(request: Request) -> rules.DecisionChannel:
    client = request.headers.get(CLIENT_HEADER, "").strip().lower()
    return rules.DecisionChannel.APP if client in APP_CLIENTS else rules.DecisionChannel.PORTAL


class BulkApproveItem(BaseModel):
    """One approval to approve, at the version you saw (If-Match for each)."""

    model_config = ConfigDict(extra="forbid")

    record_id: uuid.UUID
    approval_id: uuid.UUID
    version: int


class BulkApproveIn(BaseModel):
    """Approve these, with one comment (WP-032 D6, REQ-PRT-008)."""

    model_config = ConfigDict(extra="forbid")

    items: list[BulkApproveItem] = Field(min_length=1, max_length=bulk_approvals.BULK_APPROVE_MAX)
    comment: str | None = Field(default=None, max_length=4000)


class BulkApproveResult(BaseModel):
    """What happened to one: decided, or skipped with the reason's code."""

    approval_id: uuid.UUID
    record_id: uuid.UUID
    decided: bool
    code: str | None = None


class BulkApproveOut(BaseModel):
    """Each approval's outcome, in the order sent."""

    items: list[BulkApproveResult]


ModifyRefused = service.ModifyRefused


class ClarificationOut(BaseModel):
    """An approver's question on this approval (WP-047a S3a; REQ-SR-037)."""

    id: uuid.UUID
    state: ClarificationState = Field(description="open, answered, decided or closed.")
    addressee: Addressee = Field(description="requester or technician.")
    asked_by: uuid.UUID
    asked_at: datetime
    ended_at: datetime | None
    question: str | None = Field(
        description="The question (sanitised HTML): for the person who asked and staff only."
    )
    answer: str | None = Field(
        description="The answer (sanitised HTML): for the person who asked and staff only."
    )

    @classmethod
    def of(cls, shown: clarifications.Shown) -> "ClarificationOut":
        """From the service's view."""
        row = shown.row
        return cls(
            id=row.id,
            state=state_of(row.ended_how),
            addressee=Addressee(row.addressee),
            asked_by=row.asked_by,
            asked_at=row.asked_at,
            ended_at=row.ended_at,
            question=shown.question,
            answer=shown.answer,
        )


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
    board_id: uuid.UUID | None = Field(
        description="Changes: the advisory board this approval came from (WP-045b)."
    )
    board_reason: BoardChoice | None = Field(
        description="Why that board: its mapping matched, or it is the default board."
    )
    advisory: bool = Field(
        description="An optional board member's vote: shown, never counted (WP-045b)."
    )
    state: rules.ApprovalState
    branch: str | None = Field(
        default=None, description="Requests: the parallel group this stage runs in (REQ-SR-030)."
    )
    skip_reason: rules.SkipReason | None = Field(
        default=None, description="Requests: why the stage was skipped (REQ-SR-032)."
    )
    condition: dict[str, Any] | None = Field(
        default=None, description="A skipped stage's condition, in the form rules' terms."
    )
    auto_reason: rules.AutoReason | None = Field(
        default=None,
        description="Requests: why it was approved automatically (REQ-SR-033); `channel` is "
        "then `automatic`.",
    )
    auto_ref: int | None = Field(
        default=None,
        description="The earlier stage the person approved, or the matched rule's number.",
    )
    auto_rule: dict[str, str] | None = Field(
        default=None, description="The matched rule's name, per language."
    )
    auto_keys: list[str] | None = Field(
        default=None, description="Staff only: the answer keys the matched rule read."
    )
    decided_at: datetime | None
    decided_by: uuid.UUID | None
    channel: rules.DecisionChannel | None
    comment: str | None = Field(description="Hidden when private and you are not staff.")
    comment_private: bool
    comments_required: bool
    self_approved: bool = Field(description="Decided by the requester or the person it is for.")
    can_decide: bool
    on_behalf_of_id: uuid.UUID | None = Field(
        default=None,
        description="Requests: the approver a delegation routed it away from (REQ-SR-035); "
        "they may still decide it. Decided by `decided_by` on their behalf.",
    )
    round: int = Field(default=1, description="Requests: the approval round (REQ-SR-041).")
    escalated_from_id: uuid.UUID | None = Field(
        default=None,
        description="Requests: the approval this one was escalated from (REQ-SR-034); the "
        "first of the two to decide settles it.",
    )
    clarification: ClarificationOut | None = Field(
        default=None, description="Requests: the latest question asked on it (REQ-SR-037)."
    )
    created_at: datetime
    version: int

    @classmethod
    def of(
        cls, view: service.ApprovalView, clarification: clarifications.Shown | None = None
    ) -> "ApprovalOut":
        """From the service's view, with its latest clarification if any."""
        row = view.row
        return cls(
            id=row.id,
            stage=row.stage,
            record_stage=row.record_stage,
            rule=rules.LevelRule(row.rule) if row.rule else None,
            approver_id=row.approver_id,
            origin=rules.ApproverOrigin(row.origin),
            route_reason=rules.RouteReason(row.route_reason) if row.route_reason else None,
            board_id=row.board_id,
            board_reason=BoardChoice(row.board_reason) if row.board_reason else None,
            advisory=row.advisory,
            state=rules.ApprovalState(row.state),
            branch=row.branch,
            skip_reason=rules.SkipReason(row.skip_reason) if row.skip_reason else None,
            condition=dict(view.condition) if view.condition is not None else None,
            auto_reason=rules.AutoReason(row.auto_reason) if row.auto_reason else None,
            auto_ref=row.auto_ref,
            auto_rule=dict(view.auto_rule) if view.auto_rule is not None else None,
            auto_keys=list(view.auto_keys) if view.auto_keys is not None else None,
            decided_at=row.decided_at,
            decided_by=row.decided_by,
            channel=rules.DecisionChannel(row.channel) if row.channel else None,
            comment=view.comment,
            comment_private=row.comment_private,
            comments_required=row.comments_required,
            self_approved=view.self_approved,
            can_decide=view.can_decide,
            on_behalf_of_id=row.on_behalf_of_id,
            round=row.round,
            escalated_from_id=row.escalated_from_id,
            clarification=ClarificationOut.of(clarification) if clarification else None,
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
    origin: rules.ApproverOrigin = Field(
        default=rules.ApproverOrigin.NAMED,
        description="`backup`: it came to you in place of the approver (marked, REQ-PRT-008).",
    )
    state: rules.ApprovalState = rules.ApprovalState.PENDING
    decided_at: datetime | None = None


class ApprovalsOut(BaseModel):
    """A record's approvals with the names of the people in them."""

    items: list[ApprovalOut]
    people: dict[str, PersonOut]
    modify_refused: ModifyRefused | None = Field(
        default=None,
        description="Requests: why you may not adjust the running approval (REQ-SR-042 AC2): "
        "no_permission, out_of_scope or approval_not_running; null: you may. Other types: "
        "always null.",
    )


async def approvals_out(
    session: TenantSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> ApprovalsOut:
    """The record's approvals as the viewer may see them, with the people's names."""
    found = await service.list_for_record(session, subject, wtype, record_id)
    asked = (
        await clarifications.shown(
            session, subject, wtype, await service.record_of(session, wtype, record_id)
        )
        if found
        else {}
    )
    names = {
        p for v in found for p in (v.row.approver_id, v.row.decided_by, v.row.on_behalf_of_id) if p
    }
    names |= {c.row.asked_by for c in asked.values()}
    return ApprovalsOut(
        items=[ApprovalOut.of(v, asked.get(v.row.id)) for v in found],
        people=people_out(await user_contacts(session, sorted(str(n) for n in names))),
        modify_refused=await service.modify_refused(session, subject, wtype, record_id),
    )


class MyApprovalsOut(BaseModel):
    """Your waiting approvals with the names of the people they are for."""

    items: list[PendingApprovalOut]
    people: dict[str, PersonOut]


# The audit entry's outcome of a decision (QA9-F-03; lane B's audit.decision.* labels).
OUTCOMES = {rules.Decision.APPROVE: "approved", rules.Decision.REJECT: "rejected"}


class DecisionIn(BaseModel):
    """Approve or reject; a rejection needs a reason (REQ-SR-028)."""

    decision: rules.Decision
    comment: str | None = Field(default=None, max_length=rules.COMMENT_MAX)
    private: bool = Field(default=False, description="Hidden from the requester (REQ-SR-028 AC3).")


def add_approval_routes(router: APIRouter, wtype: WorkItemType, *, withdraw: bool = True) -> None:
    """The approval routes of `wtype` on its router (before the `/{record_id}` routes).

    `withdraw`: the requester's withdrawal (service requests; releases and problems have none).
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
                    origin=rules.ApproverOrigin(p.approval.origin),
                )
                for p in found
            ],
            people=people_out(await user_contacts(session, sorted(str(n) for n in names))),
        )

    @router.get("/my-approvals/decided", summary="Approvals you decided lately")
    async def my_decided(session: TenantSession, subject: SignedIn) -> MyApprovalsOut:
        """The last 30 days, newest first (the portal inbox's second list, REQ-PRT-008)."""
        found = await service.decided_by_me(session, subject, wtype)
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
                    origin=rules.ApproverOrigin(p.approval.origin),
                    state=rules.ApprovalState(p.approval.state),
                    decided_at=p.approval.decided_at,
                )
                for p in found
            ],
            people=people_out(await user_contacts(session, sorted(str(n) for n in names))),
        )

    @router.post("/approvals/decisions", summary="Approve several at once")
    async def approve_many(
        body: BulkApproveIn, session: TenantSession, subject: SignedIn, request: Request
    ) -> BulkApproveOut:
        """One comment for all, at most 20; each is one decision (audited, live). No rejects."""
        channel = _channel(request)
        outcomes = await bulk_approvals.approve_many(
            session,
            subject,
            wtype,
            [bulk_approvals.ApprovalRef(i.record_id, i.approval_id, i.version) for i in body.items],
            comment=body.comment,
            channel=channel,
            source=source_of(request),
        )
        facts = RequestFacts.of(request)
        for outcome in outcomes:
            if outcome.decided:  # one audit entry per decision, as for a single one
                await record_audit(
                    session,
                    action_code=f"{audit}.approval_decided",
                    facts=facts,
                    object_type=audit,
                    object_id=outcome.ref.record_id,
                    details={
                        "approval_id": str(outcome.ref.approval_id),
                        "bulk": True,
                        "outcome": OUTCOMES[rules.Decision.APPROVE],  # bulk only approves
                    },
                )
        return BulkApproveOut(
            items=[
                BulkApproveResult(
                    approval_id=o.ref.approval_id,
                    record_id=o.ref.record_id,
                    decided=o.decided,
                    code=o.code,
                )
                for o in outcomes
            ]
        )

    @router.get("/{record_id}/approvals", summary="Approvals of the record")
    async def approvals(
        record_id: uuid.UUID, session: TenantSession, subject: SignedIn
    ) -> ApprovalsOut:
        """Every approver's entry; for those who see the record and for its approvers."""
        return await approvals_out(session, subject, wtype, record_id)

    Decided = Annotated[  # noqa: N806 - type alias
        AuditNote,
        audited(f"{audit}.approval_decided", object_type=audit, object_param="record_id"),
    ]

    @router.post("/{record_id}/approvals/{approval_id}/decision", summary="Approve or reject")
    async def decide(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        approval_id: uuid.UUID,
        body: DecisionIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: SignedIn,
        request: Request,
        response: Response,
        note: Decided,
    ) -> ApprovalOut:
        """If-Match carries the approval's version; the first decision decides the stage."""
        channel = _channel(request)
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
        # Only once decided, the audit says which (QA9-F-03), labelled by lane B (#281).
        note.details = {"outcome": OUTCOMES[body.decision]}
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
