"""A change's risk (WP-045b S1; file 05 §8, REQ-CHG-056..060). Pure.

Levels in order (lowest first), a scored questionnaire whose total maps to a level through
bands, rules that may raise the level and never lower a questionnaire's result unless an admin
allows it, and an override by a person that always says why. The questionnaire is versioned:
a change keeps the version it was assessed with (REQ-CHG-057 AC3).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    """Appendix A's levels, lowest first (REQ-CHG-056)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


ORDER: tuple[RiskLevel, ...] = tuple(RiskLevel)


def rank(level: RiskLevel | str) -> int:
    """A level's place, lowest first (reports group and sort by it, REQ-CHG-056 AC1)."""
    return ORDER.index(RiskLevel(level))


@dataclass(frozen=True)
class Answer:
    """One answer and its weight."""

    code: str
    score: int


@dataclass(frozen=True)
class Question:
    """One question of a questionnaire, with its weighted answers."""

    code: str
    answers: tuple[Answer, ...]

    def score_of(self, answer: str) -> int | None:
        """The answer's weight, or None for an answer the question does not have."""
        return next((a.score for a in self.answers if a.code == answer), None)


@dataclass(frozen=True)
class Band:
    """Scores from `low` (inclusive) map to `level`, up to the next band."""

    low: int
    level: RiskLevel


@dataclass(frozen=True)
class Questionnaire:
    """A versioned risk questionnaire (REQ-CHG-057)."""

    version: int
    questions: tuple[Question, ...]
    bands: tuple[Band, ...]

    def level_for(self, score: int) -> RiskLevel:
        """The level a total score maps to (bands sorted, the highest band reached)."""
        reached = [b for b in sorted(self.bands, key=lambda b: b.low) if score >= b.low]
        return reached[-1].level if reached else ORDER[0]


def _q(code: str, *answers: tuple[str, int]) -> Question:
    return Question(code, tuple(Answer(c, s) for c, s in answers))


# Appendix A's questionnaire and bands (0-3 low, 4-7 medium, 8-11 high, 12+ very high).
DEFAULT_QUESTIONNAIRE = Questionnaire(
    version=1,
    questions=(
        _q("affected", ("one_team", 0), ("department_or_site", 2), ("organisation", 4)),
        _q("done_before", ("often", 0), ("once_or_twice", 1), ("never", 3)),
        _q("backout_plan", ("tested", 0), ("untested", 2), ("none", 4)),
        _q("outage", ("none", 0), ("in_window", 1), ("outside_window", 3)),
        _q("critical", ("no", 0), ("yes", 3)),
        _q("cis_changed", ("one", 0), ("two_to_five", 1), ("more_than_five", 2)),
    ),
    bands=(
        Band(0, RiskLevel.LOW),
        Band(4, RiskLevel.MEDIUM),
        Band(8, RiskLevel.HIGH),
        Band(12, RiskLevel.VERY_HIGH),
    ),
)


@dataclass(frozen=True)
class Assessment:
    """What a questionnaire gave: the answers, the score and the level, with its version."""

    version: int
    answers: Mapping[str, str]
    score: int
    level: RiskLevel


def assess(
    questionnaire: Questionnaire, answers: Mapping[str, str]
) -> tuple[Assessment | None, list[tuple[str, str]]]:
    """Score the answers (REQ-CHG-057): every question answered with one of its answers.

    Returns the assessment, or (None, field problems) naming each question that is missing an
    answer or has one it does not offer.
    """
    problems: list[tuple[str, str]] = []
    total = 0
    for question in questionnaire.questions:
        given = answers.get(question.code)
        if given is None:
            problems.append((f"risk_answers.{question.code}", "required"))
            continue
        weight = question.score_of(given)
        if weight is None:
            problems.append((f"risk_answers.{question.code}", "invalid_choice"))
            continue
        total += weight
    known = {q.code for q in questionnaire.questions}
    problems += [(f"risk_answers.{n}", "not_a_field") for n in sorted(set(answers) - known)]
    if problems:
        return None, problems
    level = questionnaire.level_for(total)
    return Assessment(questionnaire.version, dict(answers), total, level), []


def raised_by_rule(
    current: RiskLevel | None, by_rule: RiskLevel, *, may_lower: bool = False
) -> tuple[RiskLevel, str | None]:
    """A rule's level against the current one (REQ-CHG-058).

    A rule sets or raises the level; it never lowers a questionnaire's result unless the admin
    allows it. Returns the level to keep and, when the rule is ignored, why (for its trace).
    """
    if current is None or rank(by_rule) >= rank(current) or may_lower:
        return by_rule, None
    return current, "risk_rule_would_lower"


def override_problems(chosen: RiskLevel | None, reason: str | None) -> list[tuple[str, str]]:
    """An override by a person always says why (REQ-CHG-060 AC1)."""
    if chosen is not None and not (reason or "").strip():
        return [("risk_reason", "reason_required")]
    return []


def effective(calculated: RiskLevel | None, chosen: RiskLevel | None) -> RiskLevel | None:
    """The level that counts: the person's override, else the calculated one (both are kept)."""
    return chosen if chosen is not None else calculated


def highest(levels: Sequence[RiskLevel]) -> RiskLevel | None:
    """The highest of several levels (several rules), or None."""
    return max(levels, key=rank) if levels else None


# The change details' risk columns (0116): what an assessment and an override write.
RISK_FIELDS = ("risk", "risk_score", "risk_answers", "risk_version", "risk_chosen", "risk_reason")
_LEVELS = frozenset(level.value for level in RiskLevel)


def details_problems(merged: Mapping[str, object]) -> list[tuple[str, str]]:
    """(field, code) pairs of a change's risk after an edit (values merged)."""
    problems: list[tuple[str, str]] = []
    for name in ("risk", "risk_chosen"):
        value = merged.get(name)
        if value is not None and value not in _LEVELS:
            problems.append((name, "invalid_choice"))
    chosen = merged.get("risk_chosen")
    reason = merged.get("risk_reason")
    problems += override_problems(
        RiskLevel(chosen) if isinstance(chosen, str) and chosen in _LEVELS else None,
        reason if isinstance(reason, str) else None,
    )
    return problems


def questionnaire_from(raw: Any) -> Questionnaire:  # noqa: ANN401 - a template's stored JSON, checked here
    """A template's own questionnaire (its JSON), else Appendix A's; a broken one falls back."""
    if not raw:
        return DEFAULT_QUESTIONNAIRE
    try:
        questions = tuple(
            Question(
                str(q["code"]),
                tuple(Answer(str(a["code"]), int(a["score"])) for a in q["answers"]),
            )
            for q in raw["questions"]
        )
        bands = tuple(Band(int(b["low"]), RiskLevel(b["level"])) for b in raw["bands"])
        version = int(raw.get("version", 1))
    except (KeyError, TypeError, ValueError, AttributeError):
        return DEFAULT_QUESTIONNAIRE
    if not questions or not bands:
        return DEFAULT_QUESTIONNAIRE
    return Questionnaire(version, questions, bands)


def questionnaire_json(questionnaire: Questionnaire) -> dict[str, object]:
    """A questionnaire as the API and the template store it."""
    return {
        "version": questionnaire.version,
        "questions": [
            {"code": q.code, "answers": [{"code": a.code, "score": a.score} for a in q.answers]}
            for q in questionnaire.questions
        ],
        "bands": [{"low": b.low, "level": b.level.value} for b in questionnaire.bands],
    }
