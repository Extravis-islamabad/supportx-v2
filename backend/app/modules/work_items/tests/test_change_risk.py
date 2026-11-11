"""A change's risk, the pure rules (WP-045b S1; REQ-CHG-056..060)."""

from app.modules.work_items.domain.change_risk import (
    DEFAULT_QUESTIONNAIRE,
    RiskLevel,
    assess,
    effective,
    highest,
    override_problems,
    raised_by_rule,
    rank,
)

# 4 + 1 + 2 + 0 + 0 + 2 = 9
NINE = {
    "affected": "organisation",
    "done_before": "once_or_twice",
    "backout_plan": "untested",
    "outage": "none",
    "critical": "no",
    "cis_changed": "more_than_five",
}


def test_req_chg_056_levels_are_in_their_order() -> None:
    assert [rank(level) for level in RiskLevel] == [0, 1, 2, 3]
    assert rank("very_high") > rank("high") > rank(RiskLevel.MEDIUM) > rank("low")


def test_req_chg_057_ac1_a_total_of_nine_is_high() -> None:
    result, problems = assess(DEFAULT_QUESTIONNAIRE, NINE)
    assert problems == []
    assert result is not None
    assert (result.score, result.level, result.version) == (9, RiskLevel.HIGH, 1)


def test_req_chg_057_bands_follow_appendix_a() -> None:
    q = DEFAULT_QUESTIONNAIRE
    assert [q.level_for(s) for s in (0, 3, 4, 7, 8, 11, 12, 20)] == [
        RiskLevel.LOW,
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.HIGH,
        RiskLevel.VERY_HIGH,
        RiskLevel.VERY_HIGH,
    ]


def test_req_chg_057_ac2_changing_one_answer_recomputes() -> None:
    lower, _ = assess(DEFAULT_QUESTIONNAIRE, {**NINE, "affected": "one_team"})  # 9 - 4 = 5
    assert lower is not None
    assert (lower.score, lower.level) == (5, RiskLevel.MEDIUM)


def test_every_question_needs_one_of_its_answers() -> None:
    result, problems = assess(DEFAULT_QUESTIONNAIRE, {**NINE, "critical": "maybe", "extra": "x"})
    assert result is None
    assert set(problems) == {
        ("risk_answers.critical", "invalid_choice"),
        ("risk_answers.extra", "not_a_field"),
    }
    partial = dict(list(NINE.items())[:2])
    _, missing = assess(DEFAULT_QUESTIONNAIRE, partial)
    assert ("risk_answers.outage", "required") in missing


def test_req_chg_058_a_rule_raises_and_never_lowers_unless_allowed() -> None:
    assert raised_by_rule(RiskLevel.MEDIUM, RiskLevel.HIGH) == (RiskLevel.HIGH, None)
    assert raised_by_rule(None, RiskLevel.LOW) == (RiskLevel.LOW, None)
    assert raised_by_rule(RiskLevel.HIGH, RiskLevel.LOW) == (
        RiskLevel.HIGH,
        "risk_rule_would_lower",
    )  # AC2: ignored, and the trace says why
    assert raised_by_rule(RiskLevel.HIGH, RiskLevel.LOW, may_lower=True) == (RiskLevel.LOW, None)
    assert highest([RiskLevel.LOW, RiskLevel.VERY_HIGH, RiskLevel.HIGH]) == RiskLevel.VERY_HIGH
    assert highest([]) is None


def test_req_chg_060_an_override_says_why_and_both_are_kept() -> None:
    assert override_problems(RiskLevel.LOW, None) == [("risk_reason", "reason_required")]
    assert override_problems(RiskLevel.LOW, "  ") == [("risk_reason", "reason_required")]
    assert override_problems(RiskLevel.LOW, "Done weekly without issue") == []
    assert override_problems(None, None) == []
    assert effective(RiskLevel.HIGH, RiskLevel.LOW) == RiskLevel.LOW
    assert effective(RiskLevel.HIGH, None) == RiskLevel.HIGH
