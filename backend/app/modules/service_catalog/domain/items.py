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
TEXT_MAX = 2000  # a short answer
LONG_TEXT_MAX = 10_000
HELP_MAX = 500
NUMBER_LIMIT = 10**15  # as WP-026 fields
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
    """What a form question takes (WP-030's five, plus WP-031 D6; the rules of WP-026's fields)."""

    TEXT = "text"
    LONG_TEXT = "long_text"
    CHOICE = "choice"
    NUMBER = "number"
    DATE = "date"
    DECIMAL = "decimal"
    CURRENCY = "currency"
    DATETIME = "datetime"
    MULTI_CHOICE = "multi_choice"
    YES_NO = "yes_no"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    PERSON = "person"
    ATTACHMENT = "attachment"


class QuestionAudience(StrEnum):
    """Who sees a form question (REQ-CAT-008): the requester, the technician, the approver."""

    REQUESTER = "requester"
    TECHNICIAN = "technician"
    APPROVER = "approver"


CHOICE_KINDS = frozenset({QuestionKind.CHOICE, QuestionKind.MULTI_CHOICE})
TEXT_KINDS = frozenset(
    {
        QuestionKind.TEXT,
        QuestionKind.LONG_TEXT,
        QuestionKind.EMAIL,
        QuestionKind.PHONE,
        QuestionKind.URL,
    }
)
# The formats of WP-026's custom fields (metadata/domain/fields.py), the same codes too.
_FORMATS: Mapping[QuestionKind, tuple[re.Pattern[str], str]] = {
    QuestionKind.EMAIL: (re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"), "email_not_valid"),
    QuestionKind.PHONE: (re.compile(r"^\+?[0-9 ()./-]{3,30}$"), "phone_not_valid"),
    QuestionKind.URL: (re.compile(r"^https?://[^\s]+$", re.IGNORECASE), "url_not_valid"),
}
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_ATTACHMENTS = 10


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
    options: Sequence[str] = ()  # choice codes; their words in option_labels
    # WP-031 D6: the words of each choice per language, help text, a starting value and who
    # sees the question (an approver-only question is never on the requester's form).
    option_labels: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    help: Mapping[str, str] = field(default_factory=dict)
    default: Any = None
    shown_to: frozenset[QuestionAudience] = frozenset(QuestionAudience)

    def as_json(self) -> dict[str, Any]:
        """For the item's JSON column."""
        return {
            "key": self.key,
            "label": dict(self.label),
            "kind": self.kind.value,
            "required": self.required,
            "options": list(self.options),
            "option_labels": {k: dict(v) for k, v in self.option_labels.items()},
            "help": dict(self.help),
            "default": self.default,
            "shown_to": sorted(a.value for a in self.shown_to),
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


def _option_problems(at: str, q: Question) -> list[Problem]:
    if q.kind not in CHOICE_KINDS:
        return [(f"{at}.options", "not_allowed")] if q.options else []
    if not q.options:
        return [(f"{at}.options", "required")]
    if len(q.options) > MAX_OPTIONS:
        return [(f"{at}.options", "too_many_options")]
    if any(not _KEY.fullmatch(o) for o in q.options) or len(set(q.options)) != len(q.options):
        return [(f"{at}.options", "invalid_key")]
    found: list[Problem] = [
        (f"{at}.option_labels.{code}", "unknown_option")
        for code in q.option_labels
        if code not in q.options
    ]
    for code, words in q.option_labels.items():
        found += name_problems(f"{at}.option_labels.{code}", words, required=False)
    return found


def question_problems(questions: Sequence[Question]) -> list[Problem]:
    """Keys unique and well-formed, labels in English, choices with options, sane defaults."""
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
        found += _help_problems(f"{at}.help", q.help)
        found += _option_problems(at, q)
        if not q.shown_to:
            found.append((f"{at}.shown_to", "required"))
        elif q.required and QuestionAudience.REQUESTER not in q.shown_to:
            # Nobody on the form could answer it.
            found.append((f"{at}.required", "not_allowed"))
        if q.default is not None and (
            q.kind in {QuestionKind.ATTACHMENT, QuestionKind.PERSON}
            or _value_problem(q, q.default) is not None
        ):
            found.append((f"{at}.default", "invalid_value"))
    return found


def _help_problems(at: str, help_text: Mapping[str, str]) -> list[Problem]:
    found: list[Problem] = []
    for lang, text in help_text.items():
        if lang not in LANGUAGES:
            found.append((f"{at}.{lang}", "invalid_choice"))
        elif len(text) > HELP_MAX:
            found.append((f"{at}.{lang}", "value_too_long"))
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


def _value_problem(q: Question, value: Any) -> str | None:  # noqa: ANN401, C901, PLR0911 - JSON; one rule per kind
    """The problem code of one non-empty answer, or None."""
    kind = q.kind
    if kind in TEXT_KINDS:
        if not isinstance(value, str):
            return "invalid_text"
        limit = LONG_TEXT_MAX if kind is QuestionKind.LONG_TEXT else TEXT_MAX
        if len(value) > limit:
            return "value_too_long"
        rule = _FORMATS.get(kind)
        return rule[1] if rule and not rule[0].fullmatch(value.strip()) else None
    if kind in {QuestionKind.NUMBER, QuestionKind.DECIMAL, QuestionKind.CURRENCY}:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return "invalid_number"
        return "above_maximum" if abs(value) >= NUMBER_LIMIT else None
    if kind is QuestionKind.CHOICE:
        return None if value in q.options else "invalid_choice"
    if kind is QuestionKind.MULTI_CHOICE:
        ok = isinstance(value, list) and all(isinstance(v, str) and v in q.options for v in value)
        return None if ok else "invalid_choice"
    if kind is QuestionKind.YES_NO:
        return None if isinstance(value, bool) else "invalid_value"
    if kind is QuestionKind.DATE:
        return None if isinstance(value, str) and _DATE.fullmatch(value) else "invalid_date"
    if kind is QuestionKind.DATETIME:
        ok = isinstance(value, str) and _DATETIME.fullmatch(value) is not None
        return None if ok else "timezone_required"
    if kind is QuestionKind.PERSON:
        return None if isinstance(value, str) and _is_uuid(value) else "invalid_value"
    if kind is QuestionKind.ATTACHMENT:  # file IDs, stored and scanned by the files module
        ok = (
            isinstance(value, list)
            and len(value) <= MAX_ATTACHMENTS
            and all(isinstance(v, str) and _is_uuid(v) for v in value)
        )
        return None if ok else "invalid_value"
    return "invalid_value"  # pragma: no cover - every kind is handled above


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _empty(value: Any) -> bool:  # noqa: ANN401 - JSON value
    return value is None or value == [] or (isinstance(value, str) and not value.strip())


def answer_problems(
    questions: Sequence[Question],
    answers: Mapping[str, Any],
    *,
    by: QuestionAudience = QuestionAudience.REQUESTER,
) -> list[Problem]:
    """The form's answers (REQ-SR-003): required ones given, values of their kind, no strangers.

    `by` is who fills the form: a question not shown to them is unknown to them, so a
    requester can never set a technician-only or approver-only answer.
    """
    by_key = {q.key: q for q in questions if by in q.shown_to}
    found: list[Problem] = [
        (f"answers.{key}", "unknown_question") for key in answers if key not in by_key
    ]
    for q in by_key.values():
        value = answers.get(q.key)
        if _empty(value):
            if q.required and by is QuestionAudience.REQUESTER:
                found.append((f"answers.{q.key}", "required"))
            continue
        if (code := _value_problem(q, value)) is not None:
            found.append((f"answers.{q.key}", code))
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
