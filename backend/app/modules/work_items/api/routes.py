"""Work item HTTP API: one router per type, `/api/v1/<type path>` (WP-020; ADR-026). No logic here.

`build_router(INCIDENT)` gives `/api/v1/incidents/...`; later types get their own paths, schemas
and permissions from the same factory (D3). Writes use If-Match (409 says who changed what);
create takes an Idempotency-Key. Status changes only through `/actions/{action}`; group and
technician only through `/assign` and `/take`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import BadRequest, ProblemDetail
from app.modules.ai import GATEWAY_STATE, Gateway
from app.modules.audit import AuditNote, RequestFacts, audited, entries_for_changes
from app.modules.audit import record as record_audit
from app.modules.identity_access import PolicyService, Subject, get_policy, user_contacts
from app.modules.work_items.api.approval_routes import add_approval_routes
from app.modules.work_items.api.asset_routes import add_asset_routes
from app.modules.work_items.api.conversation_routes import (
    add_collection_routes,
    add_record_routes,
)
from app.modules.work_items.api.list_routes import add_list_routes, list_dependency
from app.modules.work_items.api.parts_routes import add_parts_collection_routes, add_parts_routes
from app.modules.work_items.api.people import PersonOut, people_out
from app.modules.work_items.api.problem_routes import add_problem_routes
from app.modules.work_items.api.settings_routes import add_settings_routes
from app.modules.work_items.domain import change_risk as risk_rules
from app.modules.work_items.domain import reapproval as reapproval_rules
from app.modules.work_items.domain.approvals import RouteReason
from app.modules.work_items.domain.change_risk import RiskLevel
from app.modules.work_items.domain.changes import DETAIL_FIELDS as CHANGE_DETAIL_FIELDS
from app.modules.work_items.domain.classification import (
    PRIORITY_REASON_MAX,
    Impact,
    Priority,
    PrioritySource,
    Scale,
    Urgency,
)
from app.modules.work_items.domain.conversation import FirstResponseAction
from app.modules.work_items.domain.lifecycle import (
    REASON_TEXT_MAX,
    USER_ACTIONS,
    ReasonList,
    ReasonMode,
    StatusCategory,
    WorkItemAction,
)
from app.modules.work_items.domain.reapproval import OnChange, Watched
from app.modules.work_items.domain.releases import (
    BUILD_REF_MAX,
    DETAIL_FIELDS,
    VERSION_MAX,
    DowntimePhase,
    ReleaseRisk,
    StageOutcome,
)
from app.modules.work_items.domain.service_requests import ApprovalStatus, OnBehalfScope
from app.modules.work_items.domain.stages import RailState
from app.modules.work_items.domain.templates import IMPACT_DETAILS_MAX, REASON_LISTS, PickList
from app.modules.work_items.domain.types import (
    DESCRIPTION_MAX,
    INCIDENT,
    STANDARD_LIFECYCLE,
    SUBJECT_MAX,
    TAGS_MAX,
    Channel,
    WorkItemType,
    WorkItemTypeCode,
)
from app.modules.work_items.infra.models import WorkItem, WorkItemCategory, WorkItemDowntime
from app.modules.work_items.service import (
    asset_links,
    change_links,
    release_links,
    resolution,
    stage_approvals,
)
from app.modules.work_items.service import change_boards as board_service
from app.modules.work_items.service import change_risk as risk_service
from app.modules.work_items.service import duplicates as duplicates_service
from app.modules.work_items.service import problems as problem_service
from app.modules.work_items.service import reapproval as reapproval_service
from app.modules.work_items.service import search as search_service
from app.modules.work_items.service import settings as settings_service
from app.modules.work_items.service import work_items as service
from app.modules.work_items.service.catalogue import Catalogue, ReasonInfo
from app.modules.work_items.service.closing import MoveInput, requester_channel_states
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, PageResult, request_zone
from app.shared.api.ratelimit import rate_limit
from app.shared.history import Actors, ChangeKind, HistoryEntry, Source, source_of
from app.shared.labels import strip_isolates

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such record visible to you."},
}
CONFLICT: Responses = {
    409: {
        "model": ProblemDetail,
        "description": "version_conflict (who changed what), invalid_transition, record_closed, "
        "would_lose_access, already_taken or already_yours.",
    }
}


# --- schemas --------------------------------------------------------------------------------------


# REQ-AST-025: the record types that link assets (the incident and request forms, e-mail).
_WITH_ASSETS = frozenset({WorkItemTypeCode.INCIDENT, WorkItemTypeCode.SERVICE_REQUEST})


class WorkItemIn(BaseModel):
    """A new record. Group and technician need the assign permission."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(max_length=SUBJECT_MAX * 2)
    description: str | None = Field(
        default=None, max_length=DESCRIPTION_MAX * 2, description="Rich text (HTML), sanitised."
    )
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None = None
    channel: Channel | None = Field(
        default=None, description="Only phone or walk_up may be chosen; others are set for you."
    )
    site_id: uuid.UUID | None = Field(default=None, description="Default: the requester's site.")
    department_id: uuid.UUID | None = Field(
        default=None, description="Default: the requester's department (WP-021)."
    )
    group_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None
    asset_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=20,
        description="Assets to link (REQ-AST-025; incidents and requests, the assets feature).",
    )
    category_id: uuid.UUID | None = None
    impact: Impact | None = None
    impact_details: str | None = Field(
        default=None, max_length=IMPACT_DETAILS_MAX * 2, description="Plain text."
    )
    urgency: Urgency | None = None
    level: str | None = Field(default=None, max_length=40, description="A `level` list code.")
    # Problems only (WP-044a s2, REQ-PRB-005, -006); refused on other types.
    problem_type: str | None = Field(
        default=None, max_length=40, description="Problems: a `problem_type` list code."
    )
    root_cause_category: str | None = Field(
        default=None, max_length=40, description="Problems: a `root_cause` list code."
    )
    outage_started_at: datetime | None = Field(
        default=None, description="Problems: when the outage began."
    )
    outage_ended_at: datetime | None = Field(
        default=None, description="Problems: when it ended (not before it began)."
    )
    root_cause: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX * 2,
        description="Problems: the root cause, rich text (needs problems.edit_analysis and "
        "problems.view_root_cause).",
    )
    symptoms: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX * 2,
        description="Problems: the symptoms, rich text (needs problems.edit_analysis).",
    )
    workaround: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX * 2,
        description="Problems: the workaround, rich text (needs problems.edit_solution).",
    )
    review_summary: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX * 2,
        description="Problems: the review's summary (needs problems.edit_analysis).",
    )
    review_lessons: str | None = Field(
        default=None, max_length=DESCRIPTION_MAX * 2, description="Problems: lessons learned."
    )
    review_actions: str | None = Field(
        default=None, max_length=DESCRIPTION_MAX * 2, description="Problems: follow-up actions."
    )
    change_type: str | None = Field(
        default=None, max_length=40, description="Changes only: a change type code (REQ-CHG-005)."
    )
    retrospective: bool | None = Field(
        default=None,
        description=(
            "Changes only: work already done (REQ-CHG-004); needs actual_start and actual_end, "
            "both past; it enters at the review."
        ),
    )
    actual_start: datetime | None = Field(default=None, description="Changes only, retrospective.")
    actual_end: datetime | None = Field(default=None, description="Changes only, retrospective.")
    from_record_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Changes only: the incident, request, problem or release it is made from; linked "
            "as change_for on both (REQ-CHG-002)."
        ),
    )
    change_reason: str | None = Field(
        default=None, max_length=40, description="Changes only: a reason for change code."
    )
    template_id: uuid.UUID | None = Field(
        default=None, description="Default: the tenant's default template (its rules apply)."
    )
    catalog_item_id: uuid.UUID | None = Field(
        default=None, description="Service requests only, and required there (REQ-SR-001)."
    )
    answers: dict[str, Any] | None = Field(
        default=None, description="Service requests: the item form's answers by question key."
    )
    custom: dict[str, Any] | None = Field(
        default=None, description="Custom field values by key (GET /custom-fields?entity=...)."
    )
    priority: Priority | None = Field(
        default=None, description="Set by hand (needs change_priority and a reason)."
    )
    priority_reason: str | None = Field(default=None, max_length=PRIORITY_REASON_MAX)
    tags: list[str] = Field(default_factory=list, max_length=TAGS_MAX * 2)
    confirm_lose_access: bool = Field(
        default=False, description="Confirm handing it to people you cannot see records of."
    )
    keep_following: bool | None = Field(
        default=None,
        description="With confirm_lose_access: keep following it (null: tenant default, D-068).",
    )


class WorkItemPatch(BaseModel):
    """Fields to change (only those sent). Not status, group or technician."""

    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, max_length=SUBJECT_MAX * 2)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)
    requester_id: uuid.UUID | None = None
    on_behalf_of_id: uuid.UUID | None = None
    channel: Channel | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    impact: Impact | None = None
    impact_details: str | None = Field(default=None, max_length=IMPACT_DETAILS_MAX * 2)
    urgency: Urgency | None = None
    level: str | None = Field(default=None, max_length=40)
    # Problems only (WP-044a s2, REQ-PRB-005, -006); refused on other types.
    problem_type: str | None = Field(
        default=None, max_length=40, description="Problems: a `problem_type` list code."
    )
    root_cause_category: str | None = Field(
        default=None, max_length=40, description="Problems: a `root_cause` list code."
    )
    outage_started_at: datetime | None = Field(
        default=None, description="Problems: when the outage began."
    )
    outage_ended_at: datetime | None = Field(
        default=None, description="Problems: when it ended (not before it began)."
    )
    root_cause: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX * 2,
        description="Problems: the root cause, rich text (needs problems.edit_analysis and "
        "problems.view_root_cause).",
    )
    symptoms: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX * 2,
        description="Problems: the symptoms, rich text (needs problems.edit_analysis).",
    )
    workaround: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX * 2,
        description="Problems: the workaround, rich text (needs problems.edit_solution).",
    )
    review_summary: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX * 2,
        description="Problems: the review's summary (needs problems.edit_analysis).",
    )
    review_lessons: str | None = Field(
        default=None, max_length=DESCRIPTION_MAX * 2, description="Problems: lessons learned."
    )
    review_actions: str | None = Field(
        default=None, max_length=DESCRIPTION_MAX * 2, description="Problems: follow-up actions."
    )
    custom: dict[str, Any] | None = Field(
        default=None, description="Custom values to change by key (null clears one); others kept."
    )
    priority: Priority | None = Field(
        default=None,
        description="A value sets it by hand (with a reason); null: back to the matrix.",
    )
    priority_reason: str | None = Field(default=None, max_length=PRIORITY_REASON_MAX)
    tags: list[str] | None = Field(default=None, max_length=TAGS_MAX * 2)
    confirm_lose_access: bool = False
    keep_following: bool | None = Field(
        default=None,
        description="With confirm_lose_access: keep following it (null: tenant default, D-068).",
    )


RESOLUTION_MAX = DESCRIPTION_MAX * 2  # rich text, like the description


class ResolutionRejectIn(BaseModel):
    """Why it is not fixed: the requester's own words, shown as a public reply."""

    model_config = ConfigDict(extra="forbid")

    comment: str = Field(max_length=RESOLUTION_MAX)


class ResolutionAnswerOut(BaseModel):
    """What the requester's answer did (requesters see no more of the record here)."""

    display_id: str
    status: str
    closed: bool = Field(description="False on confirm: a technician closes it (closure rules).")

    @classmethod
    def of(cls, answered: "resolution.Answered") -> "ResolutionAnswerOut":
        """From the service's answer."""
        return cls(
            display_id=answered.record.display_id,
            status=answered.record.status,
            closed=answered.closed,
        )


class WorkItemTransitionIn(BaseModel):
    """The reason, when the transition asks for one."""

    model_config = ConfigDict(extra="forbid")

    reason_code: str | None = Field(default=None, max_length=40)
    reason_text: str | None = Field(default=None, max_length=REASON_TEXT_MAX)
    group_id: uuid.UUID | None = Field(
        default=None,
        description="Start work on an unassigned record: which of your groups (as with Take).",
    )
    resolution: str | None = Field(
        default=None,
        max_length=RESOLUTION_MAX,
        description="Resolve: the fix, rich text (sanitised). REQ-INC-090.",
    )
    closure_code: str | None = Field(
        default=None, max_length=40, description="Close: a closure code. REQ-INC-093."
    )
    confirm_open_work: bool = Field(
        default=False,
        description="Resolve or close although work is still open (the warning was shown).",
    )


class WorkItemAssignIn(BaseModel):
    """New group and technician (either may be null). Moving between groups needs a reason."""

    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None
    reason_code: str | None = Field(default=None, max_length=40)
    reason_text: str | None = Field(default=None, max_length=PRIORITY_REASON_MAX)
    confirm_lose_access: bool = Field(
        default=False, description="You confirmed it leaves your reach (D-053)."
    )
    keep_following: bool | None = Field(
        default=None,
        description="With confirm_lose_access: keep following it (null: tenant default, D-068).",
    )


class WorkItemDueDateIn(BaseModel):
    """A due date set by hand (null clears it and the SLA calculates it again), and why."""

    model_config = ConfigDict(extra="forbid")

    due_at: datetime | None = Field(description="The new due moment (UTC); null clears it.")
    reason: str = Field(min_length=1, max_length=500)


SlaKind = Literal["first_response", "resolution"]
SlaState = Literal["running", "paused", "met", "breached", "stopped"]
# A target as lists show it: `warning` is a running target past its warning point.
SlaShownState = Literal["running", "warning", "paused", "met", "breached", "stopped"]
SlaMetHow = Literal["on_time", "late", "at_resolution"]
SlaReason = Literal["created", "priority_changed", "condition_changed"]


class SlaManualOut(BaseModel):
    """A due date set by hand: who, why and when (REQ-SLA-028 AC3)."""

    due_at: datetime
    by_id: uuid.UUID | None
    by_name: str | None
    reason: str | None
    at: datetime | None


SlaLevelAnchor = Literal["due", "warning"]
SlaRunState = Literal["waiting", "ran", "cancelled"]


class SlaLevelRunOut(BaseModel):
    """One escalation level of a target: when it runs; whether it waits, ran or was cancelled."""

    position: int
    anchor: SlaLevelAnchor
    offset_seconds: int = Field(description="Business seconds from the anchor; negative: before.")
    state: SlaRunState
    due_at: datetime | None = Field(description="None while waiting: held by a pause.")
    ran_at: datetime | None
    failed_actions: int = Field(description="Actions that could not be done (REQ-SLA-024 AC3).")


class SlaTargetOut(BaseModel):
    """One target of the record's SLA (the latest round).

    Times are UTC; seconds are business seconds on the target's calendar.
    """

    kind: SlaKind
    round: int
    state: SlaState
    target_seconds: int
    used_seconds: int
    paused_seconds: int
    running_since: datetime | None
    paused_since: datetime | None
    due_at: datetime | None
    warning_at: datetime | None
    met_at: datetime | None
    met_how: SlaMetHow | None
    breached_at: datetime | None
    breach_seconds: int | None
    calendar_id: uuid.UUID | None
    calendar_name: str | None
    manual: SlaManualOut | None
    warned_at: datetime | None = Field(
        default=None, description="When it reached its warning point (REQ-SLA-019)."
    )
    levels: list[SlaLevelRunOut] = Field(default_factory=list)


class WorkItemSlaOut(BaseModel):
    """The record's SLA panel (REQ-SLA-038). No policy: the record has no SLA."""

    policy_id: uuid.UUID | None
    policy_name: str | None
    reason: SlaReason | None
    applied_at: datetime | None
    targets: list[SlaTargetOut]
    may_set_due_dates: bool

    @classmethod
    def of(cls, panel: service.SlaPanel) -> "WorkItemSlaOut":
        """The panel as the API returns it."""
        view = panel.sla
        return cls(
            policy_id=view.policy_id,
            policy_name=view.policy_name,
            reason=cast("SlaReason | None", view.reason),
            applied_at=view.applied_at,
            may_set_due_dates=panel.may_set_due_dates,
            targets=[
                SlaTargetOut(
                    kind=cast("SlaKind", t.kind),
                    round=t.round,
                    state=cast("SlaState", t.state),
                    target_seconds=t.target_seconds,
                    used_seconds=t.used_seconds,
                    paused_seconds=t.paused_seconds,
                    running_since=t.running_since,
                    paused_since=t.paused_since,
                    due_at=t.due_at,
                    warning_at=t.warning_at,
                    met_at=t.met_at,
                    met_how=cast("SlaMetHow | None", t.met_how),
                    breached_at=t.breached_at,
                    breach_seconds=t.breach_seconds,
                    calendar_id=t.calendar_id,
                    calendar_name=t.calendar_name,
                    manual=SlaManualOut(
                        due_at=t.manual_due_at,
                        by_id=t.manual_by,
                        by_name=panel.names.get(str(t.manual_by)) if t.manual_by else None,
                        reason=t.manual_reason,
                        at=t.manual_at,
                    )
                    if t.manual_due_at is not None
                    else None,
                    warned_at=t.warned_at,
                    levels=[
                        SlaLevelRunOut(
                            position=lv.position,
                            anchor=cast("SlaLevelAnchor", lv.anchor),
                            offset_seconds=lv.offset_seconds,
                            state=cast("SlaRunState", lv.state),
                            due_at=lv.due_at,
                            ran_at=lv.ran_at,
                            failed_actions=lv.failed_actions,
                        )
                        for lv in t.levels
                    ],
                )
                for t in view.targets
            ],
        )


class WorkItemTakeIn(BaseModel):
    """Which of your groups, when it has none and you are in several."""

    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID | None = None


_people = people_out


class WorkItemActionStateOut(BaseModel):
    """An action as you may use it now. Disabled ones carry a reason code (labelled)."""

    action: str
    allowed: bool
    reason: str | None = None
    reason_mode: ReasonMode = ReasonMode.NONE
    reason_list: ReasonList | None = None
    confirmation: dict[str, str] | None = Field(
        default=None, description="Asked before the move runs, per language (en, ar, ur)."
    )
    allowed_for: "AllowedForOut | None" = Field(
        default=None, description="Refused as not_for_you: who may run it (QA WP-029 C2)."
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Resolve and close: record fields the closure rules still need (REQ-INC-094).",
    )


class RoleNameOut(BaseModel):
    """A role: system roles are labelled by key, other roles shown by name."""

    key: str
    name: str
    system: bool


class AllowedForOut(BaseModel):
    """Who a transition is limited to: roles, group names, people on the record (codes)."""

    roles: list[RoleNameOut]
    groups: list[str]
    relatives: list[str]


class AnalysisChangeOut(BaseModel):
    """The last change of one analysis field (REQ-PRB-030)."""

    field: str = Field(description="`root_cause` or `symptoms`.")
    changed_by: uuid.UUID | None = Field(description="Null when the system changed it.")
    changed_at: datetime


class WorkItemOut(BaseModel):
    """A work item as staff see it."""

    id: uuid.UUID
    type: str
    display_id: str
    subject: str
    description: str | None
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None
    channel: Channel
    site_id: uuid.UUID | None
    department_id: uuid.UUID | None
    desk_id: uuid.UUID
    group_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    category_id: uuid.UUID | None
    impact: Impact | None
    impact_details: str | None
    urgency: Urgency | None
    priority: Priority
    priority_source: PrioritySource
    level: str | None = Field(description="A `level` list code (may be a retired one).")
    # Problems (WP-044a s2); null on other types.
    problem_type: str | None = None
    root_cause_category: str | None = None
    outage_started_at: datetime | None = None
    outage_ended_at: datetime | None = None
    root_cause: str | None = Field(
        default=None, description="Problems: null when root_cause_hidden (D-140 Q7)."
    )
    root_cause_hidden: bool = Field(
        default=False, description="Problems: you may not read the root cause."
    )
    symptoms: str | None = None
    workaround: str | None = None
    review_summary: str | None = None
    review_lessons: str | None = None
    review_actions: str | None = None
    review_required: bool = Field(
        default=False, description="Problems: closing needs the review summary (REQ-PRB-053)."
    )
    known_error_at: datetime | None = Field(
        default=None, description="Problems: when it was marked a known error."
    )
    accepted_at: datetime | None = Field(
        default=None, description="Problems: a known error accepted without a fix (approved)."
    )
    accept_review_at: datetime | None = Field(
        default=None, description="Problems: when the accepted known error is looked at again."
    )
    known_error_retired_at: datetime | None = Field(
        default=None, description="Problems: when the known error was retired (a permanent fix)."
    )
    analysis_changes: list[AnalysisChangeOut] = Field(
        default_factory=list,
        description="Problems: who last changed each analysis field you may read, and when.",
    )
    template_id: uuid.UUID | None = Field(description="The template it was created from.")
    lifecycle: str = Field(
        default=STANDARD_LIFECYCLE,
        description="The transition set it follows, from its template (WP-044a; REQ-PRB-025).",
    )
    status_before_pause: str | None = Field(
        default=None, description="On hold: the status it resumes to (problems, Appendix A)."
    )
    catalog_item_id: uuid.UUID | None = Field(
        default=None, description="Service requests: the item it was raised from."
    )
    answers: dict[str, Any] = Field(
        default_factory=dict, description="Service requests: the item form's answers."
    )
    approval_status: ApprovalStatus | None = Field(
        default=None, description="Service requests: not needed, pending, approved ..."
    )
    custom: dict[str, Any] = Field(description="Custom field values by key (WP-026).")
    stage: str | None = Field(
        default=None, description="Staged types (releases): the stage it is in (ADR-041)."
    )
    stage_path: str | None = Field(
        default=None, description="Staged types: the path of stages it follows."
    )
    status: str
    status_category: StatusCategory
    status_reason_code: str | None
    status_reason_text: str | None
    status_changed_at: datetime
    tags: list[str]
    first_assigned_at: datetime | None
    first_responded_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    last_reopened_at: datetime | None
    reopen_count: int
    resolution: str | None = Field(description="The fix, sanitised rich text (REQ-INC-090).")
    closure_code: str | None = Field(description="A closure_code pick-list code (REQ-INC-093).")
    resolution_notified_at: datetime | None = Field(
        description="When the requester was told of the resolution; auto-close counts from it."
    )
    follows_id: uuid.UUID | None = Field(
        description="The earlier record a requester's late reply followed (REQ-INC-098)."
    )
    reassignment_count: int
    paused_seconds: int
    paused_since: datetime | None
    sla_policy_id: uuid.UUID | None = Field(description="Null: no SLA applies (REQ-INC-011).")
    first_response_due_at: datetime | None
    resolution_due_at: datetime | None
    first_response_sla_state: SlaShownState | None = Field(
        default=None, description="Where the response target stands (`warning`: past its point)."
    )
    resolution_sla_state: SlaShownState | None = None
    first_response_breached: bool = Field(default=False, description="Ever breached (stays).")
    resolution_breached: bool = False
    created_at: datetime
    created_by: uuid.UUID | None
    updated_at: datetime
    updated_by: uuid.UUID | None
    version: int = Field(description="Send it back as If-Match (the ETag) to change it.")
    actions: list[WorkItemActionStateOut] = Field(
        description="Status actions, always in the same order."
    )
    operations: list[WorkItemActionStateOut] = Field(
        description="edit, assign, take, change_priority, delete (problems: edit_analysis): "
        "whether you may, and why not."
    )
    history_count: int
    people: dict[str, PersonOut] = Field(description="The people on the record, by user ID.")
    visible: bool = Field(
        default=True, description="False right after you handed it away (D-053): no more access."
    )
    conversation_actions: list[WorkItemActionStateOut] = Field(
        description="add_note, reply, manage_followers: whether you may, and why not."
    )
    following: bool = Field(description="You follow this record.")
    conversation_count: int = Field(description="Replies and notes.")

    @classmethod
    def of(cls, view: service.WorkItemView) -> "WorkItemOut":
        """From the service view."""
        r = view.record
        return cls(
            **{name: getattr(r, name) for name in _RECORD_FIELDS},
            root_cause=None if "root_cause" in view.hidden else r.root_cause,
            root_cause_hidden="root_cause" in view.hidden,
            review_required=view.review_required,
            analysis_changes=[
                AnalysisChangeOut(
                    field=c.field,
                    changed_by=None if c.actor_id is None else uuid.UUID(c.actor_id),
                    changed_at=c.at,
                )
                for c in view.analysis_changes
            ],
            actions=[_state(a) for a in view.actions],
            operations=[_state(a) for a in view.operations],
            history_count=view.history_count,
            people=_people(view.names),
            visible=view.visible,
            conversation_actions=[_state(a) for a in view.conversation],
            following=view.following,
            conversation_count=view.conversation_count,
        )


_RECORD_FIELDS = (
    "catalog_item_id",
    "answers",
    "approval_status",
    "id",
    "type",
    "display_id",
    "subject",
    "description",
    "requester_id",
    "on_behalf_of_id",
    "channel",
    "site_id",
    "department_id",
    "desk_id",
    "group_id",
    "technician_id",
    "category_id",
    "impact",
    "impact_details",
    "urgency",
    "priority",
    "priority_source",
    "level",
    "problem_type",
    "root_cause_category",
    "outage_started_at",
    "outage_ended_at",
    "symptoms",
    "workaround",
    "review_summary",
    "review_lessons",
    "review_actions",
    "known_error_at",
    "known_error_retired_at",
    "accepted_at",
    "accept_review_at",
    "template_id",
    "lifecycle",
    "status_before_pause",
    "custom",
    "stage",
    "stage_path",
    "status",
    "status_category",
    "status_reason_code",
    "status_reason_text",
    "status_changed_at",
    "tags",
    "first_assigned_at",
    "first_responded_at",
    "resolved_at",
    "closed_at",
    "last_reopened_at",
    "reopen_count",
    "resolution",
    "closure_code",
    "resolution_notified_at",
    "follows_id",
    "reassignment_count",
    "paused_seconds",
    "paused_since",
    "sla_policy_id",
    "first_response_due_at",
    "resolution_due_at",
    "first_response_sla_state",
    "resolution_sla_state",
    "first_response_breached",
    "resolution_breached",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "version",
)


def _state(a: service.ActionState) -> WorkItemActionStateOut:
    return WorkItemActionStateOut(
        action=a.action,
        allowed=a.allowed,
        reason=a.reason,
        reason_mode=ReasonMode(a.reason_mode),
        reason_list=ReasonList(a.reason_list) if a.reason_list else None,
        confirmation=dict(a.confirmation) if a.confirmation else None,
        allowed_for=None
        if a.allowed_for is None
        else AllowedForOut(
            roles=[
                RoleNameOut(key=r.key, name=r.name, system=r.system) for r in a.allowed_for.roles
            ],
            groups=a.allowed_for.groups,
            relatives=a.allowed_for.relatives,
        ),
        missing=list(a.missing),
    )


class WorkItemListItem(BaseModel):
    """One row of a list."""

    id: uuid.UUID
    display_id: str
    subject: str
    catalog_item_id: uuid.UUID | None = Field(
        default=None, description="Service requests: the item it was raised from."
    )
    approval_status: ApprovalStatus | None = Field(
        default=None, description="Service requests: the approval (REQ-SR-009)."
    )
    requester_id: uuid.UUID
    technician_id: uuid.UUID | None
    group_id: uuid.UUID | None
    site_id: uuid.UUID | None
    category_id: uuid.UUID | None
    priority: Priority
    priority_source: PrioritySource
    level: str | None
    stage: str | None = Field(default=None, description="Staged types: the current stage.")
    stage_path: str | None = Field(
        default=None, description="Staged types: the path (releases: `emergency` is the flag)."
    )
    status: str
    status_category: StatusCategory
    status_reason_code: str | None
    channel: Channel
    tags: list[str]
    sla_policy_id: uuid.UUID | None
    first_response_due_at: datetime | None
    resolution_due_at: datetime | None
    first_response_sla_state: SlaShownState | None = None
    resolution_sla_state: SlaShownState | None = None
    first_response_breached: bool = False
    resolution_breached: bool = False
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int
    # More columns the list can show (WP-020d, REQ-INC-104), custom fields included.
    impact: Impact | None
    urgency: Urgency | None
    department_id: uuid.UUID | None
    closure_code: str | None
    reopen_count: int
    status_changed_at: datetime | None
    first_responded_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    custom: dict[str, Any] = Field(default_factory=dict, description="Custom values by key.")


class WorkItemPage(Page[WorkItemListItem]):
    """One page of a list, with the display names of the people on it."""

    people: dict[str, PersonOut] = Field(default_factory=dict)


class CausingProblemOut(BaseModel):
    """An incident's causing problem, narrowly (WP-044c D14; REQ-PRB-071, Q7)."""

    id: uuid.UUID
    display_id: str
    subject: str
    status: str = Field(description="The problem's status code (labelled by the UI).")
    known_error: bool
    workaround: str | None = Field(description="Rich text (sanitised), what to do meanwhile.")
    target_at: datetime | None = Field(description="When the problem should be solved by.")
    may_open: bool = Field(description="Whether you may open the problem itself.")

    @classmethod
    def of(cls, view: "problem_service.CausingView") -> "CausingProblemOut":
        """From the service's view."""
        return cls(
            id=view.id,
            display_id=view.display_id,
            subject=view.subject,
            status=view.status,
            known_error=view.known_error,
            workaround=view.workaround,
            target_at=view.target_at,
            may_open=view.may_open,
        )


class WorkItemSearchOut(BaseModel):
    """Search results, best first, with the people on them (name and email)."""

    items: list[WorkItemListItem]
    people: dict[str, PersonOut] = Field(default_factory=dict)


class DuplicatesQuery(BaseModel):
    """A draft incident, to look for possible duplicates of (REQ-INC-022)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=250)
    description: str | None = Field(default=None, max_length=4000)
    requester_id: uuid.UUID | None = None
    exclude: uuid.UUID | None = None


class DuplicateOut(BaseModel):
    """An open incident that may be the same issue (REQ-INC-022)."""

    item: WorkItemListItem
    # 0 to about 1.2: similarity, plus a weight for the same requester within the hour.
    score: float
    reasons: list[Literal["similar_meaning", "similar_subject", "same_requester"]]


class DuplicatesOut(BaseModel):
    """Possible duplicates of a draft, best first, and how they were found (D-134)."""

    items: list[DuplicateOut]
    # "meaning": AI embeddings (AI on); "text": subject similarity, no model (AI off).
    method: Literal["meaning", "text"]
    people: dict[str, PersonOut] = Field(default_factory=dict)


class WorkItemViewCountOut(BaseModel):
    """A built-in view and how many records you see in it (capped)."""

    view: str
    count: int
    capped: bool = Field(description="True: more than `count`.")


class WorkItemAssigneeOut(BaseModel):
    """Someone who can be assigned, with their open load."""

    id: uuid.UUID
    display_name: str
    email: str = Field(description="Second line in pickers: two people may share a name.")
    open_count: int
    group_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Their groups: someone outside the record's group is assigned by moving "
        "the record to one of these in the same request (D-154a).",
    )


class WorkItemStatusOut(BaseModel):
    """One status of the tenant's life cycle."""

    code: str
    category: StatusCategory
    colour: str
    labels: dict[str, str] | None = Field(description="Admin overrides; null: shipped labels.")
    system: bool
    disabled: bool
    resume_on_requester_reply: bool = Field(
        default=False,
        description="A requester reply moves a record in this paused status to in progress.",
    )


class WorkItemClosureOut(BaseModel):
    """Closing rules (WP-020f; REQ-INC-094..098)."""

    resolve_requires: list[str] = Field(description="Fields required before resolving.")
    close_requires: list[str] = Field(description="Fields required before closing.")
    open_work: dict[str, str] = Field(
        description="Open work kind -> warn or block (defaults for kinds not listed)."
    )
    complete_open_work: bool
    auto_close_days: int | None = Field(description="Business days; null: off.")
    reopen_window_days: int
    task_owner_access: bool = Field(
        description="A task's owner may work on it without access to the record (D-112)."
    )
    requester_channels: list[str] = Field(
        description="Channels that reach this tenant's requesters now; auto-close needs one."
    )
    requester_channel_states: list["RequesterChannelOut"] = Field(
        description="Every channel that can tell requesters, and why one does not reach now."
    )


class RequesterChannelOut(BaseModel):
    """A channel that can tell requesters, for this tenant now."""

    channel: str
    reason: str | None = Field(description="Null: it reaches; else why not (a labelled code).")


class WorkItemTransitionOut(BaseModel):
    """One allowed move."""

    from_status: str
    action: WorkItemAction
    to_status: str | None = Field(description="Null: back to the status before canceling.")
    reason_mode: ReasonMode
    reason_list: ReasonList | None
    lifecycle: str = Field(
        default=STANDARD_LIFECYCLE,
        description="The transition set: `standard`, or one a template chooses (WP-044a).",
    )


class WorkItemScaleValueOut(BaseModel):
    """One impact, urgency or priority value."""

    scale: Scale
    code: str
    rank: int
    colour: str | None
    labels: dict[str, str] | None


class WorkItemReasonOut(BaseModel):
    """One reason of a pick list (retired ones included, marked: they still label records)."""

    list: ReasonList
    code: str
    labels: dict[str, str] | None
    sort_order: int = 0
    colour: str | None = None
    disabled: bool = False


class WorkItemListValueOut(BaseModel):
    """One value of a level or closure-code list (retired ones included, marked)."""

    code: str
    labels: dict[str, str] | None = Field(description="Null: labelled by the UI from the code.")
    sort_order: int
    colour: str | None
    disabled: bool
    attributes: dict[str, Any] | None = Field(
        default=None,
        description="A value's own settings (a release type's default template, risk).",
    )


class WorkItemMatrixCellOut(BaseModel):
    """impact x urgency → priority."""

    impact: Impact
    urgency: Urgency
    priority: Priority


# Pick lists every type has: the reason lists, levels and closure codes.
SHARED_LISTS = frozenset({*REASON_LISTS, PickList.LEVEL, PickList.CLOSURE_CODE})


def _value(v: ReasonInfo) -> WorkItemListValueOut:
    return WorkItemListValueOut(
        code=v.code,
        labels=v.labels,
        sort_order=v.sort_order,
        colour=v.colour,
        disabled=v.disabled,
        attributes=dict(v.attributes) if v.attributes else None,
    )


class ReapprovalPolicyIO(BaseModel):
    """What an edit to an approved change does, per watched value (REQ-CHG-053)."""

    model_config = ConfigDict(extra="forbid")

    on_change: dict[Watched, OnChange] = Field(
        default_factory=dict, description="window, risk, plans: restart, notify or ignore."
    )
    tolerance_minutes: int = Field(
        default=60, ge=0, le=10_080, description="A window moved by more than this restarts."
    )


class WorkItemCatalogueOut(BaseModel):
    """The tenant's configuration of this type (for forms, filters and labels)."""

    prefix: str
    default_priority: Priority
    default_impact: Impact | None = Field(description="What the create form starts with.")
    default_urgency: Urgency | None = Field(description="What the create form starts with.")
    auto_status_on_assign: bool
    keep_following_on_handover: bool = Field(
        description="Hand-over dialog: 'keep following' starts ticked (D-068)."
    )
    on_behalf_scope: OnBehalfScope = Field(
        default=OnBehalfScope.SAME_DEPARTMENT,
        description="Whom a requester may raise a record for (REQ-SR-011).",
    )
    approvals_hidden_from_requesters: bool = Field(
        default=False,
        description="Requesters see only 'awaiting approval', no names or comments (REQ-SR-024).",
    )
    approvals_require_sign_in: bool = Field(
        default=False,
        description="E-mailed approval links need the approver signed in (D-132; off).",
    )
    portal_show_due_time: bool = Field(
        default=False, description="Requesters see the expected resolution time (REQ-INC-147)."
    )
    first_task_starts_work: bool = Field(
        default=True,
        description="Requests: ticking the first fulfilment task moves a New or Assigned request "
        "to In progress, when ticked by its technician or group (D-154c).",
    )
    first_response_on: list[FirstResponseAction] = Field(
        description="Which actions stamp the first response (REQ-INC-065)."
    )
    review_required_priorities: list[Priority] = Field(
        default_factory=list,
        description="Problems: priorities that need a review before closing (major ones always).",
    )
    segregation_strict: bool = Field(
        default=False,
        description="Changes: implementing groups' members may not approve either (REQ-CHG-039).",
    )
    cab_every_match: bool = Field(
        default=False,
        description="Changes: every board the mapping matches reviews, not only the first.",
    )
    reapproval: ReapprovalPolicyIO | None = Field(
        default=None,
        description="Changes: edits to an approved change (REQ-CHG-053); null: shipped.",
    )
    version: int
    statuses: list[WorkItemStatusOut]
    actions: list[WorkItemAction] = Field(description="User actions in their fixed order.")
    transitions: list[WorkItemTransitionOut]
    scales: list[WorkItemScaleValueOut]
    matrix: list[WorkItemMatrixCellOut]
    reasons: list[WorkItemReasonOut]
    levels: list[WorkItemListValueOut] = Field(description="Support levels (REQ-INC-007).")
    closure_codes: list[WorkItemListValueOut] = Field(description="REQ-INC-093.")
    problem_types: list[WorkItemListValueOut] = Field(
        default_factory=list, description="Problems: the problem type list (WP-044a)."
    )
    root_causes: list[WorkItemListValueOut] = Field(
        default_factory=list, description="Problems: the root cause category list (WP-044a)."
    )
    own_lists: dict[str, list[WorkItemListValueOut]] = Field(
        default_factory=dict,
        description="The type's own pick lists (releases: release_type, release_reason).",
    )
    closure: WorkItemClosureOut
    next_number: int = Field(description="The display number the next record gets.")

    @classmethod
    async def of(cls, session: AsyncSession, cat: Catalogue) -> "WorkItemCatalogueOut":
        """From the loaded catalogue and the tenant's requester channels (BUG-02)."""
        channels = await requester_channel_states(session)
        return cls(
            prefix=cat.prefix,
            default_priority=Priority(cat.default_priority),
            default_impact=None if cat.default_impact is None else Impact(cat.default_impact),
            default_urgency=None if cat.default_urgency is None else Urgency(cat.default_urgency),
            auto_status_on_assign=cat.auto_status_on_assign,
            keep_following_on_handover=cat.keep_following_on_handover,
            on_behalf_scope=OnBehalfScope(cat.on_behalf_scope),
            approvals_hidden_from_requesters=cat.approvals_hidden_from_requesters,
            approvals_require_sign_in=cat.approvals_require_sign_in,
            portal_show_due_time=cat.portal_show_due_time,
            first_task_starts_work=cat.first_task_starts_work,
            review_required_priorities=[Priority(p) for p in cat.review_required_priorities],
            segregation_strict=cat.segregation_strict,
            cab_every_match=cat.cab_every_match,
            reapproval=ReapprovalPolicyIO.model_validate(
                reapproval_rules.policy_json(reapproval_rules.policy_from(cat.reapproval))
            )
            if cat.reapproval is not None
            else None,
            first_response_on=[FirstResponseAction(c) for c in cat.first_response_on],
            version=cat.settings_version,
            statuses=[
                WorkItemStatusOut(
                    code=s.code,
                    category=StatusCategory(s.category),
                    colour=s.colour,
                    labels=s.labels,
                    system=s.system,
                    disabled=s.disabled,
                    resume_on_requester_reply=s.resume_on_requester_reply,
                )
                for s in cat.statuses
            ],
            # The actions of this type's life cycle (an incident never offers a problem's).
            actions=cat.used_actions(),
            transitions=[
                WorkItemTransitionOut(
                    from_status=t.from_status,
                    action=t.action,
                    to_status=t.to_status,
                    reason_mode=t.reason_mode,
                    reason_list=t.reason_list,
                    lifecycle=code,
                )
                # The standard set first; life-cycle order (QA BUG-04): by status, then the
                # fixed action order.
                for code, lifecycle in cat.lifecycles.items()
                for t in sorted(
                    lifecycle.transitions.values(),
                    key=lambda t: (
                        [st.code for st in cat.statuses].index(t.from_status),
                        USER_ACTIONS.index(t.action) if t.action in USER_ACTIONS else 99,
                    ),
                )
                if t.action in USER_ACTIONS
            ],
            scales=[
                WorkItemScaleValueOut(
                    scale=Scale(v.scale), code=v.code, rank=v.rank, colour=v.colour, labels=v.labels
                )
                for v in cat.scales
            ],
            matrix=[
                WorkItemMatrixCellOut(impact=Impact(i), urgency=Urgency(u), priority=Priority(p))
                for (i, u), p in sorted(cat.matrix.items())
            ],
            reasons=[
                WorkItemReasonOut(
                    list=ReasonList(r.list),
                    code=r.code,
                    labels=r.labels,
                    sort_order=r.sort_order,
                    colour=r.colour,
                    disabled=r.disabled,
                )
                for r in cat.reasons
                if r.list in REASON_LISTS
            ],
            levels=[_value(v) for v in cat.list_values(PickList.LEVEL)],
            closure_codes=[_value(v) for v in cat.list_values(PickList.CLOSURE_CODE)],
            problem_types=[_value(v) for v in cat.list_values(PickList.PROBLEM_TYPE)],
            root_causes=[_value(v) for v in cat.list_values(PickList.ROOT_CAUSE)],
            # The lists only this type has (any list beyond the shared ones it was seeded with).
            own_lists={
                name: [_value(v) for v in cat.list_values(PickList(name))]
                for name in sorted({r.list for r in cat.reasons} - SHARED_LISTS)
            },
            closure=WorkItemClosureOut(
                resolve_requires=list(cat.closure.resolve_requires),
                close_requires=list(cat.closure.close_requires),
                open_work=dict(cat.closure.open_work),
                complete_open_work=cat.closure.complete_open_work,
                auto_close_days=cat.closure.auto_close_days,
                reopen_window_days=cat.closure.reopen_window_days,
                task_owner_access=cat.closure.task_owner_access,
                requester_channels=sorted(n for n, reason in channels.items() if reason is None),
                requester_channel_states=[
                    RequesterChannelOut(channel=n, reason=reason) for n, reason in channels.items()
                ],
            ),
            next_number=cat.last_number + 1,
        )


class WorkItemClosurePatch(BaseModel):
    """Closing rules to change (only those sent). If-Match: the catalogue's `version`."""

    model_config = ConfigDict(extra="forbid")

    resolve_requires: list[str] | None = Field(default=None, max_length=30)
    close_requires: list[str] | None = Field(default=None, max_length=30)
    open_work: dict[str, str] | None = None
    complete_open_work: bool | None = None
    auto_close_days: int | None = Field(
        default=None, description="1 to 30 business days; null switches auto-close off."
    )
    reopen_window_days: int | None = None
    task_owner_access: bool | None = None


# Settings that may be cleared with null (the others ignore a null).
NULLABLE_SETTINGS = frozenset({"default_impact", "default_urgency"})


class WorkItemSettingsPatch(BaseModel):
    """Type settings to change (only those sent). If-Match: the catalogue's `version`."""

    model_config = ConfigDict(extra="forbid")

    prefix: str | None = Field(default=None, max_length=6, description="2-6 capital letters.")
    next_number: int | None = Field(
        default=None, ge=1, le=10**15, description="The number the next record gets (never lower)."
    )
    default_priority: Priority | None = None
    default_impact: Impact | None = Field(default=None, description="Null: no default.")
    default_urgency: Urgency | None = Field(default=None, description="Null: no default.")
    auto_status_on_assign: bool | None = None
    keep_following_on_handover: bool | None = None
    on_behalf_scope: OnBehalfScope | None = None
    approvals_hidden_from_requesters: bool | None = None
    approvals_require_sign_in: bool | None = None
    portal_show_due_time: bool | None = None
    first_task_starts_work: bool | None = None
    review_required_priorities: list[Priority] | None = Field(default=None, max_length=4)
    segregation_strict: bool | None = Field(default=None, description="Changes only.")
    cab_every_match: bool | None = Field(default=None, description="Changes only.")
    reapproval: ReapprovalPolicyIO | None = Field(
        default=None, description="Changes only. Null: the shipped policy."
    )
    first_response_on: list[FirstResponseAction] | None = Field(default=None, max_length=3)


class WorkItemCategoryOut(BaseModel):
    """One node of the category tree."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    level: int
    code: str | None = Field(description="Seeded nodes: labelled by the UI from this code.")
    labels: dict[str, str] | None = Field(description="Admin nodes: their own translations.")
    sort_order: int
    default_group_id: uuid.UUID | None
    disabled: bool
    version: int

    @classmethod
    def of(cls, node: WorkItemCategory) -> "WorkItemCategoryOut":
        """From a row."""
        return cls(
            id=node.id,
            parent_id=node.parent_id,
            level=node.level,
            code=node.code,
            labels=node.labels,
            sort_order=node.sort_order,
            default_group_id=node.default_group_id,
            disabled=node.disabled_at is not None,
            version=node.version,
        )


class WorkItemCategoryIn(BaseModel):
    """A new node: under `parent_id`, or a new top-level category."""

    model_config = ConfigDict(extra="forbid")

    parent_id: uuid.UUID | None = None
    labels: dict[str, str] = Field(
        description='{"en": "...", "ar": "...", "ur": "..."}; en required.'
    )
    default_group_id: uuid.UUID | None = None


class WorkItemCategoryPatch(BaseModel):
    """Rename / translate, default group, disable."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = None
    default_group_id: uuid.UUID | None = None
    disabled: bool | None = None


class WorkItemFieldChangeOut(BaseModel):
    """One field of one save. Values are codes, IDs, text or ISO times; the UI labels them."""

    field: str
    old: Any = None
    new: Any = None


class WorkItemHistoryEntryOut(BaseModel):
    """One save: who, when (microseconds), from where, what, why, and which automation."""

    change_id: uuid.UUID
    version: int
    kind: ChangeKind
    occurred_at: datetime
    actor_type: Literal["user", "system"]
    actor_id: str | None
    actor_name: str | None
    source: Source
    reason: str | None
    automation: dict[str, Any] | None = Field(
        description="Set when automation made the change, e.g. {kind: matrix}."
    )
    bulk_job_id: uuid.UUID | None = Field(
        default=None, description="The bulk job that made this change for its actor (WP-020d)."
    )
    changes: list[WorkItemFieldChangeOut]
    audit_entry_id: uuid.UUID | None = Field(
        default=None,
        description="The audit entry of this save; only for holders of audit.view (REQ-AUD-006).",
    )

    @classmethod
    def of(
        cls,
        entry: HistoryEntry,
        names: dict[str, str],
        audit: dict[uuid.UUID, uuid.UUID] | None = None,
    ) -> "WorkItemHistoryEntryOut":
        """From a history entry plus resolved actor names (and audit links, if allowed)."""
        return cls(
            change_id=entry.change_id,
            version=entry.version,
            kind=entry.kind,
            occurred_at=entry.occurred_at,
            actor_type="user" if entry.actor_type == "user" else "system",
            actor_id=entry.actor_id,
            actor_name=names.get(entry.actor_id or ""),
            source=entry.source,
            reason=entry.reason,
            automation=entry.automation_ref if isinstance(entry.automation_ref, dict) else None,
            bulk_job_id=entry.batch_id,
            changes=[
                WorkItemFieldChangeOut(field=c.field, old=c.old, new=c.new) for c in entry.changes
            ],
            audit_entry_id=(audit or {}).get(entry.change_id),
        )


class WorkItemHistoryOut(BaseModel):
    """Saves of one record, newest first."""

    items: list[WorkItemHistoryEntryOut]
    next_cursor: str | None
    people: dict[str, PersonOut] = Field(
        default_factory=dict, description="People named in changed values, by user ID."
    )


def _item(row: WorkItem) -> WorkItemListItem:
    return WorkItemListItem.model_validate(row, from_attributes=True)


def _cursor(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    """`<microseconds since epoch>_<change id>` (URL-safe, exact to the microsecond)."""
    if not value:
        return None
    try:
        micros, change = value.split("_", 1)
        moment = datetime.fromtimestamp(0, UTC) + timedelta(microseconds=int(micros))
        return moment, uuid.UUID(change)
    except ValueError as error:
        raise BadRequest(code="invalid_cursor") from error


def _cursor_text(at: datetime, change_id: uuid.UUID) -> str:
    delta = at - datetime.fromtimestamp(0, UTC)
    micros = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    return f"{micros}_{change_id}"


# --- the factory ----------------------------------------------------------------------------------


class AutomationRunOut(BaseModel):
    """One automation step on the record: names, codes and outcomes, never values."""

    id: uuid.UUID
    kind: str = Field(description="business_rule, routing, assignment, trigger or loop_guard")
    automation_name: str | None
    outcome: str
    detail: dict[str, Any]
    occurred_at: datetime


class ReleaseDetailsIn(BaseModel):
    """A release's own fields to change (send only those you change; null clears one)."""

    model_config = ConfigDict(extra="forbid")

    release_type: str | None = Field(
        default=None, max_length=40, description="A release type code."
    )
    risk: ReleaseRisk | None = None
    risk_reason: str | None = Field(
        default=None,
        max_length=REASON_TEXT_MAX,
        description="Why the risk changed (required then).",
    )
    release_version: str | None = Field(default=None, max_length=VERSION_MAX)
    build_ref: str | None = Field(default=None, max_length=BUILD_REF_MAX)
    release_reason: str | None = Field(default=None, max_length=40)
    release_notes: str | None = Field(
        default=None, max_length=RESOLUTION_MAX, description="Rich text, sanitised on save."
    )
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    release_manager_id: uuid.UUID | None = None
    release_engineer_id: uuid.UUID | None = None


class ReleaseDetailsOut(BaseModel):
    """A release's own fields (REQ-REL-002..005), with the release's version for If-Match."""

    work_item_id: uuid.UUID
    version: int = Field(description="The release's version: send it back as If-Match.")
    release_type: str | None
    risk: ReleaseRisk | None
    release_version: str | None
    build_ref: str | None
    release_reason: str | None
    release_notes: str | None
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    actual_start: datetime | None
    actual_end: datetime | None
    release_manager_id: uuid.UUID | None
    release_engineer_id: uuid.UUID | None

    @classmethod
    def of(cls, view: service.ReleaseDetailsView) -> "ReleaseDetailsOut":
        """From the service view (all empty before any field is set)."""
        row = view.details
        return cls(
            work_item_id=view.record.id,
            version=view.record.version,
            **{n: (getattr(row, n) if row is not None else None) for n in DETAIL_FIELDS},
        )


class ChangeCopyIn(BaseModel):
    """What a copy of a change brings besides its fields (REQ-CHG-003)."""

    model_config = ConfigDict(extra="forbid")

    parts: list[Literal["plans", "roles"]] = Field(default_factory=list, max_length=2)


class ChangePrefillOut(BaseModel):
    """A new change's starting values from another record (REQ-CHG-002)."""

    subject: str
    description: str | None
    requester_id: uuid.UUID
    impact: str | None
    urgency: str | None
    site_id: uuid.UUID | None
    from_record_id: uuid.UUID = Field(description="Send back on create to link the two.")


class ChangeDetailsIn(BaseModel):
    """A change's own fields to change (send only those you change; null clears one)."""

    model_config = ConfigDict(extra="forbid")

    change_type: str | None = Field(default=None, max_length=40, description="A change type code.")
    change_reason: str | None = Field(
        default=None, max_length=40, description="A reason for change code."
    )
    risk_chosen: RiskLevel | None = Field(
        default=None,
        description="Override the calculated risk (REQ-CHG-060): needs risk_reason. Null: none.",
    )
    risk_reason: str | None = Field(default=None, max_length=500)


class ChangeRiskAssessmentIn(BaseModel):
    """The questionnaire's answers, one per question (REQ-CHG-057)."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, str] = Field(max_length=50)


class ChangeRiskAnswerOut(BaseModel):
    """One answer and its weight."""

    code: str
    score: int


class ChangeRiskQuestionOut(BaseModel):
    """One question with its weighted answers (labels: risk_question.<code> and its answers)."""

    code: str
    answers: list[ChangeRiskAnswerOut]


class ChangeRiskBandOut(BaseModel):
    """Scores from `low` map to `level`."""

    low: int
    level: RiskLevel


class ChangeRiskQuestionnaireOut(BaseModel):
    """The questionnaire this change is assessed with (its template's, else Appendix A's)."""

    version: int
    questions: list[ChangeRiskQuestionOut]
    bands: list[ChangeRiskBandOut]


def _plain(value: object) -> str | int | None:
    """A watched value as JSON: times as ISO text, levels by their code, versions as numbers."""
    if value is None or isinstance(value, int):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class ApprovalFieldChangeOut(BaseModel):
    """One watched value that changed since approval."""

    field: str = Field(description="window_start, window_end, risk or plans.<section>.")
    before: str | int | None
    after: str | int | None
    effect: OnChange


class StageChangesOut(BaseModel):
    """What changed since one stage of the change was approved (REQ-CHG-053 AC3)."""

    stage: str
    changes: list[ApprovalFieldChangeOut]

    @classmethod
    def of(cls, found: "reapproval_service.StageChanges") -> "StageChangesOut":
        """From the service's comparison."""
        return cls(
            stage=found.stage,
            changes=[
                ApprovalFieldChangeOut(
                    field=c.field, before=_plain(c.before), after=_plain(c.after), effect=c.effect
                )
                for c in found.changes
            ],
        )


class EmergencyOverrideIn(BaseModel):
    """Why the change must go on without its approval (D-144)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class ReapprovalPreviewIn(BaseModel):
    """What a person is about to save; leave out what stays."""

    model_config = ConfigDict(extra="forbid")

    window_start: datetime | None = None
    window_end: datetime | None = None
    risk: RiskLevel | None = None


class ChangeApprovalBarredOut(BaseModel):
    """Someone the level would name who may not approve, and why."""

    user_id: uuid.UUID
    reason: RouteReason


class ChangeApprovalPreviewOut(BaseModel):
    """The stage's first level as it would open now (REQ-CHG-039: never a silent skip)."""

    stage: str
    approver_ids: list[uuid.UUID]
    barred: list[ChangeApprovalBarredOut]
    fallback_reason: RouteReason | None = Field(
        description="Set: the approval administrators decide as well, for this reason."
    )
    people: dict[str, PersonOut] = Field(
        default_factory=dict, description="The approvers and the people left out, by user ID."
    )

    @classmethod
    def of(
        cls, found: "board_service.Preview", people: dict[str, PersonOut] | None = None
    ) -> "ChangeApprovalPreviewOut":
        """From the service's preview."""
        return cls(
            people=people or {},
            stage=found.stage,
            approver_ids=list(found.named),
            barred=[
                ChangeApprovalBarredOut(user_id=u, reason=RouteReason(r)) for u, r in found.barred
            ],
            fallback_reason=RouteReason(found.fallback_reason) if found.fallback_reason else None,
        )


class ChangeDetailsOut(BaseModel):
    """A change's own fields (REQ-CHG-005, -011), with the change's version for If-Match."""

    work_item_id: uuid.UUID
    version: int = Field(description="The change's version: send it back as If-Match.")
    change_type: str | None
    change_reason: str | None
    retrospective: bool = Field(description="Logged after the fact (REQ-CHG-004).")
    risk: RiskLevel | None = Field(default=None, description="Calculated (REQ-CHG-057).")
    risk_score: int | None = None
    risk_answers: dict[str, str] | None = None
    risk_version: int | None = None
    risk_chosen: RiskLevel | None = Field(default=None, description="The override, if any.")
    risk_reason: str | None = None
    sent_back: bool = Field(
        default=False,
        description="Sent back for approval by a re-approval restart: an emergency override may "
        "keep it going (D-144).",
    )

    @classmethod
    def of(cls, view: service.DetailsView) -> "ChangeDetailsOut":
        """From the service view (all empty before any field is set)."""
        row = view.details
        return cls(
            work_item_id=view.record.id,
            version=view.record.version,
            **{n: (getattr(row, n) if row is not None else None) for n in CHANGE_DETAIL_FIELDS},
            retrospective=bool(getattr(row, "retrospective", False)),  # a change's row only
            **{n: getattr(row, n, None) for n in risk_rules.RISK_FIELDS},
            sent_back=getattr(row, "resume_stage", None) is not None,
        )


class RoleHoldingOut(BaseModel):
    """One role of the record and who holds it."""

    code: str
    labels: dict[str, str] | None = Field(description="Null: labelled by the UI from the code.")
    single: bool = Field(description="Held by one person; otherwise people and groups.")
    system: bool
    disabled: bool
    user_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]


class RolesOut(BaseModel):
    """A record's roles tab (REQ-REL-023), with the record's version for If-Match."""

    version: int
    roles: list[RoleHoldingOut]
    people: dict[str, str] = Field(description="Holders' display names, by user ID.")

    @classmethod
    def of(cls, view: service.RolesView) -> "RolesOut":
        """From the service view."""
        return cls(
            version=view.record.version,
            roles=[
                RoleHoldingOut(
                    code=r.definition.code,
                    labels=r.definition.labels,
                    single=r.definition.single,
                    system=r.definition.system,
                    disabled=r.definition.disabled_at is not None,
                    user_ids=list(r.user_ids),
                    group_ids=list(r.group_ids),
                )
                for r in view.roles
            ],
            people=dict(view.names),
        )


class RoleHoldersIn(BaseModel):
    """Who holds the role now (replaces the holders; both empty clears it)."""

    model_config = ConfigDict(extra="forbid")

    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class PersonOptionOut(BaseModel):
    """A person a picker may offer."""

    id: uuid.UUID
    name: str


class PlanSectionOut(BaseModel):
    """One plan section (REQ-REL-025), with its own version for If-Match (0: not written)."""

    section: str
    content: str | None = Field(description="Sanitised rich text.")
    version: int
    updated_at: datetime | None
    updated_by: uuid.UUID | None


class PlanSectionIn(BaseModel):
    """A plan section's text (rich text, sanitised on save; empty clears it)."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, max_length=RESOLUTION_MAX)
    convert_to_normal: bool | None = Field(
        default=None,
        description=(
            "A standard change's plan is locked (409 standard_change_locked): true confirms "
            "making it a normal change, which goes through normal approval (REQ-CHG-006)."
        ),
    )


class StageScheduleOut(BaseModel):
    """A stage's dates and outcome on the record's path (REQ-REL-026, -028)."""

    stage: str
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    actual_start: datetime | None
    actual_end: datetime | None
    outcome: StageOutcome | None
    outcome_notes: str | None
    issues: str | None
    version: int = Field(description="This stage row's version for If-Match (0: none yet).")
    overdue: bool = Field(
        default=False,
        description="Its scheduled end has passed and it has not ended (REQ-CHG-017).",
    )


class StageScheduleIn(BaseModel):
    """What to change (only what is sent). Correcting an actual date needs a reason."""

    model_config = ConfigDict(extra="forbid")

    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    outcome: StageOutcome | None = None
    outcome_notes: str | None = Field(default=None, max_length=10_000)
    issues: str | None = Field(default=None, max_length=10_000)
    reason: str | None = Field(default=None, max_length=REASON_TEXT_MAX)


class DowntimeOut(BaseModel):
    """A planned or actual downtime window (REQ-REL-027)."""

    id: uuid.UUID
    phase: DowntimePhase
    kind: str | None = Field(description="A downtime_kind list code.")
    starts_at: datetime
    ends_at: datetime
    description: str | None
    service_ids: list[uuid.UUID]
    ci_ids: list[uuid.UUID]
    source_work_item_id: uuid.UUID | None
    version: int

    @classmethod
    def of(cls, row: WorkItemDowntime) -> "DowntimeOut":
        """From a row."""
        return cls.model_validate(row, from_attributes=True)


class DowntimeIn(BaseModel):
    """A downtime window's fields (only what is sent, on a change)."""

    model_config = ConfigDict(extra="forbid")

    phase: DowntimePhase | None = None
    kind: str | None = Field(default=None, max_length=40)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    description: str | None = Field(default=None, max_length=10_000)
    service_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    ci_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class SubReleaseOut(BaseModel):
    """A sub-release as its parent lists it (REQ-REL-037); hidden ones show only that they exist."""

    id: uuid.UUID
    visible: bool
    display_id: str | None
    subject: str | None
    stage: str | None
    status: str | None


class ParentIn(BaseModel):
    """The release's parent (null: none)."""

    model_config = ConfigDict(extra="forbid")

    parent_id: uuid.UUID | None


class ParentOut(BaseModel):
    """The release's parent now."""

    parent_id: uuid.UUID | None


class StageMoveIn(BaseModel):
    """A listed status move of a staged type (ADR-041): the target status and its reason."""

    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(max_length=40, description="A status listed as a move from here.")
    reason_code: str | None = Field(default=None, max_length=40)
    reason_text: str | None = Field(default=None, max_length=REASON_TEXT_MAX)
    resolution: str | None = Field(
        default=None,
        max_length=RESOLUTION_MAX,
        description="Moving into a resolved status: the outcome, rich text (sanitised).",
    )
    closure_code: str | None = Field(
        default=None, max_length=40, description="Moving into a closed status: a closure code."
    )
    confirm_open_work: bool = Field(
        default=False, description="Closing with open tasks or approvals: you confirm."
    )
    fields: dict[str, Any] | None = Field(
        default=None,
        description="Values the move asks for (see `missing` on the stages panel), saved in the"
        " same request with the usual edit checks and history.",
    )


class StageEntryOut(BaseModel):
    """One time the record was in a stage."""

    entered_at: datetime
    left_at: datetime | None


class RailStageOut(BaseModel):
    """One stage on the rail, in path order."""

    stage: str
    state: RailState
    optional: bool
    entries: list[StageEntryOut]


class MissingFieldOut(BaseModel):
    """A value a move still needs."""

    field: str
    code: str = Field(description="`required` (the move) or `required_to_leave_stage`.")


class StageMoveOut(BaseModel):
    """A move offered from the current status."""

    to_status: str
    to_stage: str
    reason_mode: ReasonMode
    reason_list: ReasonList | None
    required_fields: list[str]
    allowed: bool
    reason: str | None = Field(description="Why you may not (a code), when not allowed.")
    missing: list[MissingFieldOut] = Field(
        default_factory=list, description="Values the move asks for in its dialog (REQ-REL-018)."
    )
    lands_in: str = Field(
        description="The status it ends in, after any automatic advance from a completing one."
    )


class StagePanelOut(BaseModel):
    """A staged record's rail and its offered moves."""

    stage: str
    stage_path: str
    status: str
    version: int
    rail: list[RailStageOut]
    moves: list[StageMoveOut]

    @classmethod
    def of(cls, panel: service.StagePanel) -> "StagePanelOut":
        """From the service panel."""
        r = panel.record
        return cls(
            stage=str(r.stage),
            stage_path=str(r.stage_path),
            status=r.status,
            version=r.version,
            rail=[
                RailStageOut(
                    stage=s.stage,
                    state=s.state,
                    optional=s.optional,
                    entries=[
                        StageEntryOut(entered_at=e.entered_at, left_at=e.left_at) for e in s.entries
                    ],
                )
                for s in panel.rail
            ],
            moves=[
                StageMoveOut(
                    to_status=m.transition.to_status,
                    to_stage=m.to_stage,
                    reason_mode=m.transition.reason_mode,
                    reason_list=m.transition.reason_list,
                    required_fields=list(m.transition.required_fields),
                    allowed=m.allowed,
                    reason=m.reason,
                    missing=[MissingFieldOut(field=f, code=c) for f, c in m.missing],
                    lands_in=m.lands_in or m.transition.to_status,
                )
                for m in panel.moves
            ],
        )


async def _audit_reapproval(
    session: AsyncSession, request: Request, wtype: WorkItemType, record_id: uuid.UUID
) -> None:
    """A change sent back for approval by this save is audited (REQ-CHG-053, Haider)."""
    if wtype.code is not WorkItemTypeCode.CHANGE:
        return
    for entry in await reapproval_service.sent_back_in_this_save(session, record_id):
        await record_audit(
            session,
            action_code="change.sent_back_for_approval",
            facts=RequestFacts.of(request),
            object_type="change",
            object_id=record_id,
            details={"stage": entry.stage, "entry_id": str(entry.id)},
        )


def build_router(wtype: WorkItemType) -> APIRouter:  # noqa: C901, PLR0915 - one route per operation
    """Every route of one work item type."""
    router = APIRouter(
        prefix=f"/{wtype.path}",
        tags=[wtype.path],
        dependencies=[Depends(rate_limit("work_items"))],
        responses=RESPONSES,
    )
    perm = wtype.permission
    View = Annotated[Subject, Depends(require_permission(perm("view")))]  # noqa: N806 - type alias
    Create = Annotated[Subject, Depends(require_permission(perm("create")))]  # noqa: N806 - type alias
    Edit = Annotated[Subject, Depends(require_permission(perm("edit")))]  # noqa: N806 - type alias
    Assign = Annotated[Subject, Depends(require_permission(perm("assign")))]  # noqa: N806 - type alias
    Take = Annotated[Subject, Depends(require_permission(perm("take")))]  # noqa: N806 - type alias
    DueDates = Annotated[Subject, Depends(require_permission(perm("edit_due_dates")))]  # noqa: N806 - type alias
    Delete = Annotated[Subject, Depends(require_permission(perm("delete")))]  # noqa: N806 - type alias
    Admin = Annotated[  # noqa: N806 - type alias
        Subject, Depends(require_permission("config.service_desk", "settings.manage"))
    ]
    Policy = Annotated[PolicyService, Depends(get_policy)]  # noqa: N806 - type alias
    # The record's own requester (no console permission): the service checks it is theirs.
    SignedIn = Annotated[Subject, Depends(require_signed_in())]  # noqa: N806 - type alias
    Query_ = Annotated[ListQuery, Depends(list_dependency(wtype))]  # noqa: N806 - type alias
    location = f"/api/v1/{wtype.path}"
    name = wtype.code.replace("_", " ")
    audit = wtype.code.value  # audit codes: "incident.deleted", "service_request.deleted"

    async def _page(
        session: Any,  # noqa: ANN401 - TenantSession (an AsyncSession) from the route
        page: PageResult[WorkItem],
    ) -> WorkItemPage:
        people = sorted(
            {str(u) for r in page.rows for u in (r.requester_id, r.technician_id) if u is not None}
        )
        return WorkItemPage(
            items=[_item(r) for r in page.rows],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
            estimated_total=page.estimated_total,
            people=_people(await user_contacts(session, people)),
        )

    @router.get("", summary=f"List {wtype.path}")
    async def list_items(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        session: TenantSession,
        query: Query_,
        subject: View,
        request: Request,
        view: Annotated[str | None, Query(description="A built-in view (see /views).")] = None,
        tag: Annotated[str | None, Query(max_length=40)] = None,
    ) -> WorkItemPage:
        """Records you may see. Filter with the DSL or simple parameters, a view and a tag."""
        page = await service.list_page(
            session, subject, wtype, query, view=view, zone=request_zone(request), tag=tag
        )
        return await _page(session, page)

    @router.get("/views", summary=f"Built-in {name} views with counts")
    async def views(
        session: TenantSession, subject: View, request: Request
    ) -> list[WorkItemViewCountOut]:
        """Every built-in view in its fixed order, with how many records you see in it."""
        found = await service.view_counts(session, subject, wtype, zone=request_zone(request))
        return [WorkItemViewCountOut(view=v, count=c, capped=capped) for v, c, capped in found]

    @router.get("/trash", summary=f"{name.capitalize()}s in the trash")
    async def trash(
        session: TenantSession, query: Query_, subject: Delete, request: Request
    ) -> WorkItemPage:
        """Deleted records you may restore (needs the delete permission)."""
        page = await service.list_page(
            session, subject, wtype, query, view=None, zone=request_zone(request), trash=True
        )
        return await _page(session, page)

    @router.get("/assignees", summary="People who can be assigned")
    async def assignees(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        session: TenantSession,
        subject: View,
        policy: Policy,
        group_id: uuid.UUID | None = None,
        search: Annotated[str | None, Query(max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[WorkItemAssigneeOut]:
        """Members of `group_id` (or everyone) who can work on these records, with open load."""
        found = await service.assignees(
            session,
            subject,
            wtype,
            policy,
            group_id=group_id,
            search=strip_isolates(search or "").strip() or None,  # a pasted name may carry marks
            limit=limit,
        )
        return [
            WorkItemAssigneeOut(
                id=u, display_name=n, email=e, open_count=c, group_ids=sorted(g, key=str)
            )
            for u, n, e, c, g in found
        ]

    @router.get("/search", summary=f"Search {wtype.path}")
    async def search(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        session: TenantSession,
        subject: View,
        q: Annotated[
            str | None,
            Query(
                max_length=200,
                description="Display ID, subject or description words, or the requester's name "
                "or email. Word forms (English, Arabic), Urdu word starts and typos match.",
            ),
        ] = None,
        status_category: Annotated[list[StatusCategory], Query()] = [],  # noqa: B006 - FastAPI copies query defaults
        requester_id: uuid.UUID | None = None,
        ids: Annotated[
            list[uuid.UUID] | None,
            Query(max_length=20, description="Only these records (e.g. recently viewed)."),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=search_service.MAX_RESULTS)] = 20,
    ) -> WorkItemSearchOut:
        """Records you may see, exactly as in the lists (REQ-INC-085), best match first.

        Without `q`: the most recently updated (narrowed by the other parameters).
        """
        rows = await search_service.search(
            session,
            subject,
            wtype,
            strip_isolates(q or "").strip() or None,  # a pasted ID or name may carry marks
            status_categories={c.value for c in status_category},
            requester_id=requester_id,
            ids=ids,
            limit=limit,
        )
        people = sorted({str(u) for r in rows for u in (r.requester_id, r.technician_id) if u})
        return WorkItemSearchOut(
            items=[_item(r) for r in rows],
            people=_people(await user_contacts(session, people)),
        )

    if wtype is INCIDENT:

        @router.get(
            "/{record_id}/causing-problem",
            summary="The problem causing this incident, as incident technicians see it",
        )
        async def causing_problem(
            record_id: uuid.UUID, session: TenantSession, subject: View
        ) -> CausingProblemOut | None:
            """What anyone who may see the incident is told (WP-044c D14, REQ-PRB-071).

            The problem's title, status, known error marker, workaround and target date, never
            its root cause. Null when no problem causes it.
            """
            found = await problem_service.causing_view(session, subject, record_id)
            return None if found is None else CausingProblemOut.of(found)

        @router.post("/possible-duplicates", summary="Possible duplicates of a new incident")
        async def possible_duplicates(
            body: DuplicatesQuery,
            session: TenantSession,
            subject: Create,
            request: Request,
        ) -> DuplicatesOut:
            """Open incidents you may see that look like the one being written (REQ-INC-022).

            A POST: the draft's text travels in the body, never in a URL (proxy logs, history).
            With AI on: by meaning (logged as an AI call). With AI off: by subject, no model
            (D-134). The same requester's incidents from the last hour count extra.
            """
            gateway: Gateway = getattr(request.app.state, GATEWAY_STATE)
            found, method = await duplicates_service.possible_duplicates(
                session,
                subject,
                gateway,
                title=strip_isolates(body.title).strip(),
                description=body.description,
                requester_id=body.requester_id,
                exclude=body.exclude,
            )
            people = sorted(
                {
                    str(u)
                    for c in found
                    for u in (c.record.requester_id, c.record.technician_id)
                    if u
                }
            )
            return DuplicatesOut(
                items=[
                    DuplicateOut(item=_item(c.record), score=c.score, reasons=list(c.reasons))
                    for c in found
                ],
                method=method,
                people=_people(await user_contacts(session, people)),
            )

    @router.get("/lookup/{value}", summary="Find by display ID")
    async def lookup(
        value: str, session: TenantSession, subject: View, response: Response
    ) -> WorkItemOut:
        """`INC-12`, `inc-12` or `12`. Old prefixes keep working after a rename."""
        found = await service.lookup(session, subject, wtype, value[:40])
        set_etag(response, found.record.version)
        return WorkItemOut.of(found)

    @router.get("/settings", summary=f"{name.capitalize()} configuration")
    async def get_settings(
        session: TenantSession, subject: View, response: Response
    ) -> WorkItemCatalogueOut:
        """Statuses, actions, transitions, scales, the matrix, reasons and the prefix."""
        del subject
        cat = await settings_service.get_catalogue(session, wtype)
        set_etag(response, cat.settings_version)
        return await WorkItemCatalogueOut.of(session, cat)

    @router.patch("/settings", summary=f"Change {name} settings", responses=CONFLICT)
    async def patch_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: WorkItemSettingsPatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Annotated[
            AuditNote, audited(f"{audit}.settings_changed", object_type=f"{audit}_settings")
        ],
    ) -> WorkItemCatalogueOut:
        """Prefix, default priority and the automatic status moves on assignment."""
        note.details = {"changed_fields": sorted(body.model_fields_set)}
        cat = await settings_service.update_settings(
            session,
            wtype,
            expected_version=version,
            values={
                k: v
                for k, v in body.model_dump(include=body.model_fields_set).items()
                if v is not None or k in NULLABLE_SETTINGS
            },
            source=source_of(request),
            user_id=subject.user_id,
        )
        set_etag(response, cat.settings_version)
        return await WorkItemCatalogueOut.of(session, cat)

    @router.patch(
        "/settings/closure", summary=f"Change how {name}s resolve and close", responses=CONFLICT
    )
    async def patch_closure(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: WorkItemClosurePatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Annotated[
            AuditNote, audited(f"{audit}.settings_changed", object_type=f"{audit}_settings")
        ],
    ) -> WorkItemCatalogueOut:
        """Closure rules, open work, auto-close (needs a channel that tells requesters), reopen."""
        note.details = {"changed_fields": sorted(body.model_fields_set)}
        sent = body.model_dump(include=body.model_fields_set)
        cat = await settings_service.update_closure_settings(
            session,
            wtype,
            expected_version=version,
            values={k: v for k, v in sent.items() if v is not None or k == "auto_close_days"},
            source=source_of(request),
            user_id=subject.user_id,
        )
        set_etag(response, cat.settings_version)
        return await WorkItemCatalogueOut.of(session, cat)

    @router.get("/categories", summary="Category tree")
    async def categories(session: TenantSession, subject: View) -> list[WorkItemCategoryOut]:
        """Every node, parents first; disabled nodes are marked, not hidden."""
        del subject
        return [
            WorkItemCategoryOut.of(n)
            for n in await settings_service.list_categories(session, wtype)
        ]

    @router.post("/categories", summary="Add a category", status_code=status.HTTP_201_CREATED)
    async def create_category(
        body: WorkItemCategoryIn,
        session: TenantSession,
        subject: Admin,
        request: Request,
        note: Annotated[
            AuditNote, audited(f"{audit}.category_created", object_type=f"{audit}_category")
        ],
    ) -> WorkItemCategoryOut:
        """A new node (at most three levels)."""
        del subject
        node = await settings_service.create_category(
            session,
            wtype,
            parent_id=body.parent_id,
            labels=body.labels,
            default_group_id=body.default_group_id,
            source=source_of(request),
        )
        out = WorkItemCategoryOut.of(node)
        note.object_id = str(out.id)
        note.details = {"parent_id": body.parent_id}
        return out

    @router.patch("/categories/{category_id}", summary="Change a category", responses=CONFLICT)
    async def patch_category(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        category_id: uuid.UUID,
        body: WorkItemCategoryPatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        request: Request,
        note: Annotated[
            AuditNote,
            audited(
                f"{audit}.category_changed",
                object_type=f"{audit}_category",
                object_param="category_id",
            ),
        ],
    ) -> WorkItemCategoryOut:
        """Rename or translate, set its default group, disable or enable."""
        del subject
        note.details = {"changed_fields": sorted(body.model_fields_set)}
        node = await settings_service.update_category(
            session,
            wtype,
            category_id,
            expected_version=version,
            values=body.model_dump(include=body.model_fields_set),
            source=source_of(request),
        )
        return WorkItemCategoryOut.of(node)

    add_list_routes(router, wtype)
    if wtype.code is WorkItemTypeCode.SERVICE_REQUEST:
        add_approval_routes(router, wtype)  # WP-030 s2: before the /{record_id} routes
    elif wtype.code in {
        WorkItemTypeCode.RELEASE,
        WorkItemTypeCode.PROBLEM,
        WorkItemTypeCode.CHANGE,
    }:
        # Release and change stage approvals (WP-058a s5, WP-045a) and problem approvals asked
        # ad hoc (WP-044b s4): none has a requester's withdrawal (a change is canceled instead).
        add_approval_routes(router, wtype, withdraw=False)
    if wtype.code is WorkItemTypeCode.CHANGE:
        # WP-045a D6 (REQ-CHG-002): before the /{record_id} routes.

        @router.get("/prefill", summary="A new change's values from another record")
        async def change_prefill(
            record_id: uuid.UUID, session: TenantSession, subject: Create
        ) -> ChangePrefillOut:
            """From an incident, request, problem or release you see; every value is editable."""
            return ChangePrefillOut(**await change_links.prefill(session, subject, record_id))

    if wtype.code is WorkItemTypeCode.PROBLEM:
        # WP-044a s3: before the /{record_id} routes
        add_problem_routes(router, wtype, record_in=WorkItemIn, record_out=WorkItemOut)
    add_parts_collection_routes(router, wtype)
    add_collection_routes(router, wtype)
    add_settings_routes(router, wtype, WorkItemCatalogueOut)

    @router.post(
        "",
        summary=f"Create {'an' if name[0] in 'aeiou' else 'a'} {name}",
        status_code=status.HTTP_201_CREATED,
        response_model=WorkItemOut,
        responses=CONFLICT,
    )
    async def create(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: WorkItemIn,
        session: TenantSession,
        subject: Create,
        idempotency: Idempotency,
        request: Request,
        policy: Policy,
    ) -> Response:
        """A new record. Send an Idempotency-Key: a retried request returns the same 201."""

        async def run() -> Created:
            values = body.model_dump(exclude_unset=True)
            from_record = values.pop("from_record_id", None)
            if from_record is not None and wtype.code is not WorkItemTypeCode.CHANGE:
                raise service.field_errors([("from_record_id", "not_allowed")])
            asset_ids = values.pop("asset_ids", None) or []
            if asset_ids and wtype.code not in _WITH_ASSETS:
                raise service.field_errors([("asset_ids", "not_allowed")])
            view = await service.create(
                session,
                subject,
                wtype,
                values,
                source=source_of(request),
                holders=policy,
            )
            if from_record is not None:  # REQ-CHG-002: linked to its source, on both records
                await change_links.link_new(
                    session, subject, view.record, from_record, source=source_of(request)
                )
            if asset_ids:  # REQ-AST-025: in the same transaction as the record
                await asset_links.link_new(
                    session, subject, view.record, asset_ids, source=source_of(request)
                )
            out = WorkItemOut.of(view)
            return Created(
                body=out, headers={"Location": f"{location}/{out.id}", "ETag": f'"{out.version}"'}
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.get("/{record_id}", summary=f"Get {'an' if name[0] in 'aeiou' else 'a'} {name}")
    async def get(
        record_id: uuid.UUID, session: TenantSession, subject: View, response: Response
    ) -> WorkItemOut:
        """One record within your view scope (404 otherwise, even if it exists)."""
        found = await service.get(session, subject, wtype, record_id)
        set_etag(response, found.record.version)
        return WorkItemOut.of(found)

    @router.patch("/{record_id}", summary="Edit fields", responses=CONFLICT)
    async def edit(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemPatch,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Edit,
        response: Response,
        request: Request,
    ) -> WorkItemOut:
        """Change the fields you send. Needs If-Match. Priority by hand needs a reason."""
        view = await service.update(
            session,
            subject,
            wtype,
            record_id,
            expected_version=version,
            values=body.model_dump(include=body.model_fields_set),
            source=source_of(request),
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.post("/{record_id}/actions/{action}", summary="Run a status action", responses=CONFLICT)
    async def act(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        action: WorkItemAction,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        response: Response,
        request: Request,
        policy: Policy,
        body: WorkItemTransitionIn | None = None,
    ) -> WorkItemOut:
        """Only the actions the life cycle allows from the current status; some need a reason.

        Start work on an unassigned record takes it for you first (`group_id` as with Take).
        """
        view = await service.transition(
            session,
            subject,
            wtype,
            record_id,
            action,
            expected_version=version,
            reason_code=body.reason_code if body else None,
            reason_text=body.reason_text if body else None,
            source=source_of(request),
            holders=policy,
            group_id=body.group_id if body else None,
            closing_input=MoveInput(
                resolution=body.resolution,
                closure_code=body.closure_code,
                confirm_open_work=body.confirm_open_work,
            )
            if body
            else None,
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    if wtype.stages is not None:  # ADR-041: staged types move by listed status transitions

        @router.get("/{record_id}/stages", summary="The stage rail and the moves from here")
        async def stage_panel(
            record_id: uuid.UUID, session: TenantSession, subject: View, response: Response
        ) -> StagePanelOut:
            """Each stage on the record's path (done, current, skipped, future) and its moves."""
            panel = await service.stage_panel(session, subject, wtype, record_id)
            set_etag(response, panel.record.version)
            return StagePanelOut.of(panel)

        @router.get("/{record_id}/schedule", summary="Each stage's dates and outcome")
        async def get_schedule(
            record_id: uuid.UUID, session: TenantSession, subject: View
        ) -> list[StageScheduleOut]:
            """The stages on the record's path, in order; actual dates are set by the engine."""
            _record, rows = await service.stage_schedules(session, subject, wtype, record_id)
            return [
                StageScheduleOut(
                    stage=stage,
                    **{n: getattr(row, n) if row else None for n in service.SCHEDULE_FIELDS},
                    version=row.version if row else 0,
                    overdue=service.schedule_overdue(row),
                )
                for stage, row in rows
            ]

        @router.patch(
            "/{record_id}/schedule/{stage}",
            summary="Change a stage's dates or outcome",
            responses=CONFLICT,
        )
        async def patch_schedule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            stage: str,
            body: StageScheduleIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: Edit,
            response: Response,
            request: Request,
        ) -> StageScheduleOut:
            """If-Match: the stage row's version (0 before anything is set)."""
            sent = body.model_dump(include=body.model_fields_set - {"reason"})
            row = await service.update_stage_schedule(
                session,
                subject,
                wtype,
                record_id,
                stage,
                values=sent,
                expected_version=version,
                reason=body.reason,
                source=source_of(request),
            )
            await _audit_reapproval(session, request, wtype, record_id)
            set_etag(response, row.version)
            return StageScheduleOut(
                stage=stage,
                **{n: getattr(row, n) for n in service.SCHEDULE_FIELDS},
                version=row.version,
            )

        @router.get("/{record_id}/downtimes", summary="Downtime windows")
        async def get_downtimes(
            record_id: uuid.UUID, session: TenantSession, subject: View
        ) -> list[DowntimeOut]:
            """Planned and actual windows, by start."""
            _record, rows = await service.downtimes(session, subject, wtype, record_id)
            return [DowntimeOut.of(r) for r in rows]

        @router.post(
            "/{record_id}/downtimes",
            summary="Add a downtime window",
            status_code=status.HTTP_201_CREATED,
            response_model=DowntimeOut,
        )
        async def add_downtime(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            body: DowntimeIn,
            session: TenantSession,
            subject: Edit,
            idempotency: Idempotency,
            request: Request,
        ) -> Response:
            """Send an Idempotency-Key: a retry returns the same 201."""

            async def run() -> Created:
                row = await service.save_downtime(
                    session,
                    subject,
                    wtype,
                    record_id,
                    None,
                    values=body.model_dump(include=body.model_fields_set),
                    expected_version=0,
                    source=source_of(request),
                )
                out = DowntimeOut.of(row)
                return Created(body=out, headers={"ETag": f'"{out.version}"'})

            return await idempotency.run(body, run)

        @router.patch(
            "/{record_id}/downtimes/{downtime_id}",
            summary="Change a downtime window",
            responses=CONFLICT,
        )
        async def patch_downtime(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            downtime_id: uuid.UUID,
            body: DowntimeIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: Edit,
            response: Response,
            request: Request,
        ) -> DowntimeOut:
            """If-Match: the window's version."""
            row = await service.save_downtime(
                session,
                subject,
                wtype,
                record_id,
                downtime_id,
                values=body.model_dump(include=body.model_fields_set),
                expected_version=version,
                source=source_of(request),
            )
            set_etag(response, row.version)
            return DowntimeOut.of(row)

        @router.delete(
            "/{record_id}/downtimes/{downtime_id}",
            summary="Remove a downtime window",
            status_code=status.HTTP_204_NO_CONTENT,
            responses=CONFLICT,
        )
        async def delete_downtime(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            downtime_id: uuid.UUID,
            version: ExpectedVersion,
            session: TenantSession,
            subject: Edit,
            request: Request,
        ) -> Response:
            """If-Match: the window's version."""
            await service.remove_downtime(
                session,
                subject,
                wtype,
                record_id,
                downtime_id,
                expected_version=version,
                source=source_of(request),
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        @router.post("/{record_id}/moves", summary="Move to a listed status", responses=CONFLICT)
        async def move(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            body: StageMoveIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: View,
            response: Response,
            request: Request,
        ) -> WorkItemOut:
            """Only moves listed from the current status on the record's path.

            A completing status moves on to the next stage in the same save. Needs If-Match.
            """
            view = await service.move_status(
                session,
                subject,
                wtype,
                record_id,
                target=body.to_status,
                expected_version=version,
                reason_code=body.reason_code,
                reason_text=body.reason_text,
                source=source_of(request),
                closing_input=MoveInput(
                    resolution=body.resolution,
                    closure_code=body.closure_code,
                    confirm_open_work=body.confirm_open_work,
                ),
                fields=body.fields,
            )
            if wtype.code is WorkItemTypeCode.CHANGE:  # REQ-CHG-039: a fallback is audited
                facts = RequestFacts.of(request)
                for row in await stage_approvals.rerouted_in_this_save(session, record_id):
                    await record_audit(
                        session,
                        action_code="change.approval_rerouted",
                        facts=facts,
                        object_type="change",
                        object_id=record_id,
                        details={
                            "approval_id": str(row.id),
                            "stage": row.record_stage,
                            "level": row.stage,
                            "reason": row.route_reason,
                            "to": "approval_administrators",
                            "board_id": str(row.board_id) if row.board_id else None,
                        },
                    )
            set_etag(response, view.record.version)
            return WorkItemOut.of(view)

    if wtype.plan_sections:  # REQ-REL-025: the plan's rich-text sections

        @router.get("/{record_id}/plan", summary="The plan's sections")
        async def get_plan(
            record_id: uuid.UUID, session: TenantSession, subject: View
        ) -> list[PlanSectionOut]:
            """Every section of the type, in order (version 0: not written yet)."""
            _record, rows = await service.plan_sections(session, subject, wtype, record_id)
            return [
                PlanSectionOut(
                    section=name,
                    content=row.content if row else None,
                    version=row.version if row else 0,
                    updated_at=row.updated_at if row else None,
                    updated_by=row.updated_by if row else None,
                )
                for name, row in rows
            ]

        @router.put(
            "/{record_id}/plan/{section}", summary="Write a plan section", responses=CONFLICT
        )
        async def put_plan(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            section: str,
            body: PlanSectionIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: Edit,
            response: Response,
            request: Request,
        ) -> PlanSectionOut:
            """If-Match: this section's version (0 the first time); other sections never clash."""
            row = await service.put_plan_section(
                session,
                subject,
                wtype,
                record_id,
                section,
                content=body.content,
                expected_version=version,
                source=source_of(request),
                convert_to_normal=body.convert_to_normal is True,
            )
            await _audit_reapproval(session, request, wtype, record_id)
            set_etag(response, row.version)
            return PlanSectionOut(
                section=section,
                content=row.content,
                version=row.version,
                updated_at=row.updated_at,
                updated_by=row.updated_by,
            )

    if wtype.roles:  # REQ-REL-023, -024: named roles on the record

        @router.get("/roles/{role}/candidates", summary="People who may hold a role")
        async def role_candidates(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query
            role: str,
            session: TenantSession,
            subject: View,
            policy: Policy,
            search: Annotated[str | None, Query(max_length=200)] = None,
            limit: Annotated[int, Query(ge=1, le=50)] = 20,
        ) -> list[PersonOptionOut]:
            """Only people the role allows (REQ-REL-024): active, and eligible by its rule."""
            found = await service.role_candidates(
                session, subject, wtype, role, search=search, holders=policy, limit=limit
            )
            return [PersonOptionOut(id=i, name=n) for i, n in found]

        @router.get("/{record_id}/roles", summary="The record's roles and their holders")
        async def get_roles(
            record_id: uuid.UUID, session: TenantSession, subject: View, response: Response
        ) -> RolesOut:
            """Every role in order with its holders (people and groups)."""
            view = await service.roles_of(session, subject, wtype, record_id)
            set_etag(response, view.record.version)
            return RolesOut.of(view)

        @router.put("/{record_id}/roles/{role}", summary="Set who holds a role", responses=CONFLICT)
        async def put_role(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            role: str,
            body: RoleHoldersIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: Edit,
            response: Response,
            request: Request,
            policy: Policy,
        ) -> RolesOut:
            """Needs If-Match (the record's version). Only eligible, active people (REQ-REL-024)."""
            view = await service.set_role(
                session,
                subject,
                wtype,
                record_id,
                role,
                user_ids=body.user_ids,
                group_ids=body.group_ids,
                expected_version=version,
                source=source_of(request),
                holders=policy,
            )
            set_etag(response, view.record.version)
            return RolesOut.of(view)

    if wtype.code is WorkItemTypeCode.RELEASE:  # REQ-REL-037: parent and sub-releases

        @router.get("/{record_id}/sub-releases", summary="The release's sub-releases")
        async def get_sub_releases(
            record_id: uuid.UUID, session: TenantSession, subject: View
        ) -> list[SubReleaseOut]:
            """With their stage and status, live; ones you may not see show only that they exist."""
            found = await release_links.sub_releases(session, subject, wtype, record_id)
            return [SubReleaseOut(**vars(s)) for s in found]

        @router.put("/{record_id}/parent", summary="Make it a sub-release of another release")
        async def put_parent(
            record_id: uuid.UUID,
            body: ParentIn,
            session: TenantSession,
            subject: Edit,
            request: Request,
        ) -> ParentOut:
            """One parent at most; loops are refused (REQ-REL-037 AC1). Null removes it."""
            parent = await release_links.set_parent(
                session, subject, wtype, record_id, body.parent_id, source=source_of(request)
            )
            return ParentOut(parent_id=parent)

    if wtype.code is WorkItemTypeCode.RELEASE:  # REQ-REL-002..005: a release's own fields

        @router.get("/{record_id}/details", summary="The release's own fields")
        async def get_details(
            record_id: uuid.UUID, session: TenantSession, subject: View, response: Response
        ) -> ReleaseDetailsOut:
            """Type, risk, version, build, reason, notes, dates and the release's people."""
            found = await service.release_details(session, subject, wtype, record_id)
            set_etag(response, found.record.version)
            return ReleaseDetailsOut.of(found)

        @router.post(
            "/{record_id}/copy",
            summary="Copy the release into a new one",
            status_code=status.HTTP_201_CREATED,
            response_model=WorkItemOut,
        )
        async def copy_release(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            session: TenantSession,
            subject: Create,
            idempotency: Idempotency,
            request: Request,
            policy: Policy,
        ) -> Response:
            """A new release from this one's fields (REQ-REL-009).

            Never stage progress, approvals, dates or worklogs. Send an Idempotency-Key: a retry
            returns the same 201.
            """

            async def run() -> Created:
                view = await service.copy_release(
                    session, subject, wtype, record_id, source=source_of(request), holders=policy
                )
                out = WorkItemOut.of(view)
                return Created(
                    body=out,
                    headers={"Location": f"{location}/{out.id}", "ETag": f'"{out.version}"'},
                )

            return await idempotency.run({"copy_of": str(record_id)}, run)

        @router.patch(
            "/{record_id}/details", summary="Change the release's own fields", responses=CONFLICT
        )
        async def patch_details(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            body: ReleaseDetailsIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: Edit,
            response: Response,
            request: Request,
        ) -> ReleaseDetailsOut:
            """Needs If-Match (the release's version). A risk change needs `risk_reason`."""
            sent = body.model_dump(include=body.model_fields_set - {"risk_reason"})
            view = await service.update_release_details(
                session,
                subject,
                wtype,
                record_id,
                expected_version=version,
                values=sent,
                source=source_of(request),
                risk_reason=body.risk_reason,
            )
            set_etag(response, view.record.version)
            return ReleaseDetailsOut.of(view)

    if wtype.code is WorkItemTypeCode.CHANGE:  # REQ-CHG-005, -011: a change's own fields

        @router.post(
            "/{record_id}/copy",
            summary="Copy the change into a new one",
            status_code=status.HTTP_201_CREATED,
            response_model=WorkItemOut,
        )
        async def copy_change(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            body: ChangeCopyIn,
            session: TenantSession,
            subject: Create,
            idempotency: Idempotency,
            request: Request,
            policy: Policy,
        ) -> Response:
            """A new change from this one's fields, and the plans or roles chosen (REQ-CHG-003).

            Never its approvals, history or schedule. Send an Idempotency-Key: a retry returns
            the same 201.
            """

            async def run() -> Created:
                made = await change_links.copy_change(
                    session,
                    subject,
                    record_id,
                    parts_chosen=frozenset(body.parts),
                    source=source_of(request),
                    holders=policy,
                )
                view = await service.get(session, subject, wtype, made.id)
                out = WorkItemOut.of(view)
                return Created(
                    body=out,
                    headers={"Location": f"{location}/{out.id}", "ETag": f'"{out.version}"'},
                )

            return await idempotency.run({"copy_of": str(record_id), **body.model_dump()}, run)

        @router.get("/{record_id}/details", summary="The change's own fields")
        async def get_change_details(
            record_id: uuid.UUID, session: TenantSession, subject: View, response: Response
        ) -> ChangeDetailsOut:
            """The change type and the reason for change."""
            found = await service.details(session, subject, wtype, record_id)
            set_etag(response, found.record.version)
            return ChangeDetailsOut.of(found)

        @router.get(
            "/{record_id}/approvals/changes-since",
            summary="What changed since the change's stages were approved",
        )
        async def approval_changes_since(
            record_id: uuid.UUID, session: TenantSession, subject: View
        ) -> list[StageChangesOut]:
            """Per approved stage, field by field, with what each change does (REQ-CHG-053)."""
            found = await reapproval_service.changes_since(session, subject, record_id)
            return [StageChangesOut.of(s) for s in found]

        @router.post(
            "/{record_id}/emergency-override",
            summary="Keep a change going that was sent back for approval",
            responses=CONFLICT,
        )
        async def emergency_override(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            body: EmergencyOverrideIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: View,
            response: Response,
            request: Request,
            note: Annotated[
                AuditNote,
                # The dependency also logs a refused attempt (lane B's #327 review).
                audited(
                    "change.emergency_override", object_type="change", object_param="record_id"
                ),
            ],
        ) -> WorkItemOut:
            """Needs changes.emergency_override, a reason and If-Match (D-144).

            The re-approval is withdrawn, the change returns where it was, and its review
            becomes mandatory. Audited with the reason, refused attempts too.
            """
            note.reason = body.reason
            updated = await reapproval_service.emergency_override(
                session,
                subject,
                record_id,
                reason=body.reason,
                expected_version=version,
                source=source_of(request),
            )
            note.details = {"stage": updated.stage, "status": updated.status}
            view = await service.get(session, subject, wtype, record_id)
            set_etag(response, view.record.version)
            return WorkItemOut.of(view)

        @router.post(
            "/{record_id}/approvals/reapproval-preview",
            summary="Would this save send the change back for approval?",
        )
        async def reapproval_preview(
            record_id: uuid.UUID, body: ReapprovalPreviewIn, session: TenantSession, subject: View
        ) -> list[StageChangesOut]:
            """The approved stages the proposed window or risk would send the change back to.

            Empty: the save keeps every approval. Changes nothing (REQ-CHG-053, Haider).
            """
            found = await reapproval_service.preview(
                session,
                subject,
                record_id,
                reapproval_service.Proposed(body.window_start, body.window_end, body.risk),
            )
            return [StageChangesOut.of(s) for s in found]

        @router.get(
            "/{record_id}/approvals/preview", summary="Who would approve the change's stage"
        )
        async def approvals_preview(
            record_id: uuid.UUID,
            session: TenantSession,
            subject: View,
            stage: Annotated[str | None, Query(max_length=40)] = None,
        ) -> ChangeApprovalPreviewOut | None:
            """Before a submit: who would approve, who is left out and why (REQ-CHG-039).

            Also whether the approval administrators decide too. Null: the stage needs no
            approval. Changes nothing.
            """
            found = await board_service.preview(session, subject, record_id, stage)
            if found is None:
                return None
            ids = {*found.named, *(u for u, _ in found.barred)}
            people = people_out(await user_contacts(session, sorted(str(u) for u in ids)))
            return ChangeApprovalPreviewOut.of(found, people)

        @router.get("/{record_id}/risk/questionnaire", summary="The change's risk questionnaire")
        async def risk_questionnaire(
            record_id: uuid.UUID, session: TenantSession, subject: View
        ) -> ChangeRiskQuestionnaireOut:
            """Its template's own, else Appendix A's (REQ-CHG-057)."""
            asked = await risk_service.questionnaire(session, subject, record_id)
            return ChangeRiskQuestionnaireOut.model_validate(risk_rules.questionnaire_json(asked))

        @router.put(
            "/{record_id}/risk/assessment",
            summary="Answer the risk questionnaire",
            responses=CONFLICT,
        )
        async def assess_risk(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            body: ChangeRiskAssessmentIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: Edit,
            response: Response,
            request: Request,
        ) -> ChangeDetailsOut:
            """Scores the answers and sets the calculated risk (If-Match: the change's version)."""
            view = await risk_service.assess(
                session,
                subject,
                record_id,
                answers=body.answers,
                expected_version=version,
                source=source_of(request),
            )
            await _audit_reapproval(session, request, wtype, record_id)
            set_etag(response, view.record.version)
            return ChangeDetailsOut.of(view)

        @router.patch(
            "/{record_id}/details", summary="Change the change's own fields", responses=CONFLICT
        )
        async def patch_change_details(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            record_id: uuid.UUID,
            body: ChangeDetailsIn,
            version: ExpectedVersion,
            session: TenantSession,
            subject: Edit,
            response: Response,
            request: Request,
        ) -> ChangeDetailsOut:
            """Needs If-Match (the change's version). Send only what you change; null clears."""
            view = await service.update_details(
                session,
                subject,
                wtype,
                record_id,
                expected_version=version,
                values=body.model_dump(include=body.model_fields_set),
                source=source_of(request),
            )
            await _audit_reapproval(session, request, wtype, record_id)
            set_etag(response, view.record.version)
            return ChangeDetailsOut.of(view)

    @router.post(
        "/{record_id}/resolution/confirm",
        summary="The requester confirms the resolution",
        responses=CONFLICT,
    )
    async def confirm_resolution(
        record_id: uuid.UUID, session: TenantSession, subject: SignedIn, request: Request
    ) -> ResolutionAnswerOut:
        """Closes it with the requester as actor (REQ-INC-096). 409 `not_resolved` otherwise."""
        answered = await resolution.confirm(
            session, subject, wtype, record_id, source=source_of(request)
        )
        return ResolutionAnswerOut.of(answered)

    @router.post(
        "/{record_id}/resolution/reject",
        summary="The requester says it is not fixed",
        responses=CONFLICT,
    )
    async def reject_resolution(
        record_id: uuid.UUID,
        body: ResolutionRejectIn,
        session: TenantSession,
        subject: SignedIn,
        request: Request,
    ) -> ResolutionAnswerOut:
        """Reopens it to in progress; the comment is a public reply by the requester."""
        answered = await resolution.reject(
            session, subject, wtype, record_id, comment=body.comment, source=source_of(request)
        )
        return ResolutionAnswerOut.of(answered)

    @router.post("/{record_id}/assign", summary="Assign or reassign", responses=CONFLICT)
    async def assign(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemAssignIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Assign,
        response: Response,
        request: Request,
        policy: Policy,
    ) -> WorkItemOut:
        """Set group and technician. A move out of your reach needs `confirm_lose_access`."""
        view = await service.assign(
            session,
            subject,
            wtype,
            record_id,
            expected_version=version,
            group_id=body.group_id,
            technician_id=body.technician_id,
            reason_code=body.reason_code,
            reason_text=body.reason_text,
            confirm_lose_access=body.confirm_lose_access,
            keep_following=body.keep_following,
            source=source_of(request),
            holders=policy,
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.post("/{record_id}/take", summary="Take it yourself", responses=CONFLICT)
    async def take(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Take,
        response: Response,
        request: Request,
        policy: Policy,
        body: WorkItemTakeIn | None = None,
    ) -> WorkItemOut:
        """You become the technician; with no group, your only group is set (or you choose)."""
        view = await service.take(
            session,
            subject,
            wtype,
            record_id,
            expected_version=version,
            group_id=body.group_id if body else None,
            source=source_of(request),
            holders=policy,
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.put(
        "/{record_id}/due-dates/{kind}",
        summary="Set or clear a due date by hand",
        responses=CONFLICT,
        dependencies=[
            audited(f"{audit}.due_date_changed", object_type=audit, object_param="record_id")
        ],
    )
    async def set_due_date(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        kind: SlaKind,
        body: WorkItemDueDateIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: DueDates,
        response: Response,
        request: Request,
    ) -> WorkItemOut:
        """REQ-SLA-028: the date stays through priority and policy changes until cleared."""
        view = await service.set_due_date(
            session,
            subject,
            wtype,
            record_id,
            kind=kind,
            due_at=body.due_at,
            reason=body.reason,
            expected_version=version,
            source=source_of(request),
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.delete(
        "/{record_id}",
        summary="Move to the trash",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT,
        dependencies=[audited(f"{audit}.deleted", object_type=audit, object_param="record_id")],
    )
    async def delete(
        record_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Delete,
        request: Request,
    ) -> Response:
        """Soft delete: recoverable from the trash with POST …/restore."""
        await service.remove(
            session, subject, wtype, record_id, expected_version=version, source=source_of(request)
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/{record_id}/restore",
        summary="Restore from the trash",
        responses=CONFLICT,
        dependencies=[audited(f"{audit}.restored", object_type=audit, object_param="record_id")],
    )
    async def restore(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Delete,
        response: Response,
        request: Request,
    ) -> WorkItemOut:
        """Take it out of the trash, as it was."""
        view = await service.restore(
            session, subject, wtype, record_id, expected_version=version, source=source_of(request)
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.get("/{record_id}/automation", summary="Automation log of the record")
    async def automation_log(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> list[AutomationRunOut]:
        """Triggers' outcomes per action and loop stops, newest first (kept 30 days)."""
        rows = await service.automation_log(session, subject, wtype, record_id)
        return [AutomationRunOut.model_validate(r, from_attributes=True) for r in rows]

    @router.get("/{record_id}/sla", summary="SLA")
    async def sla_panel(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemSlaOut:
        """The record's SLA: the policy, why it applies, each target and its due date."""
        return WorkItemSlaOut.of(await service.sla_panel(session, subject, wtype, record_id))

    @router.get("/{record_id}/history", summary="History")
    async def history(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        record_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        cursor: Annotated[
            str | None, Query(description="next_cursor of the previous page.")
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        actors: Annotated[Actors, Query(description="people, automation or all")] = "all",
    ) -> WorkItemHistoryOut:
        """Every save, newest first, in true order: who, when, from where, what, why."""
        entries, next_cursor, names, people = await service.history(
            session, subject, wtype, record_id, before=_cursor(cursor), limit=limit, actors=actors
        )
        audit = (
            await entries_for_changes(session, [e.change_id for e in entries])
            if subject.holds("audit.view")
            else {}
        )
        return WorkItemHistoryOut(
            items=[WorkItemHistoryEntryOut.of(e, names, audit) for e in entries],
            next_cursor=None if next_cursor is None else _cursor_text(*next_cursor),
            people=_people(people),
        )

    add_record_routes(router, wtype)
    add_parts_routes(router, wtype)
    # REQ-AST-025: assets on incidents and requests (the forms and the e-mail ask for them).
    if wtype.code in _WITH_ASSETS:
        add_asset_routes(router, wtype)
    return router
