"""Changes' stage model: the seeds of file 05 Appendix A (WP-045a S1; REQ-CHG-023..027). Pure.

Seed data, never fixed behaviour: a tenant's copy is made on first use and is editable later
(D-041). Status codes carry their stage (`cab_awaiting`), and the labels give the plain name.
Approval outcomes (accepted, plan approved, CAB approved, and their rejections) are set by the
approvals code only (`system`).

Paths per change type (REQ-CHG-027): standard (review optional), minor, normal (the default),
major (all eight stages) and emergency (an emergency CAB, a mandatory review). A move into a
stage the record's path does not have is never offered (StageModel.moves_from), so one list of
moves serves every path.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from app.modules.work_items.domain.lifecycle import ReasonMode, StatusCategory
from app.modules.work_items.domain.stages import (
    DEFAULT_PATH,
    PathDef,
    SetBy,
    StageDef,
    StagedStatusDef,
    StageModel,
    StatusTransitionDef,
)

OPEN, PAUSED = StatusCategory.OPEN, StatusCategory.PAUSED
CLOSED, CANCELED = StatusCategory.CLOSED, StatusCategory.CANCELED

STAGES = (
    "submission",
    "planning",
    "cab_review",
    "implementation",
    "acceptance_testing",
    "deployment",
    "review",
    "closure",
)
# The change types' paths (Appendix A); the normal path is the model's default.
STANDARD_PATH, MINOR_PATH, MAJOR_PATH, EMERGENCY_PATH = "standard", "minor", "major", "emergency"

_BLUE, _AMBER, _GREEN, _RED, _GREY = "#1677FF", "#D48806", "#389E0D", "#CF1322", "#595959"


def _s(  # noqa: PLR0913 - one status, explicit
    code: str,
    stage: str,
    category: StatusCategory,
    colour: str,
    *,
    completing: bool = False,
    system: bool = False,
) -> StagedStatusDef:
    return StagedStatusDef(
        code, stage, category, colour, completing, SetBy.SYSTEM if system else SetBy.PERSON
    )


STATUSES = (
    _s("submission_submitted", "submission", OPEN, _BLUE),
    _s("submission_more_info", "submission", PAUSED, _AMBER),
    _s("submission_awaiting_acceptance", "submission", OPEN, _AMBER),
    _s("submission_accepted", "submission", OPEN, _GREEN, completing=True, system=True),
    _s("submission_rejected", "submission", CLOSED, _RED, system=True),
    _s("planning_planning", "planning", OPEN, _BLUE),
    _s("planning_awaiting_approval", "planning", OPEN, _AMBER),
    _s("planning_plan_approved", "planning", OPEN, _GREEN, completing=True, system=True),
    _s("planning_plan_rejected", "planning", OPEN, _RED, system=True),
    _s("cab_awaiting", "cab_review", OPEN, _AMBER),
    _s("cab_clarification", "cab_review", PAUSED, _AMBER),
    _s("cab_approved", "cab_review", OPEN, _GREEN, completing=True, system=True),
    _s("cab_rejected", "cab_review", CLOSED, _RED, system=True),
    _s("implementation_scheduled", "implementation", OPEN, _BLUE),
    _s("implementation_in_progress", "implementation", OPEN, _BLUE),
    _s("implementation_implemented", "implementation", OPEN, _GREEN, completing=True),
    _s("implementation_backed_out", "implementation", OPEN, _AMBER),
    _s("implementation_failed", "implementation", OPEN, _RED),
    _s("acceptance_testing", "acceptance_testing", OPEN, _BLUE),
    _s("acceptance_passed", "acceptance_testing", OPEN, _GREEN, completing=True),
    _s("acceptance_failed", "acceptance_testing", OPEN, _RED),
    _s("deployment_deploying", "deployment", OPEN, _BLUE),
    _s("deployment_deployed", "deployment", OPEN, _GREEN, completing=True),
    _s("deployment_failed", "deployment", OPEN, _RED),
    _s("review_in_review", "review", OPEN, _BLUE),
    _s("review_complete", "review", OPEN, _GREEN, completing=True),
    _s("closure_closed", "closure", CLOSED, _GREY),
    _s("closure_canceled", "closure", CANCELED, _GREY),
)

REQUIRED = ReasonMode.REQUIRED


def _t(
    source: str, target: str, *, reason: bool = False, permission: str | None = None
) -> StatusTransitionDef:
    return StatusTransitionDef(
        source, target, REQUIRED if reason else ReasonMode.NONE, permission=permission
    )


_MOVES = (
    # A standard change is approved at creation (REQ-CHG-006): the system's move only.
    _t("submission_submitted", "submission_accepted"),
    _t("submission_submitted", "submission_more_info", reason=True),
    _t("submission_submitted", "submission_awaiting_acceptance"),
    _t("submission_more_info", "submission_submitted"),
    _t("submission_awaiting_acceptance", "submission_accepted"),  # approval only
    _t("submission_awaiting_acceptance", "submission_rejected"),  # approval only
    _t("submission_rejected", "closure_closed"),
    _t("planning_planning", "planning_awaiting_approval"),
    _t("planning_awaiting_approval", "planning_plan_approved"),  # approval only
    _t("planning_awaiting_approval", "planning_plan_rejected"),  # approval only
    _t("planning_plan_rejected", "planning_planning"),  # re-plan
    _t("cab_awaiting", "cab_clarification", reason=True),
    _t("cab_awaiting", "cab_approved"),  # approval only
    _t("cab_awaiting", "cab_rejected"),  # approval only
    _t("cab_clarification", "cab_awaiting"),
    _t("cab_rejected", "planning_planning"),  # re-plan, on paths with planning
    _t("cab_rejected", "closure_closed"),
    _t("implementation_scheduled", "implementation_in_progress"),
    _t("implementation_in_progress", "implementation_implemented"),
    _t("implementation_in_progress", "implementation_backed_out", reason=True),
    _t("implementation_in_progress", "implementation_failed", reason=True),
    # Backed out, failed or a failed deployment go to the review (REQ-CHG-031, -090).
    _t("implementation_backed_out", "review_in_review"),
    _t("implementation_failed", "review_in_review"),
    _t("acceptance_testing", "acceptance_passed"),
    _t("acceptance_testing", "acceptance_failed", reason=True),
    _t("acceptance_failed", "implementation_in_progress"),
    _t("deployment_deploying", "deployment_deployed"),
    _t("deployment_deploying", "deployment_failed", reason=True),
    _t("deployment_failed", "review_in_review"),
    _t("review_in_review", "review_complete"),
)
# Cancel from any status before implementation is in progress: a reason, and the cancel right
# (owner or change manager, REQ-CHG-033).
_BEFORE_WORK = frozenset({"submission", "planning", "cab_review"})
_CANCELS = tuple(
    _t(s.code, "closure_canceled", reason=True, permission="cancel")
    for s in STATUSES
    if (s.stage in _BEFORE_WORK or s.code == "implementation_scheduled")
    and s.category not in {CLOSED, CANCELED}
)

_ALL = STAGES
CHANGE_MODEL = StageModel(
    stages=tuple(StageDef(code) for code in STAGES),
    statuses=STATUSES,
    paths=(
        PathDef(
            DEFAULT_PATH,  # normal
            ("submission", "planning", "cab_review", "implementation", "review", "closure"),
        ),
        PathDef(
            STANDARD_PATH,
            ("submission", "implementation", "review", "closure"),
            optional=frozenset({"review"}),
        ),
        PathDef(MINOR_PATH, ("submission", "planning", "implementation", "review", "closure")),
        PathDef(MAJOR_PATH, _ALL),
        PathDef(
            EMERGENCY_PATH, ("submission", "cab_review", "implementation", "review", "closure")
        ),
    ),
    transitions=_MOVES + _CANCELS,
)

# Appendix A's change roles (REQ-CHG-034): seeded per tenant, editable; who holds them decides
# stage access (ADR-041's StageGuard) and approvals. The owner is the record's technician.
CHANGE_ROLES = (
    "requester",
    "change_owner",
    "change_manager",
    "line_manager",
    "implementer",
    "reviewer",
)
# The plan sections (REQ-CHG-013, -016, -017) on #219's plan sections, each with its history.
PLAN_SECTIONS = ("impact", "rollout", "backout", "test")
# Stages that record an outcome (REQ-CHG-031, -032), and the outcomes each takes: the
# implementation successful, successful with issues, backed out or failed; tests passed or
# failed; a deployment as a release's; the review's overall result.
IMPLEMENTATION = "implementation"
STAGE_OUTCOMES: Mapping[str, frozenset[str]] = {
    IMPLEMENTATION: frozenset({"successful", "successful_with_issues", "backed_out", "failed"}),
    "acceptance_testing": frozenset({"passed", "failed"}),
    "deployment": frozenset({"passed", "failed", "partly_done"}),
    "review": frozenset({"successful", "successful_with_issues", "failed"}),
}
OUTCOME_STAGES = frozenset(STAGE_OUTCOMES)
# Appendix A's stage approvals, the first cut (REQ-CHG-042): acceptance by the line manager,
# the plan and the CAB review by the change manager, one level each. CABs (named boards, the
# majority and the chair) and the risk rows come with WP-045b; admins add levels any time.
STAGE_APPROVALS: Mapping[str, Mapping[str, Any]] = {
    "submission": {
        "raised_by": "submission_awaiting_acceptance",
        "approved": "submission_accepted",
        "rejected": "submission_rejected",
        "levels": [{"rule": "any", "approvers": [{"role": "line_manager"}]}],
    },
    "planning": {
        "raised_by": "planning_awaiting_approval",
        "approved": "planning_plan_approved",
        "rejected": "planning_plan_rejected",
        "levels": [{"rule": "any", "approvers": [{"role": "change_manager"}]}],
    },
    "cab_review": {
        "raised_by": "cab_awaiting",
        "approved": "cab_approved",
        "rejected": "cab_rejected",
        "levels": [{"rule": "any", "approvers": [{"role": "change_manager"}]}],
    },
}


# --- a change's own fields (REQ-CHG-005, -011) --------------------------------------------------

# Appendix A's change types with their colour and model (REQ-CHG-005), seeded per tenant; each
# type's path is the model's (WP-045a D2 binds them).
CHANGE_TYPES: tuple[tuple[str, str], ...] = (
    ("standard", "#389E0D"),
    ("minor", "#1677FF"),
    ("normal", "#08979C"),
    ("major", "#D46B08"),
    ("emergency", "#CF1322"),
)
CHANGE_MODELS: Mapping[str, str] = {
    "standard": "standard",
    "minor": "normal",
    "normal": "normal",
    "major": "normal",
    "emergency": "emergency",
}
# Appendix A's reasons for change (REQ-CHG-011), a translatable, reportable pick list.
CHANGE_REASONS = (
    "security_fix",
    "vulnerability_patch",
    "new_service_or_feature",
    "capacity_or_performance",
    "compliance_requirement",
    "end_of_life",
    "fault_fix",
    "cost_reduction",
)
DETAIL_FIELDS = ("change_type", "change_reason")


class ChangeModel(StrEnum):
    """What a change type behaves as (REQ-CHG-005): pre-approved, assessed, or fast-tracked."""

    STANDARD = "standard"
    NORMAL = "normal"
    EMERGENCY = "emergency"


# Each model's path when the template sets none (REQ-CHG-005, -027); the seeded types keep their
# own (minor and major are normal changes on paths of their own).
MODEL_PATHS: Mapping[ChangeModel, str] = {
    ChangeModel.STANDARD: STANDARD_PATH,
    ChangeModel.NORMAL: DEFAULT_PATH,
    ChangeModel.EMERGENCY: EMERGENCY_PATH,
}
TYPE_PATHS: Mapping[str, str] = {"minor": MINOR_PATH, "major": MAJOR_PATH}


def model_of(change_type: str, attributes: Mapping[str, Any] | None) -> ChangeModel:
    """A type's model: an admin's type says it (`attributes.model`), a seeded one has its own."""
    given = (attributes or {}).get("model")
    if given in {m.value for m in ChangeModel}:
        return ChangeModel(given)
    return ChangeModel(CHANGE_MODELS.get(change_type, ChangeModel.NORMAL.value))


def path_of(change_type: str, model: ChangeModel) -> str:
    """The path of a change of this type when its template names none."""
    return TYPE_PATHS.get(change_type) or MODEL_PATHS[model]


# A standard change's status on creation (REQ-CHG-006 AC1): accepted, which completes submission.
PRE_APPROVED = "submission_accepted"


# Completing implementation needs its outcome, and the status says the same (REQ-CHG-032 AC1).
OUTCOME_OF_STATUS: Mapping[str, frozenset[str]] = {
    "implementation_implemented": frozenset({"successful", "successful_with_issues"}),
    "implementation_backed_out": frozenset({"backed_out"}),
    "implementation_failed": frozenset({"failed"}),
}


def outcome_refusal(target: str, outcome: str | None) -> tuple[str, dict[str, str]] | None:
    """Why a move to `target` is refused for the implementation's outcome, or None."""
    allowed = OUTCOME_OF_STATUS.get(target)
    if allowed is None:
        return None
    if outcome is None:
        return "outcome_required", {"stage": IMPLEMENTATION}
    if outcome not in allowed:
        return "outcome_mismatch", {"stage": IMPLEMENTATION, "outcome": outcome}
    return None
