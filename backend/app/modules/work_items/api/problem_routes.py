"""Problem routes beyond the engine's own (WP-044a s3; REQ-PRB-011, -012, -014, -015).

    GET  /problems/prefill?incident_id=          a new problem's values from an incident
    GET  /problems/similar?q=                    open problems like a draft title
    POST /problems/from-incidents/preview        which selected incidents already have a problem
    POST /problems/from-incidents                create one problem and link the incidents
    POST /problems/{id}/incidents                link one incident to this problem (If-less)
    DELETE /problems/{id}/incidents/{incident}   unlink it (needs incident edit; 044b)
    GET  /problems/{id}/copy                     a copy's values and what is left empty
    POST /problems/{id}/copy                     create the copy
    GET  /problems/{id}/investigators            who investigates it (ADR-040)
    PUT  /problems/{id}/investigators/{user_id}  name one (whoever may edit it); audited
    DELETE /problems/{id}/investigators/{user_id}  remove one, or step down yourself; audited
    GET  /problems/{id}/impact                   counts over the caused incidents you see (044b)
    GET  /problems/{id}/evidence                 the caused incidents' timeline you see (044b)
    POST /problems/{id}/merge                    merge into another problem (If-Match; 044b)
    POST /problems/{id}/undo-merge               put a merged problem back (If-Match; 044b)
    GET  /problems/known-errors?q=               the known error database you see (044b)
    GET  /problems/known-errors/suggestions?incident_id=  known errors like an incident (044b)
    POST /problems/{id}/known-error              mark it a known error (If-Match; 044b)
    POST /problems/{id}/known-error/remove       remove the flag, with a reason (If-Match; 044b)
    POST /problems/{id}/approvals                ask named people to approve (If-Match; 044b)
    GET  /problems/{id}/message-recipients?set=  followers, incident technicians or requesters
    POST /problems/{id}/messages/incident-requesters  a reply on each linked incident (044b)
    GET  /problems/{id}/follow-up                its open linked incidents you see (044b)
    POST /problems/{id}/follow-up                resolve the chosen ones, as a bulk job (044b)

Many incidents go to "this problem instead" through the incidents' own bulk job
(`POST /incidents/bulk`, action `link_problem`), the same path as from the create form.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import audited
from app.modules.identity_access import PolicyService, Subject, get_policy, user_contacts
from app.modules.work_items.api.list_routes import BulkJobOut
from app.modules.work_items.api.people import PersonOut, people_out
from app.modules.work_items.domain.approvals import ApprovalPurpose
from app.modules.work_items.domain.classification import Priority
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.lists import MAX_BULK
from app.modules.work_items.domain.types import PROBLEM, WorkItemType
from app.modules.work_items.service import bulk as bulk_service
from app.modules.work_items.service import (
    known_errors,
    problem_approvals,
    problem_followup,
    problem_impact,
    problem_merge,
    problem_messages,
)
from app.modules.work_items.service import problems as service
from app.modules.work_items.service import work_items as items
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.history import source_of

MAX_INCIDENTS = MAX_BULK


class EvidenceSource(StrEnum):
    """An evidence source the panel names when it is not available yet."""

    CHANGES = "changes"
    RELEASES = "releases"
    SAME_ITEMS = "same_items"


class ProblemPrefillOut(BaseModel):
    """A new problem's starting values; nothing is saved until the form is sent (AC1)."""

    subject: str
    description: str | None
    impact: str | None
    urgency: str | None
    site_id: uuid.UUID | None
    category_id: uuid.UUID | None = Field(
        description="The problem category with the incident category's seeded code, if any."
    )
    requester_id: uuid.UUID = Field(description="Reported by: you (REQ-PRB-010 AC1).")
    problem_type: str
    source_incident_id: uuid.UUID


class SimilarProblemOut(BaseModel):
    """An open problem whose text is close to the draft (REQ-PRB-014)."""

    id: uuid.UUID
    display_id: str
    subject: str
    status: str
    status_category: StatusCategory


class IncidentsIn(BaseModel):
    """The selected incidents (REQ-PRB-012)."""

    model_config = ConfigDict(extra="forbid")

    incident_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_INCIDENTS)


class AlreadyCausedOut(BaseModel):
    """An incident already caused by another problem, to move or leave (AC2)."""

    incident_id: uuid.UUID
    problem_display_id: str


class PreviewOut(BaseModel):
    """What creating the problem would meet."""

    already_caused: list[AlreadyCausedOut]


class LinkOneIn(BaseModel):
    """One incident to link to this problem."""

    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID
    move: bool = Field(
        default=False, description="Move it from the problem it is linked to now (AC2)."
    )


class InvestigatorsOut(BaseModel):
    """A problem's investigators, oldest first (REQ-PRB-029)."""

    user_ids: list[uuid.UUID]
    people: dict[str, PersonOut] = Field(default_factory=dict, description="Their names.")


class LinkedOut(BaseModel):
    """The link's outcome."""

    linked: bool = Field(description="False: the incident was already caused by this problem.")


class UnlinkedOut(BaseModel):
    """The unlink's outcome."""

    unlinked: bool = Field(description="False: the incident was not caused by this problem.")


def add_problem_routes(
    router: APIRouter,
    wtype: WorkItemType,
    *,
    record_in: type[BaseModel],
    record_out: type[BaseModel],
) -> None:
    """The problem routes on the problems router (before the `/{record_id}` routes).

    `record_in` and `record_out` are the engine's WorkItemIn and WorkItemOut, passed in so this
    module does not import routes.py (which imports it).
    """
    perm = wtype.permission
    View = Annotated[Subject, Depends(require_permission(perm("view")))]  # noqa: N806 - type alias
    Create = Annotated[Subject, Depends(require_permission(perm("create")))]  # noqa: N806 - type alias
    Edit = Annotated[Subject, Depends(require_permission(perm("edit")))]  # noqa: N806 - type alias
    Policy = Annotated[PolicyService, Depends(get_policy)]  # noqa: N806 - type alias
    location = f"/api/v1/{wtype.path}"

    class FromIncidentsIn(BaseModel):
        """One problem from many incidents; the main one pre-filled the form."""

        model_config = ConfigDict(extra="forbid")

        problem: record_in  # type: ignore[valid-type]  # WorkItemIn, passed in (see above)
        main_incident_id: uuid.UUID
        incident_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_INCIDENTS)
        move_incident_ids: list[uuid.UUID] = Field(
            default_factory=list,
            description="Of those already caused by another problem, the ones to move (AC2).",
        )

    class FromIncidentsOut(BaseModel):
        """The new problem and the jobs linking the other incidents (progress on your channel)."""

        problem: record_out  # type: ignore[valid-type]  # WorkItemOut, passed in (see above)
        bulk_jobs: list[BulkJobOut]

    class CopyPreviewOut(BaseModel):
        """A copy's values (REQ-PRB-015), and the fields left empty as now retired (AC3)."""

        values: dict[str, object]
        left_empty: list[str]

    @router.get("/prefill", summary="A new problem's values from an incident")
    async def prefill(
        incident_id: uuid.UUID, session: TenantSession, subject: Create
    ) -> ProblemPrefillOut:
        """Subject, description, category, impact, urgency and site of an incident you see."""
        return ProblemPrefillOut(**await service.prefill(session, subject, incident_id))

    @router.get("/similar", summary="Open problems like a draft")
    async def similar(
        session: TenantSession,
        subject: View,
        q: Annotated[str, Query(max_length=500)] = "",
    ) -> list[SimilarProblemOut]:
        """Up to five open problems you may see, best first (REQ-PRB-014)."""
        found = await service.similar(session, subject, q)
        return [SimilarProblemOut.model_validate(r, from_attributes=True) for r in found]

    @router.post("/from-incidents/preview", summary="Check incidents before creating a problem")
    async def preview(body: IncidentsIn, session: TenantSession, subject: Create) -> PreviewOut:
        """The selected incidents already caused by a problem, listed first (REQ-PRB-012 AC2)."""
        found = await service.already_caused(session, subject, body.incident_ids)
        return PreviewOut(
            already_caused=[
                AlreadyCausedOut(incident_id=i, problem_display_id=found[i])
                for i in body.incident_ids
                if i in found
            ]
        )

    @router.post(
        "/from-incidents",
        summary="Create a problem from incidents",
        status_code=status.HTTP_201_CREATED,
        response_model=FromIncidentsOut,
    )
    async def from_incidents(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: FromIncidentsIn,
        session: TenantSession,
        subject: Create,
        idempotency: Idempotency,
        request: Request,
        policy: Policy,
    ) -> Response:
        """The problem, the main incident linked now, the others by background job.

        Incidents already caused by another problem are left there unless listed in
        `move_incident_ids`. Send an Idempotency-Key.
        """

        async def run() -> Created:
            source = source_of(request)
            others = [i for i in dict.fromkeys(body.incident_ids) if i != body.main_incident_id]
            view = await items.create(
                session,
                subject,
                PROBLEM,
                body.problem.model_dump(exclude_unset=True),  # type: ignore[attr-defined]  # a WorkItemIn
                source=source,
                holders=policy,
            )
            problem = view.record
            await service.link_cause(
                session,
                subject,
                body.main_incident_id,
                problem.id,
                move=body.main_incident_id in body.move_incident_ids,
                source=source,
            )
            jobs = await bulk_service.start_problem_links(
                session,
                subject,
                problem.id,
                others,
                moving=set(body.move_incident_ids),
                source=source,
            )
            refreshed = await items.get(session, subject, PROBLEM, problem.id)
            out = FromIncidentsOut(
                problem=record_out.of(refreshed),  # type: ignore[attr-defined]  # WorkItemOut.of
                bulk_jobs=[BulkJobOut.of(j) for j in jobs],
            )
            return Created(
                body=out,
                headers={"Location": f"{location}/{problem.id}", "ETag": f'"{problem.version}"'},
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.post("/{record_id}/incidents", summary="Link an incident to this problem")
    async def link_incident(
        record_id: uuid.UUID,
        body: LinkOneIn,
        session: TenantSession,
        subject: Edit,
        request: Request,
    ) -> LinkedOut:
        """Caused by on both records, with history; 409 `incident_has_problem` unless `move`."""
        link = await service.link_cause(
            session,
            subject,
            body.incident_id,
            record_id,
            move=body.move,
            source=source_of(request),
        )
        return LinkedOut(linked=link is not None)

    @router.get("/{record_id}/copy", summary="A copy's values")
    async def copy_preview(
        record_id: uuid.UUID, session: TenantSession, subject: Create
    ) -> CopyPreviewOut:
        """The fields a copy gets, and those left empty because their value is retired (AC3)."""
        _, values, left_empty = await service.copy_values(session, subject, record_id)
        return CopyPreviewOut(
            values={k: str(v) if isinstance(v, uuid.UUID) else v for k, v in values.items()},
            left_empty=left_empty,
        )

    @router.post(
        "/{record_id}/copy",
        summary="Copy a problem",
        status_code=status.HTTP_201_CREATED,
        response_model=record_out,
    )
    async def copy(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        session: TenantSession,
        subject: Create,
        idempotency: Idempotency,
        request: Request,
        policy: Policy,
    ) -> Response:
        """A new problem with the original's fields; its history names the original (AC2)."""

        async def run() -> Created:
            source = source_of(request)
            original, values, _ = await service.copy_values(session, subject, record_id)
            view = await items.create(
                session, subject, PROBLEM, values, source=source, holders=policy
            )
            await service.copied_from(session, view.record, original, source)
            out = record_out.of(view)  # type: ignore[attr-defined]  # WorkItemOut.of
            return Created(
                body=out,
                headers={"Location": f"{location}/{out.id}", "ETag": f'"{out.version}"'},
            )

        return await idempotency.run({"copy_of": str(record_id)}, run, status_code=201)

    _add_work_routes(router, wtype, record_out)


def _add_work_routes(router: APIRouter, wtype: WorkItemType, record_out: type[BaseModel]) -> None:
    """The routes of WP-044a s5 and WP-044b, each group in its own function."""
    _add_investigator_routes(router, wtype)
    _add_analysis_routes(router, wtype)
    _add_merge_routes(router, wtype)
    _add_unlink_route(router, wtype)
    _add_known_error_routes(router, wtype, record_out)
    _add_approval_request_route(router, wtype, record_out)
    _add_message_routes(router, wtype)
    _add_follow_up_routes(router, wtype)


class ProblemFollowUpIncidentOut(BaseModel):
    """An open linked incident the follow-up can resolve."""

    id: uuid.UUID
    display_id: str
    subject: str
    status: str


class ProblemFollowUpOut(BaseModel):
    """What the follow-up offers: the incidents, and which texts the problem has."""

    incidents: list[ProblemFollowUpIncidentOut]
    has_resolution: bool
    has_workaround: bool


class ProblemFollowUpIn(BaseModel):
    """The chosen incidents (any unticked are left as they are) and what each gets."""

    incident_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_INCIDENTS)
    copy_text: problem_followup.CopyPart = Field(
        default=problem_followup.CopyPart.RESOLUTION,
        description="What each incident gets as its resolution.",
    )


def _add_follow_up_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """Follow-up on linked incidents (WP-044b s5; REQ-PRB-055, D-140 Q1)."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias
    Edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]  # noqa: N806 - type alias

    @router.get("/{record_id}/follow-up", summary="Open linked incidents to follow up")
    async def follow_up_preview(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> ProblemFollowUpOut:
        """The list shown before confirming (REQ-PRB-055 AC1): open, linked and visible."""
        problem, found = await problem_followup.open_incidents(session, subject, record_id)
        return ProblemFollowUpOut(
            incidents=[
                ProblemFollowUpIncidentOut(
                    id=i.id, display_id=i.display_id, subject=i.subject, status=i.status
                )
                for i in found
            ],
            has_resolution=bool((problem.resolution or "").strip()),
            has_workaround=bool((problem.workaround or "").strip()),
        )

    @router.post(
        "/{record_id}/follow-up",
        summary="Resolve the chosen linked incidents",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def follow_up(
        record_id: uuid.UUID,
        body: ProblemFollowUpIn,
        session: TenantSession,
        subject: Edit,
        request: Request,
    ) -> BulkJobOut:
        """A background job: each through its own rules, with a result per incident (AC2, AC3)."""
        job = await problem_followup.start(
            session,
            subject,
            record_id,
            body.incident_ids,
            copy=body.copy_text,
            source=source_of(request),
        )
        return BulkJobOut.of(job)


class RecipientOut(BaseModel):
    """One person of a recipient set."""

    user_id: uuid.UUID
    name: str
    email: str


class RequesterMessageIn(BaseModel):
    """The message for every affected requester (rich text, sanitised)."""

    body: str = Field(min_length=1, max_length=20000)


class RequesterMessageOut(BaseModel):
    """Where it went, and how many linked incidents were left out."""

    sent_to: list[str] = Field(description="Display ids of the incidents it was sent on.")
    skipped: int = Field(description="Linked incidents you may not reply on.")


def _add_message_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """Messages from a problem (WP-044b s4, REQ-PRB-052)."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias
    Edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]  # noqa: N806 - type alias
    Policy = Annotated[PolicyService, Depends(get_policy)]  # noqa: N806 - type alias

    @router.get("/{record_id}/message-recipients", summary="People a message may go to")
    async def message_recipients(
        record_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        set: problem_messages.RecipientSet,  # noqa: A002 - the API's query name
    ) -> list[RecipientOut]:
        """The set's people with an address (only from incidents you may see), by name."""
        found = await problem_messages.recipients(session, subject, record_id, set)
        return [RecipientOut(user_id=r.user_id, name=r.name, email=r.email) for r in found]

    @router.post(
        "/{record_id}/messages/incident-requesters",
        summary="Message the requesters of the linked incidents",
    )
    async def message_requesters(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: RequesterMessageIn,
        session: TenantSession,
        subject: Edit,
        request: Request,
        policy: Policy,
    ) -> RequesterMessageOut:
        """A public reply on each linked incident you may reply on, named in its history."""
        sent = await problem_messages.to_incident_requesters(
            session,
            subject,
            record_id,
            body=body.body,
            source=source_of(request),
            policy=policy,
        )
        return RequesterMessageOut(
            sent_to=[i.display_id for i in sent.incidents], skipped=len(sent.skipped)
        )


class ApprovalRequestIn(BaseModel):
    """Whom to ask, and what for."""

    approver_ids: list[uuid.UUID] = Field(min_length=1, max_length=problem_approvals.MAX_APPROVERS)
    purpose: ApprovalPurpose = ApprovalPurpose.RECORD


def _add_approval_request_route(
    router: APIRouter, wtype: WorkItemType, record_out: type[BaseModel]
) -> None:
    """Ask for approval on a problem (WP-044b s4); deciding uses the engine's routes."""
    Edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]  # noqa: N806 - type alias
    Policy = Annotated[PolicyService, Depends(get_policy)]  # noqa: N806 - type alias

    @router.post(
        "/{record_id}/approvals",
        summary="Ask named people to approve",
        response_model=record_out,
        dependencies=[
            audited("problem.approval_requested", object_type="problem", object_param="record_id")
        ],
    )
    async def request_approval(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: ApprovalRequestIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Edit,
        request: Request,
        response: Response,
        policy: Policy,
    ) -> BaseModel:
        """The approval status becomes pending; the first decision decides (If-Match)."""
        await problem_approvals.request(
            session,
            subject,
            record_id,
            body.approver_ids,
            purpose=body.purpose,
            expected_version=version,
            source=source_of(request),
            policy=policy,
        )
        view = await items.get(session, subject, PROBLEM, record_id)
        set_etag(response, view.record.version)
        out: BaseModel = record_out.of(view)  # type: ignore[attr-defined]  # WorkItemOut.of
        return out


class KnownErrorOut(BaseModel):
    """One known error (REQ-PRB-037): never its root cause (D-140 Q7)."""

    id: uuid.UUID
    display_id: str
    subject: str
    status: str
    symptoms: str | None
    workaround: str | None
    known_error_at: datetime
    retired_at: datetime | None = Field(description="Set when a permanent fix retired it.")
    incidents: int = Field(description="Incidents it causes (live links).")


def _known(entry: known_errors.KnownError) -> KnownErrorOut:
    r = entry.record
    assert r.known_error_at is not None  # noqa: S101 - the query keeps flagged ones only
    return KnownErrorOut(
        id=r.id,
        display_id=r.display_id,
        subject=r.subject,
        status=r.status,
        symptoms=r.symptoms,
        workaround=r.workaround,
        known_error_at=r.known_error_at,
        retired_at=r.known_error_retired_at,
        incidents=entry.incidents,
    )


class KnownErrorMarkIn(BaseModel):
    """Why it is a known error (optional)."""

    comment: str | None = Field(default=None, max_length=1000)


class KnownErrorRemoveIn(BaseModel):
    """Why the flag goes (required)."""

    reason: str = Field(min_length=1, max_length=1000)


def _add_known_error_routes(
    router: APIRouter, wtype: WorkItemType, record_out: type[BaseModel]
) -> None:
    """The known error flag, its database and suggestions (WP-044b s3)."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias
    Mark = Annotated[Subject, Depends(require_permission(wtype.permission("mark_known_error")))]  # noqa: N806 - type alias

    @router.get("/known-errors", summary="The known error database")
    async def database(
        session: TenantSession,
        subject: View,
        *,
        q: Annotated[str, Query(max_length=500)] = "",
        include_retired: Annotated[bool, Query()] = True,
    ) -> list[KnownErrorOut]:
        """Known errors you may see, searched in subject, symptoms and workaround."""
        found = await known_errors.database(
            session, subject, search=q, include_retired=include_retired
        )
        return [_known(e) for e in found]

    @router.get("/known-errors/suggestions", summary="Known errors like an incident")
    async def suggestions(
        incident_id: uuid.UUID, session: TenantSession, subject: View
    ) -> list[KnownErrorOut]:
        """Open known errors matching the incident's words (an incident you may see)."""
        return [_known(e) for e in await known_errors.suggestions(session, subject, incident_id)]

    async def answer(
        session: AsyncSession, subject: Subject, record_id: uuid.UUID, response: Response
    ) -> BaseModel:
        view = await items.get(session, subject, PROBLEM, record_id)
        set_etag(response, view.record.version)
        out: BaseModel = record_out.of(view)  # type: ignore[attr-defined]  # WorkItemOut.of
        return out

    @router.post(
        "/{record_id}/known-error", summary="Mark as a known error", response_model=record_out
    )
    async def mark(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: KnownErrorMarkIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Mark,
        request: Request,
        response: Response,
    ) -> BaseModel:
        """Needs a workaround or a root cause written first; If-Match."""
        await known_errors.mark(
            session,
            subject,
            record_id,
            expected_version=version,
            comment=body.comment,
            source=source_of(request),
        )
        return await answer(session, subject, record_id, response)

    @router.post(
        "/{record_id}/known-error/remove",
        summary="Remove the known error flag",
        response_model=record_out,
    )
    async def unmark(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: KnownErrorRemoveIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Mark,
        request: Request,
        response: Response,
    ) -> BaseModel:
        """With a reason, kept in history; If-Match."""
        await known_errors.unmark(
            session,
            subject,
            record_id,
            expected_version=version,
            reason=body.reason,
            source=source_of(request),
        )
        return await answer(session, subject, record_id, response)


def _add_unlink_route(router: APIRouter, wtype: WorkItemType) -> None:
    """Unlink one incident (WP-044b; REQ-PRB-043): the incident's edit right counts."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias

    @router.delete(
        "/{record_id}/incidents/{incident_id}", summary="Unlink an incident from this problem"
    )
    async def unlink_incident(
        record_id: uuid.UUID,
        incident_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> UnlinkedOut:
        """No longer caused by this problem, with history on both (needs incident edit)."""
        await service.problem_of(session, subject, record_id)
        done = await service.unlink_cause(
            session, subject, incident_id, record_id, source=source_of(request)
        )
        return UnlinkedOut(unlinked=done)


class MergeIn(BaseModel):
    """The problem to merge this one into."""

    into_id: uuid.UUID


class MergeOut(BaseModel):
    """The merged (or restored) problem's new state, and the incidents that moved or stayed."""

    id: uuid.UUID
    status: str = Field(description="`merged` after a merge; the earlier status after an undo.")
    version: int = Field(description="The new version (also the ETag).")
    moved_incident_ids: list[uuid.UUID]
    stayed_incident_ids: list[uuid.UUID] = Field(
        description="Undo: incidents linked elsewhere since the merge, left where they are."
    )


def _add_merge_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """Merge duplicates and undo it (REQ-PRB-046): both problems need edit."""
    Edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]  # noqa: N806 - type alias

    def answer(done: problem_merge.MergeOutcome, response: Response) -> MergeOut:
        set_etag(response, done.record.version)
        return MergeOut(
            id=done.record.id,
            status=done.record.status,
            version=done.record.version,
            moved_incident_ids=done.moved,
            stayed_incident_ids=done.stayed,
        )

    @router.post("/{record_id}/merge", summary="Merge into another problem")
    async def merge(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: MergeIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Edit,
        request: Request,
        response: Response,
    ) -> MergeOut:
        """Mark it `merged` and move its incidents to `into_id`. Needs If-Match."""
        done = await problem_merge.merge(
            session,
            subject,
            record_id,
            body.into_id,
            expected_version=version,
            source=source_of(request),
        )
        return answer(done, response)

    @router.post("/{record_id}/undo-merge", summary="Undo a merge")
    async def undo_merge(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Edit,
        request: Request,
        response: Response,
    ) -> MergeOut:
        """Back to the status it had; the moved incidents return unless linked elsewhere since."""
        done = await problem_merge.undo_merge(
            session, subject, record_id, expected_version=version, source=source_of(request)
        )
        return answer(done, response)


class SiteCountOut(BaseModel):
    """Caused incidents at one site (null: no site)."""

    site_id: uuid.UUID | None
    count: int


class PriorityCountOut(BaseModel):
    """Caused incidents of one priority."""

    priority: Priority
    count: int


class WeekCountOut(BaseModel):
    """Caused incidents reported in one week."""

    week_start: datetime
    count: int


class ProblemImpactOut(BaseModel):
    """The problem's impact from the incidents it causes (REQ-PRB-033)."""

    incidents: int
    open_incidents: int
    by_priority: list[PriorityCountOut]
    by_site: list[SiteCountOut]
    people: int = Field(description="Distinct people the incidents were raised by or for.")
    minutes: int = Field(description="Time logged on those incidents.")
    open_seconds: int = Field(
        description="Total time they were open: until resolved, or until now for open ones."
    )
    weekly: list[WeekCountOut] = Field(
        description="Incidents reported per week (UTC weeks from Monday), the last 8 weeks."
    )
    partial: bool = Field(
        description="Some caused incidents are not visible to you and are not counted."
    )


class EvidenceIncidentOut(BaseModel):
    """A caused incident on the timeline."""

    id: uuid.UUID
    display_id: str
    subject: str
    priority: Priority
    status: str = Field(description="A status code of the incident type.")
    status_category: str
    site_id: uuid.UUID | None
    reported_at: datetime
    resolved_at: datetime | None


class ProblemEvidenceOut(BaseModel):
    """The evidence panel (REQ-PRB-032): what is known now, and what is not there yet."""

    incidents: list[EvidenceIncidentOut] = Field(description="Oldest report first (≤ 200).")
    left_out: bool = Field(
        description="Some caused incidents are not shown: not visible to you, or past 200."
    )
    pending_sources: list[EvidenceSource] = Field(
        description="Evidence sources not available yet (changes, releases, the same items)."
    )


def _add_analysis_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The analysis section's read-outs (WP-044b)."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias

    @router.get("/{record_id}/impact", summary="The problem's impact")
    async def impact(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> ProblemImpactOut:
        """Counts over the incidents it causes that you may see; `partial` when some are not."""
        found = await problem_impact.impact(session, subject, record_id)
        return ProblemImpactOut(
            incidents=found.incidents,
            open_incidents=found.open_incidents,
            by_priority=[
                PriorityCountOut(priority=Priority(k), count=v)
                for k, v in sorted(found.by_priority.items())
            ],
            by_site=[
                SiteCountOut(site_id=k, count=v)
                for k, v in sorted(found.by_site.items(), key=lambda kv: -kv[1])
            ],
            people=found.people,
            minutes=found.minutes,
            open_seconds=found.open_seconds,
            weekly=[WeekCountOut(week_start=w, count=c) for w, c in found.weekly],
            partial=found.partial,
        )

    @router.get("/{record_id}/evidence", summary="The problem's evidence")
    async def evidence(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> ProblemEvidenceOut:
        """The caused incidents you may see, by when they were reported, and what is pending."""
        found = await problem_impact.evidence(session, subject, record_id)
        return ProblemEvidenceOut(
            incidents=[
                EvidenceIncidentOut.model_validate(i, from_attributes=True) for i in found.incidents
            ],
            left_out=found.left_out,
            pending_sources=[EvidenceSource(s) for s in found.pending_sources],
        )


def _add_investigator_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """Investigators (ADR-040): list, name, remove; naming and removing are audited."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias
    Policy = Annotated[PolicyService, Depends(get_policy)]  # noqa: N806 - type alias
    audit = wtype.code.value

    @router.get("/{record_id}/investigators", summary="Investigators of the problem")
    async def list_investigators(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> InvestigatorsOut:
        """Technicians who work it besides the owner (REQ-PRB-029)."""
        ids = await service.investigators(session, subject, record_id)
        names = await user_contacts(session, [str(i) for i in ids])
        return InvestigatorsOut(user_ids=ids, people=people_out(names))

    @router.put(
        "/{record_id}/investigators/{user_id}",
        summary="Name an investigator",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[
            audited(f"{audit}.investigator_added", object_type=audit, object_param="record_id")
        ],
    )
    async def add_investigator(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        user_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        request: Request,
        policy: Policy,
    ) -> Response:
        """They reach this problem's record, notes, tasks and worklogs (ADR-040); idempotent."""
        await service.add_investigator(
            session, subject, record_id, user_id, policy=policy, source=source_of(request)
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete(
        "/{record_id}/investigators/{user_id}",
        summary="Remove an investigator",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[
            audited(f"{audit}.investigator_removed", object_type=audit, object_param="record_id")
        ],
    )
    async def remove_investigator(
        record_id: uuid.UUID,
        user_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """Their access to it ends; history names both changes (REQ-PRB-029 AC3)."""
        await service.remove_investigator(
            session, subject, record_id, user_id, source=source_of(request)
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["add_problem_routes"]
