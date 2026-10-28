"""Work item domain rules without I/O (WP-020). Test names cite docs/specs/parity/01 criteria."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.modules.work_items.domain.classification import (
    DEFAULT_MATRIX,
    SCALE_CODES,
    Impact,
    MatrixError,
    Priority,
    PrioritySource,
    Scale,
    Urgency,
    check_matrix,
    compute_priority,
)
from app.modules.work_items.domain.lifecycle import (
    DEFAULT_STATUSES,
    DEFAULT_TRANSITIONS,
    USER_ACTIONS,
    DefaultStatus,
    Lifecycle,
    LifecycleError,
    PauseClock,
    ReasonList,
    ReasonMode,
    StatusCategory,
    StatusDef,
    TransitionDef,
    WorkItemAction,
    after_assignment,
    default_lifecycle,
    move_pause_clock,
    reason_problems,
)
from app.modules.work_items.domain.types import (
    FIELD_PROBLEMS,
    INCIDENT,
    TYPES,
    Channel,
    WorkItemType,
    WorkItemTypeCode,
    channel_problems,
    clean_subject,
    clean_tags,
    parse_display_id,
    prefix_problems,
)
from app.shared.domain import InvalidTransition

S = DefaultStatus
A = WorkItemAction

# Appendix A, "Allowed transitions" (user actions only; assign/unassign are automatic).
APPENDIX_A: dict[str, set[WorkItemAction]] = {
    S.NEW: {A.START_WORK, A.RESOLVE, A.CANCEL},
    S.ASSIGNED: {A.START_WORK, A.WAIT_REQUESTER, A.WAIT_THIRD_PARTY, A.RESOLVE, A.CANCEL},
    S.IN_PROGRESS: {A.WAIT_REQUESTER, A.WAIT_THIRD_PARTY, A.RESOLVE, A.CANCEL},
    S.AWAITING_REQUESTER: {A.RESUME, A.RESOLVE, A.CANCEL},
    S.AWAITING_THIRD_PARTY: {A.RESUME, A.RESOLVE, A.CANCEL},
    S.RESOLVED: {A.CLOSE, A.REOPEN},
    S.CLOSED: {A.REOPEN},
    S.CANCELED: {A.UNDO_CANCEL},
    S.MERGED: set(),
}


def test_req_inc_045_ac2_only_appendix_a_transitions() -> None:
    lifecycle = default_lifecycle()
    for status, expected in APPENDIX_A.items():
        assert set(lifecycle.actions_from(status)) == expected, status


def test_req_wi_010_ac2_action_order_fixed_across_statuses() -> None:
    lifecycle = default_lifecycle()
    order = list(USER_ACTIONS)
    for status in lifecycle.statuses:
        offered = lifecycle.actions_from(status)
        assert offered == [a for a in order if a in offered]  # always the global order


def test_req_inc_044_ac1_every_status_has_one_category() -> None:
    by_code = {s.code: s.category for s in DEFAULT_STATUSES}
    assert by_code[S.IN_PROGRESS] == StatusCategory.OPEN  # work in progress never pauses the SLA
    assert {by_code[S.AWAITING_REQUESTER], by_code[S.AWAITING_THIRD_PARTY]} == {
        StatusCategory.PAUSED
    }
    assert by_code[S.MERGED] == StatusCategory.CLOSED


def test_req_inc_046_unknown_or_system_moves_are_refused() -> None:
    lifecycle = default_lifecycle()
    with pytest.raises(InvalidTransition):
        lifecycle.transition(S.CLOSED, A.RESOLVE)
    assert lifecycle.target(S.NEW, A.ASSIGN, before_cancel=None) == S.ASSIGNED
    # undo_cancel returns to where it was; without a record of that, it cannot run.
    assert lifecycle.target(S.CANCELED, A.UNDO_CANCEL, before_cancel=S.IN_PROGRESS) == S.IN_PROGRESS
    with pytest.raises(InvalidTransition):
        lifecycle.target(S.CANCELED, A.UNDO_CANCEL, before_cancel=None)


@pytest.mark.parametrize(
    ("transitions", "message"),
    [
        ([TransitionDef("nowhere", A.RESOLVE, S.RESOLVED)], "unknown status"),
        ([TransitionDef(S.NEW, A.RESOLVE, "nowhere")], "unknown status"),
        ([TransitionDef(S.NEW, A.RESOLVE, None)], "only undo_cancel"),
        ([TransitionDef(S.NEW, A.RESOLVE, S.MERGED)], "system only"),
        (
            [TransitionDef(S.NEW, A.RESOLVE, S.RESOLVED, ReasonMode.NONE, ReasonList.PAUSE)],
            "asks for no reason",
        ),
        ([TransitionDef(S.NEW, A.RESOLVE, S.RESOLVED)] * 2, "defined twice"),
    ],
)
def test_req_wi_009_ac4_broken_lifecycles_are_refused_with_a_reason(
    transitions: list[TransitionDef], message: str
) -> None:
    with pytest.raises(LifecycleError, match=message):
        Lifecycle.build(DEFAULT_STATUSES, transitions)


def test_req_inc_047_ac1_pause_and_cancel_need_a_reason() -> None:
    lifecycle = default_lifecycle()
    wait = lifecycle.transition(S.IN_PROGRESS, A.WAIT_REQUESTER)
    codes = ["more_information", "other"]
    assert reason_problems(wait, code=None, text=None, allowed_codes=codes) == [
        ("reason_code", "required")
    ]
    assert reason_problems(wait, code="more_information", text=None, allowed_codes=codes) == []
    assert reason_problems(wait, code="other", text=" ", allowed_codes=codes) == [
        ("reason_text", "required")
    ]
    assert reason_problems(wait, code="made_up", text=None, allowed_codes=codes) == [
        ("reason_code", "invalid_choice")
    ]
    start = lifecycle.transition(S.ASSIGNED, A.START_WORK)
    assert reason_problems(start, code="x", text="why", allowed_codes=[]) == [
        ("reason_code", "not_allowed"),
        ("reason_text", "not_allowed"),
    ]
    undo = lifecycle.transition(S.CANCELED, A.UNDO_CANCEL)
    assert reason_problems(undo, code=None, text=None, allowed_codes=[]) == []
    assert reason_problems(undo, code=None, text="x" * 501, allowed_codes=[]) == [
        ("reason_text", "value_too_long")
    ]


def test_req_inc_050_assignment_moves_only_from_new_and_assigned() -> None:
    lifecycle = default_lifecycle()
    assert after_assignment(lifecycle, S.NEW, had_technician=False, has_technician=True) == A.ASSIGN
    assert (
        after_assignment(lifecycle, S.ASSIGNED, had_technician=True, has_technician=False)
        == A.UNASSIGN
    )
    # In progress stays in progress (REQ-INC-050 AC4); a group-only change moves nothing.
    assert (
        after_assignment(lifecycle, S.IN_PROGRESS, had_technician=False, has_technician=True)
        is None
    )
    assert after_assignment(lifecycle, S.NEW, had_technician=False, has_technician=False) is None


def test_req_inc_044_ac2_pause_clock_adds_up() -> None:
    start = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
    clock = PauseClock(None, 0)
    clock = move_pause_clock(clock, old=StatusCategory.OPEN, new=StatusCategory.PAUSED, now=start)
    assert clock == PauseClock(start, 0)
    later = start + timedelta(minutes=90)
    clock = move_pause_clock(clock, old=StatusCategory.PAUSED, new=StatusCategory.OPEN, now=later)
    assert clock == PauseClock(None, 5400)
    # Moving between two paused statuses keeps the running pause.
    paused = move_pause_clock(clock, old=StatusCategory.OPEN, new=StatusCategory.PAUSED, now=later)
    same = move_pause_clock(
        paused, old=StatusCategory.PAUSED, new=StatusCategory.PAUSED, now=later + timedelta(hours=1)
    )
    assert same == paused


def test_req_inc_008_ac2_values_ranked_on_single_scales() -> None:
    assert list(SCALE_CODES[Scale.IMPACT]) == [
        "one_person",
        "team",
        "department_or_site",
        "organisation",
    ]
    assert list(SCALE_CODES[Scale.URGENCY]) == ["low", "medium", "high", "critical"]
    # No value appears on two scales (no "high" impact next to "affects user").
    assert not set(Impact) & set(Urgency)


def test_req_inc_009_ac1_default_matrix_is_full() -> None:
    check_matrix(DEFAULT_MATRIX)
    assert len(DEFAULT_MATRIX) == 16
    broken = dict(DEFAULT_MATRIX)
    del broken[("team", "low")]
    with pytest.raises(MatrixError):
        check_matrix(broken)


def test_req_inc_009_ac2_matrix_gives_p1_for_organisation_critical() -> None:
    computed = compute_priority("organisation", "critical", DEFAULT_MATRIX)
    assert (computed.priority, computed.source) == (Priority.P1, PrioritySource.MATRIX)
    assert compute_priority("one_person", "low", DEFAULT_MATRIX).priority == Priority.P4


def test_req_inc_011_ac1_unknown_impact_and_urgency_use_the_default() -> None:
    computed = compute_priority(None, None, DEFAULT_MATRIX, "p3")
    assert (computed.priority, computed.source) == ("p3", PrioritySource.DEFAULT)
    # Only urgency known: the lowest impact stands in.
    assert compute_priority(None, "critical", DEFAULT_MATRIX).priority == "p3"


def test_type_fields_and_values() -> None:
    assert clean_subject("  Mail   is down ") == ("Mail is down", [])
    assert clean_subject("   ")[1] == ["required"]
    assert clean_subject("x" * 251)[1] == ["value_too_long"]
    assert clean_tags(["vpn", "VPN", " wifi "]) == (["vpn", "wifi"], [])
    assert clean_tags(["<script>"])[1] == ["invalid_tag"]
    assert clean_tags([f"t{i}" for i in range(21)])[1] == ["too_many_items"]
    assert prefix_problems("INC") == []
    assert prefix_problems("inc") == ["invalid_prefix"]
    assert prefix_problems("TOOLONGX") == ["invalid_prefix"]


def test_req_inc_005_ac3_only_phone_and_walk_up_are_chosen() -> None:
    assert channel_problems(Channel.PHONE) == []
    assert channel_problems(Channel.WALK_UP) == []
    assert channel_problems(None) == []
    for reserved in (Channel.EMAIL, Channel.MONETX, Channel.PORTAL, Channel.API):
        assert channel_problems(reserved) == ["channel_reserved"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("INC-12", ("INC", 12)),
        ("inc-12", ("INC", 12)),
        (" 12 ", (None, 12)),
        ("abc", (None, None)),
    ],
)
def test_req_wi_002_ac5_display_id_forms(
    value: str, expected: tuple[str | None, int | None]
) -> None:
    assert parse_display_id(value, "INC") == expected


def test_req_wi_001_ac2_a_type_is_a_registry_entry() -> None:
    """A new type needs a registry entry, not engine code: prefix, counter, permissions."""
    problem = WorkItemType(
        code=WorkItemTypeCode.PROBLEM,
        path="problems",
        default_prefix="PRB",
        feature="problem",
        permission_prefix="problems",
    )
    assert problem.counter_key == "WI_PROBLEM"
    assert problem.permission("view") == "problems.view"
    assert Lifecycle.build(problem.statuses, problem.transitions).statuses  # default life cycle
    assert TYPES[WorkItemTypeCode.INCIDENT] is INCIDENT
    assert INCIDENT.counter_key == "WI_INCIDENT"


def test_every_field_problem_code_is_registered_for_labels() -> None:
    """Field codes built from (field, code) pairs must be in FIELD_PROBLEMS (the label check)."""
    found: set[str] = set()
    pair = re.compile(r'\(\s*"[a-z_]+",\s*"([a-z_]+)"\s*\)')
    keyword = re.compile(r'field_code="([a-z_]+)"')
    for source in (Path(__file__).parents[1]).rglob("*.py"):
        if "tests" in source.parts:
            continue
        text = source.read_text(encoding="utf-8")
        found |= set(pair.findall(text)) | set(keyword.findall(text))
    # Pairs that are not field problems: unit kinds, role scopes, field-name tuples, notification
    # recipient kinds (service/notifications.py).
    found -= {
        "site",
        "group",
        "all",
        "own",
        "on_behalf_of_id",
        "technician_id",
        "followers",
        "close_requires",
    }
    assert found <= FIELD_PROBLEMS, sorted(found - FIELD_PROBLEMS)


def test_status_def_codes_are_unique() -> None:
    codes = [s.code for s in DEFAULT_STATUSES]
    assert len(codes) == len(set(codes))
    assert {t.from_status for t in DEFAULT_TRANSITIONS} <= set(codes)
    assert StatusDef("x", StatusCategory.OPEN, "#000000").system is False
