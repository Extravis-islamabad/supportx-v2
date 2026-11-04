"""A catalog item's rules (WP-030 s1, plan D2; REQ-SR-001, -005..008, -021..023, -046; no I/O).

Every service request comes from an item, and the item decides its form, approval, fulfilment
plan, priority, SLA and group. This is the minimal model WP-030 needs; WP-031 adds the admin
screens, versions and the rest of REQ-CAT. Rules return codes (the labels say the words).
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

LANGUAGES = ("en", "ar", "ur")
NAME_MAX = 120
TEXT_MAX = 2000
MAX_QUESTIONS = 30
MAX_OPTIONS = 50
MAX_TASKS = 20
MAX_APPROVERS = 10
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class ItemAudience(StrEnum):
    """Who may raise the item (REQ-SR-010 AC3: some are for technicians only)."""

    EVERYONE = "everyone"
    TECHNICIANS = "technicians"


class QuestionKind(StrEnum):
    """What a form question takes."""

    TEXT = "text"
    LONG_TEXT = "long_text"
    CHOICE = "choice"
    NUMBER = "number"
    DATE = "date"


class ApproverKind(StrEnum):
    """Who decides a stage (REQ-SR-022): a named person, or the requested-for person's manager."""

    PERSON = "person"
    REQUESTED_FOR_MANAGER = "requested_for_manager"


Problem = tuple[str, str]  # (field path, code)


@dataclass(frozen=True)
class Question:
    """One form question (its answers are kept on the request, labelled per language)."""

    key: str
    label: Mapping[str, str]
    kind: QuestionKind
    required: bool = False
    options: Sequence[str] = ()  # choice codes; their labels live with the question

    def as_json(self) -> dict[str, Any]:
        """For the item's JSON column."""
        return {
            "key": self.key,
            "label": dict(self.label),
            "kind": self.kind.value,
            "required": self.required,
            "options": list(self.options),
        }


@dataclass(frozen=True)
class Approver:
    """One approver of a stage."""

    kind: ApproverKind
    person_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ApprovalStage:
    """The item's approval (one stage at MVP; more with `catalog`, plan D3)."""

    approvers: Sequence[Approver]
    backup_id: uuid.UUID | None = None  # REQ-SR-023: before the approval administrators
    comments_required: bool = False  # REQ-SR-028
    self_approval: bool = False  # REQ-SR-027: off = segregation of duties


@dataclass(frozen=True)
class PlannedTask:
    """One fulfilment task the plan creates (REQ-SR-046)."""

    title: Mapping[str, str]
    group_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    required: bool = True  # REQ-SR-058: the last required one fulfils the request
    internal: bool = False  # REQ-SR-051 AC2: shown to requesters only as "step n of m"


@dataclass(frozen=True)
class ItemRules:
    """What an item decides for its requests."""

    questions: Sequence[Question] = ()
    approval: ApprovalStage | None = None
    plan: Sequence[PlannedTask] = ()
    technician_after_approval: bool = False  # REQ-SR-008
    count_approval_time: bool = False  # REQ-SR-007: off = the clock waits for approval
    auto_fulfil: bool = True  # REQ-SR-058
    extra: Mapping[str, Any] = field(default_factory=dict)


def name_problems(at: str, names: Mapping[str, str] | None, *, required: bool) -> list[Problem]:
    """A name per language: English required (the fallback), each within NAME_MAX."""
    found: list[Problem] = []
    names = names or {}
    if required and not (names.get("en") or "").strip():
        found.append((f"{at}.en", "required"))
    for lang, text in names.items():
        if lang not in LANGUAGES:
            found.append((f"{at}.{lang}", "invalid_choice"))
        elif len(text) > NAME_MAX:
            found.append((f"{at}.{lang}", "value_too_long"))
    return found


def question_problems(questions: Sequence[Question]) -> list[Problem]:
    """Keys unique and well-formed, labels in English, choices with options."""
    found: list[Problem] = []
    if len(questions) > MAX_QUESTIONS:
        found.append(("questions", "too_many_questions"))
    seen: set[str] = set()
    for i, q in enumerate(questions):
        at = f"questions.{i}"
        if not _KEY.fullmatch(q.key):
            found.append((f"{at}.key", "invalid_key"))
        elif q.key in seen:
            found.append((f"{at}.key", "duplicate"))
        seen.add(q.key)
        found += name_problems(f"{at}.label", q.label, required=True)
        if q.kind is QuestionKind.CHOICE:
            if not q.options:
                found.append((f"{at}.options", "required"))
            elif len(q.options) > MAX_OPTIONS:
                found.append((f"{at}.options", "too_many_options"))
            elif any(not _KEY.fullmatch(o) for o in q.options) or len(set(q.options)) != len(
                q.options
            ):
                found.append((f"{at}.options", "invalid_key"))
        elif q.options:
            found.append((f"{at}.options", "not_allowed"))
    return found


def approval_problems(stage: ApprovalStage | None) -> list[Problem]:
    """A stage names at least one approver; a person approver names the person."""
    if stage is None:
        return []
    found: list[Problem] = []
    if not stage.approvers:
        found.append(("approval.approvers", "required"))
    if len(stage.approvers) > MAX_APPROVERS:
        found.append(("approval.approvers", "too_many_approvers"))
    for i, a in enumerate(stage.approvers):
        if a.kind is ApproverKind.PERSON and a.person_id is None:
            found.append((f"approval.approvers.{i}.person_id", "required"))
        if a.kind is ApproverKind.REQUESTED_FOR_MANAGER and a.person_id is not None:
            found.append((f"approval.approvers.{i}.person_id", "not_allowed"))
    return found


def plan_problems(plan: Sequence[PlannedTask]) -> list[Problem]:
    """Tasks have a title in English; not too many."""
    found: list[Problem] = []
    if len(plan) > MAX_TASKS:
        found.append(("plan", "too_many_tasks"))
    for i, task in enumerate(plan):
        found += name_problems(f"plan.{i}.title", task.title, required=True)
    return found


def rules_problems(rules: ItemRules) -> list[Problem]:
    """Everything wrong with an item's rules, at its field."""
    return (
        question_problems(rules.questions)
        + approval_problems(rules.approval)
        + plan_problems(rules.plan)
    )


def answer_problems(questions: Sequence[Question], answers: Mapping[str, Any]) -> list[Problem]:
    """The form's answers (REQ-SR-003): required ones given, choices from the list, no strangers."""
    by_key = {q.key: q for q in questions}
    found: list[Problem] = [
        (f"answers.{key}", "unknown_question") for key in answers if key not in by_key
    ]
    for q in questions:
        value = answers.get(q.key)
        empty = value is None or (isinstance(value, str) and not value.strip())
        if empty:
            if q.required:
                found.append((f"answers.{q.key}", "required"))
            continue
        at = f"answers.{q.key}"
        if q.kind is QuestionKind.CHOICE and value not in q.options:
            found.append((at, "invalid_choice"))
        elif q.kind is QuestionKind.NUMBER and (
            isinstance(value, bool) or not isinstance(value, int | float)
        ):
            found.append((at, "invalid_number"))
        elif q.kind in {QuestionKind.TEXT, QuestionKind.LONG_TEXT} and (
            not isinstance(value, str) or len(value) > TEXT_MAX
        ):
            found.append((at, "value_too_long" if isinstance(value, str) else "invalid_text"))
        elif q.kind is QuestionKind.DATE and not (
            isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
        ):
            found.append((at, "invalid_date"))
    return found


def needs_approval(rules: ItemRules) -> bool:
    """Whether a new request from this item waits for approval (REQ-SR-021)."""
    return rules.approval is not None and bool(rules.approval.approvers)


__all__ = [
    "LANGUAGES",
    "ApprovalStage",
    "Approver",
    "ApproverKind",
    "ItemAudience",
    "ItemRules",
    "PlannedTask",
    "Question",
    "QuestionKind",
    "answer_problems",
    "approval_problems",
    "name_problems",
    "needs_approval",
    "plan_problems",
    "question_problems",
    "rules_problems",
]
