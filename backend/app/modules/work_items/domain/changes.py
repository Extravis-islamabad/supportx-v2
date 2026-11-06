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
# Stages that record an outcome (REQ-CHG-031): the implementation's completed, backed out or failed.
OUTCOME_STAGES = frozenset({"implementation", "acceptance_testing", "deployment", "review"})
