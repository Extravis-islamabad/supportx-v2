"""Problem routes beyond the engine's own (WP-044a s3; REQ-PRB-011, -012, -014, -015).

    GET  /problems/prefill?incident_id=          a new problem's values from an incident
    GET  /problems/similar?q=                    open problems like a draft title
    POST /problems/from-incidents/preview        which selected incidents already have a problem
    POST /problems/from-incidents                create one problem and link the incidents
    POST /problems/{id}/incidents                link one incident to this problem (If-less)
    GET  /problems/{id}/copy                     a copy's values and what is left empty
    POST /problems/{id}/copy                     create the copy
    GET  /problems/{id}/investigators            who investigates it (ADR-040)
    PUT  /problems/{id}/investigators/{user_id}  name one (whoever may edit it); audited
    DELETE /problems/{id}/investigators/{user_id}  remove one, or step down yourself; audited
    GET  /problems/{id}/impact                   counts over the caused incidents you see (044b)
    GET  /problems/{id}/evidence                 the caused incidents' timeline you see (044b)

Many incidents go to "this problem instead" through the incidents' own bulk job
(`POST /incidents/bulk`, action `link_problem`), the same path as from the create form.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import audited
from app.modules.identity_access import PolicyService, Subject, get_policy, user_contacts
from app.modules.work_items.api.list_routes import BulkJobOut
from app.modules.work_items.api.people import PersonOut, people_out
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.lists import MAX_BULK
from app.modules.work_items.domain.types import PROBLEM, WorkItemType
from app.modules.work_items.service import bulk as bulk_service
from app.modules.work_items.service import problem_impact
from app.modules.work_items.service import problems as service
from app.modules.work_items.service import work_items as items
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

    _add_investigator_routes(router, wtype)
    _add_analysis_routes(router, wtype)


class SiteCountOut(BaseModel):
    """Caused incidents at one site (null: no site)."""

    site_id: uuid.UUID | None
    count: int


class PriorityCountOut(BaseModel):
    """Caused incidents of one priority."""

    priority: str = Field(description="A `priority` code.")
    count: int


class ProblemImpactOut(BaseModel):
    """The problem's impact from the incidents it causes (REQ-PRB-033)."""

    incidents: int
    open_incidents: int
    by_priority: list[PriorityCountOut]
    by_site: list[SiteCountOut]
    people: int = Field(description="Distinct people the incidents were raised by or for.")
    minutes: int = Field(description="Time logged on those incidents.")
    partial: bool = Field(
        description="Some caused incidents are not visible to you and are not counted."
    )


class EvidenceIncidentOut(BaseModel):
    """A caused incident on the timeline."""

    id: uuid.UUID
    display_id: str
    subject: str
    priority: str = Field(description="A `priority` code.")
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
                PriorityCountOut(priority=k, count=v) for k, v in sorted(found.by_priority.items())
            ],
            by_site=[
                SiteCountOut(site_id=k, count=v)
                for k, v in sorted(found.by_site.items(), key=lambda kv: -kv[1])
            ],
            people=found.people,
            minutes=found.minutes,
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
