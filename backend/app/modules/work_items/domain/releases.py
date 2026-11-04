"""Releases' stage model: the seeds of file 06 Appendix A (WP-058a; REQ-REL-014..017). Pure.

Seed data, never fixed behaviour: a tenant's copy is made on first use and is editable later
(REQ-REL-015). Status codes carry their stage (`build_in_progress`), and the labels give the
plain name. Approval outcomes (plan approved or rejected, acceptance accepted or rejected) are
set by the approvals code only (`system`).
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

OPEN, PAUSED, RESOLVED = StatusCategory.OPEN, StatusCategory.PAUSED, StatusCategory.RESOLVED
CLOSED, CANCELED = StatusCategory.CLOSED, StatusCategory.CANCELED

STAGES = (
    "submission",
    "planning",
    "build",
    "testing",
    "acceptance_testing",
    "deployment",
    "training",
    "review",
    "closure",
)
EMERGENCY_PATH = "emergency"

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
    _s("submission_requested", "submission", OPEN, _BLUE),
    _s("submission_accepted", "submission", OPEN, _GREEN, completing=True),
    _s("submission_rejected", "submission", CANCELED, _RED),
    _s("planning_in_planning", "planning", OPEN, _BLUE),
    _s("planning_waiting_approval", "planning", PAUSED, _AMBER),
    _s("planning_plan_approved", "planning", OPEN, _GREEN, completing=True, system=True),
    _s("planning_plan_rejected", "planning", OPEN, _RED, system=True),
    _s("build_in_progress", "build", OPEN, _BLUE),
    _s("build_completed", "build", OPEN, _GREEN, completing=True),
    _s("build_backed_out", "build", OPEN, _RED),
    _s("testing_in_progress", "testing", OPEN, _BLUE),
    _s("testing_passed", "testing", OPEN, _GREEN, completing=True),
    _s("testing_failed", "testing", OPEN, _RED),
    _s("acceptance_in_progress", "acceptance_testing", OPEN, _BLUE),
    _s("acceptance_accepted", "acceptance_testing", OPEN, _GREEN, completing=True, system=True),
    _s("acceptance_rejected", "acceptance_testing", OPEN, _RED, system=True),
    _s("deployment_scheduled", "deployment", OPEN, _BLUE),
    _s("deployment_in_progress", "deployment", OPEN, _BLUE),
    _s("deployment_deployed", "deployment", RESOLVED, _GREEN, completing=True),
    _s("deployment_failed", "deployment", OPEN, _RED),
    _s("deployment_rolled_back", "deployment", OPEN, _AMBER),
    _s("training_in_progress", "training", OPEN, _BLUE),
    _s("training_completed", "training", RESOLVED, _GREEN, completing=True),
    _s("review_in_progress", "review", RESOLVED, _BLUE),
    _s("review_completed", "review", RESOLVED, _GREEN, completing=True),
    _s("closure_closed", "closure", CLOSED, _GREY),
    _s("closure_canceled", "closure", CANCELED, _GREY),
)

REQUIRED = ReasonMode.REQUIRED


def _t(
    source: str,
    target: str,
    *,
    reason: bool = False,
    permission: str | None = None,
) -> StatusTransitionDef:
    return StatusTransitionDef(
        source, target, REQUIRED if reason else ReasonMode.NONE, permission=permission
    )


_MOVES = (
    _t("submission_requested", "submission_accepted"),
    _t("submission_requested", "submission_rejected", reason=True),
    _t("planning_in_planning", "planning_waiting_approval"),
    _t("planning_waiting_approval", "planning_plan_approved"),
    _t("planning_waiting_approval", "planning_plan_rejected"),
    _t("planning_plan_rejected", "planning_in_planning"),  # a new planning round
    _t("build_in_progress", "build_completed"),
    _t("build_in_progress", "build_backed_out", reason=True),
    _t("build_backed_out", "build_in_progress"),
    _t("testing_in_progress", "testing_passed"),
    _t("testing_in_progress", "testing_failed", reason=True),
    _t("testing_failed", "build_in_progress"),  # back to build
    _t("acceptance_in_progress", "acceptance_accepted"),
    _t("acceptance_in_progress", "acceptance_rejected"),
    _t("acceptance_rejected", "build_in_progress"),  # back to build
    _t("deployment_scheduled", "deployment_in_progress"),
    _t("deployment_in_progress", "deployment_deployed"),
    _t("deployment_in_progress", "deployment_failed", reason=True),
    _t("deployment_failed", "deployment_rolled_back", reason=True),
    _t("deployment_rolled_back", "build_in_progress"),
    _t("deployment_rolled_back", "closure_closed"),
    _t("training_in_progress", "training_completed"),
    _t("review_in_progress", "review_completed"),
    # Reopen a closed release into review: its own permission and a reason.
    _t("closure_closed", "review_in_progress", reason=True, permission="reopen"),
)
# Cancel from any status before closure: a reason, and the cancel permission.
_CANCELS = tuple(
    _t(s.code, "closure_canceled", reason=True, permission="cancel")
    for s in STATUSES
    if s.stage != "closure" and s.category not in {CLOSED, CANCELED}
)

RELEASE_MODEL = StageModel(
    stages=tuple(StageDef(code) for code in STAGES),
    statuses=STATUSES,
    paths=(
        PathDef(DEFAULT_PATH, STAGES),
        PathDef(
            EMERGENCY_PATH,
            ("submission", "build", "testing", "deployment", "review", "closure"),
        ),
    ),
    transitions=_MOVES + _CANCELS,
)
