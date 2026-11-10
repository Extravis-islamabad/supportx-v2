"""Releases' stage model: the seeds of file 06 Appendix A (WP-058a; REQ-REL-014..017). Pure.

Seed data, never fixed behaviour: a tenant's copy is made on first use and is editable later
(REQ-REL-015). Status codes carry their stage (`build_in_progress`), and the labels give the
plain name. Approval outcomes (plan approved or rejected, acceptance accepted or rejected) are
set by the approvals code only (`system`).
"""

import re
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


class ReleaseRisk(StrEnum):
    """A release's risk (REQ-REL-004): a short list, set by hand or by an assessment later."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Appendix A's release types (with colours) and release reasons, seeded per tenant (REQ-REL-003,
# REQ-REL-005); admins add, rename, recolour and retire them like any pick list.
RELEASE_TYPES: tuple[tuple[str, str], ...] = (
    ("major", "#CF1322"),
    ("minor", "#1677FF"),
    ("emergency", "#D48806"),
    ("maintenance", "#389E0D"),
)
RELEASE_REASONS = ("new_features", "fixes", "security", "compliance")
# Downtime kinds (REQ-REL-027), a pick list of the type's own.
DOWNTIME_KINDS = ("full_outage", "partial_outage", "maintenance_window")

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
    path: str | None = None,
) -> StatusTransitionDef:
    return StatusTransitionDef(
        source, target, REQUIRED if reason else ReasonMode.NONE, permission=permission, path=path
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
    # REQ-REL-012 AC2: an emergency release always gets its review, so only the default path may
    # close straight after a rollback.
    _t("deployment_rolled_back", "closure_closed", path=DEFAULT_PATH),
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


# --- a release's own fields (REQ-REL-002..005) ----------------------------------------------------

DETAIL_FIELDS = (
    "release_type",
    "risk",
    "release_version",
    "build_ref",
    "release_reason",
    "release_notes",
    "scheduled_start",
    "scheduled_end",
    "actual_start",
    "actual_end",
    "release_manager_id",
    "release_engineer_id",
)
# Dates are never copied (REQ-REL-009).
DATE_FIELDS = ("scheduled_start", "scheduled_end", "actual_start", "actual_end")
VERSION_MAX = 60
BUILD_REF_MAX = 200
# Searchable and shown in lists (REQ-REL-005 AC1): kept on the record's search text.
SEARCHED_FIELDS = ("release_version", "build_ref")


def detail_problems(merged: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(field, problem code) pairs of a release's fields after an edit (values merged)."""
    problems: list[tuple[str, str]] = []
    for name, limit in (("release_version", VERSION_MAX), ("build_ref", BUILD_REF_MAX)):
        value = merged.get(name)
        if value is not None and len(value) > limit:
            problems.append((name, "value_too_long"))
    risk = merged.get("risk")
    if risk is not None and risk not in {r.value for r in ReleaseRisk}:
        problems.append(("risk", "invalid_choice"))
    # REQ-REL-002 AC2: an end before its start is refused, on the field that is wrong.
    for start, end in (("scheduled_start", "scheduled_end"), ("actual_start", "actual_end")):
        began, ended = merged.get(start), merged.get(end)
        if began is not None and ended is not None and ended < began:
            problems.append((end, "end_before_start"))
    return problems


def search_terms(details: Mapping[str, Any]) -> str:
    """The release's words for search: version and build reference.

    Each value also goes in split at its separators: search reads `4.2.0` as the words 4, 2 and
    0, while the text index keeps `4.2.0` as one token.
    """
    values = [str(details[n]) for n in SEARCHED_FIELDS if details.get(n)]
    return " ".join(part for v in values for part in (v, re.sub(r"[\W_]+", " ", v).strip()))


# --- roles, plan sections, stage outcomes (WP-058a s4; REQ-REL-023..028) -------------------------

# Appendix A's release roles, each held by one person (REQ-REL-023); seeded per tenant, editable.
RELEASE_ROLES = (
    "requester",
    "release_manager",
    "release_engineer",
    "development_lead",
    "qa_lead",
    "uat_owner",
    "reviewer",
)
# Appendix A's stage approvals (REQ-REL-031): the plan by the release manager, acceptance by the
# acceptance (UAT) owner, one level each; admins add levels, people, groups and roles.
STAGE_APPROVALS: Mapping[str, Mapping[str, Any]] = {
    "planning": {
        "raised_by": "planning_waiting_approval",
        "approved": "planning_plan_approved",
        "rejected": "planning_plan_rejected",
        "levels": [{"rule": "any", "approvers": [{"role": "release_manager"}]}],
    },
    "acceptance_testing": {
        "raised_by": "acceptance_in_progress",
        "approved": "acceptance_accepted",
        "rejected": "acceptance_rejected",
        "levels": [{"rule": "any", "approvers": [{"role": "uat_owner"}]}],
    },
}
# The planning stage's rich-text sections (REQ-REL-025), each with its own version and history.
PLAN_SECTIONS = (
    "impact",
    "rollout",
    "backout",
    # The post-release review (REQ-REL-030): findings, and what went well and what did not.
    "review_findings",
    "review_went_well",
    "review_went_badly",
)
# Stages that record an outcome, notes, issues and evidence (REQ-REL-028).
OUTCOME_STAGES = frozenset(
    {"build", "testing", "acceptance_testing", "deployment", "training", "review"}
)


class DowntimePhase(StrEnum):
    """Whether a downtime window is planned or happened (REQ-REL-027)."""

    PLANNED = "planned"
    ACTUAL = "actual"


class StageOutcome(StrEnum):
    """How a stage went (REQ-REL-028)."""

    PASSED = "passed"
    FAILED = "failed"
    PARTLY_DONE = "partly_done"
    # The review stage's overall result (REQ-REL-030): successful, with issues, or failed.
    SUCCESSFUL = "successful"
    SUCCESSFUL_WITH_ISSUES = "successful_with_issues"
    # A change's implementation may also be backed out (REQ-CHG-032).
    BACKED_OUT = "backed_out"


REVIEW_OUTCOMES = frozenset(
    {StageOutcome.SUCCESSFUL, StageOutcome.SUCCESSFUL_WITH_ISSUES, StageOutcome.FAILED}
)
WORK_OUTCOMES = frozenset({StageOutcome.PASSED, StageOutcome.FAILED, StageOutcome.PARTLY_DONE})


def outcomes_for(stage: str) -> frozenset[str]:
    """The outcome codes a stage takes: the review its result, the others how the work went."""
    return frozenset(o.value for o in (REVIEW_OUTCOMES if stage == "review" else WORK_OUTCOMES))


def outcome_problems(
    stage: str, merged: Mapping[str, Any], allowed: frozenset[str] | None = None
) -> list[tuple[str, str]]:
    """(field, code) pairs of a stage's outcome after an edit (values merged).

    `allowed`: the type's own outcomes for this stage (changes); None: the release's.
    """
    problems: list[tuple[str, str]] = []
    outcome = merged.get("outcome")
    if allowed is not None:
        if outcome is not None and outcome not in allowed:
            problems.append(("outcome", "invalid_choice"))
    elif outcome is not None and stage not in OUTCOME_STAGES:
        problems.append(("outcome", "not_allowed"))
    elif outcome is not None and outcome not in outcomes_for(stage):
        problems.append(("outcome", "invalid_choice"))
    # REQ-REL-028 AC1: a failed outcome says what went wrong.
    if outcome == StageOutcome.FAILED and not (merged.get("issues") or "").strip():
        problems.append(("issues", "required"))
    for start, end in (("scheduled_start", "scheduled_end"), ("actual_start", "actual_end")):
        began, ended = merged.get(start), merged.get(end)
        if began is not None and ended is not None and ended < began:
            problems.append((end, "end_before_start"))
    return problems
