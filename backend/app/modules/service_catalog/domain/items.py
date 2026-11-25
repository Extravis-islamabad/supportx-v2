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

from app.shared.conditions import condition_problems

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
    """Who decides a stage (REQ-SR-022, -031), relative to the requested-for person or named.

    Each resolves to people when the stage opens; one that resolves to nobody falls back to
    the approval administrators, recorded (REQ-SR-023; WP-047a S2 condition 3).
    """

    PERSON = "person"
    REQUESTED_FOR_MANAGER = "requested_for_manager"
    # WP-047a S2a (REQ-SR-031): Professional (`catalog`, D-133).
    MANAGER_OF_MANAGER = "manager_of_manager"
    DEPARTMENT_HEAD = "department_head"  # the requested-for person's department's head
    GROUP_LEADS = "group_leads"  # the request's group's team leads (D-152)
    GROUP = "group"  # every member of a named group who may approve
    PERSON_ANSWER = "person_answer"  # the person a "person" question's answer names
    ASSET_OWNER = "asset_owner"  # the holder of the asset(s) the request is about
    CI_OWNER = "ci_owner"  # the owner of the CI(s) the request is about (person or group)


class StageRule(StrEnum):
    """How a stage's approvers decide it (REQ-SR-029; the level engine's rules).

    "First decision" is `any` (the coordinator's Q5): the first approval approves, a rejection
    rejects. Majority ties follow the tenant's tie rule (D-146: a tie rejects unless the chair
    decides it).
    """

    ANY = "any"
    ALL = "all"
    MAJORITY = "majority"


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
    # WP-047a S3b (REQ-SR-041, Essentials): a change to this answer after submitting restarts the
    # request's approval from its first stage.
    restarts_approval: bool = False
    # WP-047b S1 (REQ-CAT-020): a choice's extra price per option, decimal text (domain/pricing).
    option_prices: Mapping[str, str] = field(default_factory=dict)

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
            **({"restarts_approval": True} if self.restarts_approval else {}),
            **({"option_prices": dict(self.option_prices)} if self.option_prices else {}),
        }


@dataclass(frozen=True)
class Approver:
    """One approver of a stage: a kind and what it names (a person, a group or a question)."""

    kind: ApproverKind
    person_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None  # GROUP
    question_key: str | None = None  # PERSON_ANSWER: a "person" question of the form


@dataclass(frozen=True)
class ApprovalStage:
    """The item's approval (one stage at MVP; more with `catalog`, plan D3)."""

    approvers: Sequence[Approver]
    backup_id: uuid.UUID | None = None  # REQ-SR-023: before the approval administrators
    comments_required: bool = False  # REQ-SR-028
    self_approval: bool = False  # REQ-SR-027: off = segregation of duties
    # WP-047a S2a: how it is decided (REQ-SR-029), the stages it runs with (REQ-SR-030: the
    # same group opens together), and when it applies at all (REQ-SR-032: the shared DSL over
    # the answers and the quantity; None: always).
    rule: StageRule = StageRule.ANY
    parallel_group: str | None = None
    condition: Mapping[str, Any] | None = None
    # WP-047a S2b (REQ-SR-033): whether someone who approved an earlier stage of the same
    # request is not asked again (None: the tenant's setting decides), and the rules that
    # approve the stage at once when one holds.
    auto_earlier: bool | None = None
    auto_rules: Sequence["AutoRule"] = ()
    # WP-047a S3a (REQ-SR-034, Essentials): where the approval goes after its last reminder.
    escalate_to: "EscalationTarget" = field(default_factory=lambda: EscalationTarget.BACKUP)


class EscalationTarget(StrEnum):
    """Where a stage's pending approval goes after its last reminder (REQ-SR-034).

    The primary approver keeps their approval as well (REQ-SR-036 AC2). Nobody there: the
    approval administrators, recorded (the coordinator's S3 condition 2).
    """

    BACKUP = "backup"  # the stage's backup approver (the default)
    APPROVER_MANAGER = "approver_manager"  # the pending approver's own manager
    FULFILMENT_GROUP = "fulfilment_group"  # the members of the request's group
    NONE = "none"  # reminders only


class RestartOn(StrEnum):
    """A request value whose change restarts approval (REQ-SR-041), beside marked questions."""

    QUANTITY = "quantity"
    REQUESTED_FOR = "requested_for"


@dataclass(frozen=True)
class AutoRule:
    """A rule that approves a stage automatically (WP-047a S2b; REQ-SR-033).

    Its name (per language) is what the record shows: "approved automatically: <name>". Its
    condition is the shared DSL over the answers, the quantity and `requester_groups` (the
    groups the requester belongs to: `eq` means "is a member of").
    """

    name: Mapping[str, str]
    condition: Mapping[str, Any]


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
    approval: ApprovalStage | None = None  # the first stage (as before WP-047a S2a)
    plan: Sequence[PlannedTask] = ()
    technician_after_approval: bool = False  # REQ-SR-008
    count_approval_time: bool = False  # REQ-SR-007: off = the clock waits for approval
    auto_fulfil: bool = True  # REQ-SR-058
    extra: Mapping[str, Any] = field(default_factory=dict)
    # WP-047a S2a: every stage in order (`approval` is the first); empty: no approval.
    stages: Sequence[ApprovalStage] = ()
    # WP-047a S3b (REQ-SR-041): the request's own values whose change restarts approval.
    restart_on: frozenset["RestartOn"] = frozenset()


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


# REQ-SR-029 AC4: requests take up to 10 stages (the coordinator's condition 4); the staged
# record types keep their own cap (work_items `MAX_LEVELS`, 5).
MAX_STAGES = 10
PARALLEL_GROUP = re.compile(r"^[a-z0-9_]{1,40}$")
_NEEDS_PERSON = frozenset({ApproverKind.PERSON})
_NAMES_NOTHING = frozenset(
    {
        ApproverKind.REQUESTED_FOR_MANAGER,
        ApproverKind.MANAGER_OF_MANAGER,
        ApproverKind.DEPARTMENT_HEAD,
        ApproverKind.GROUP_LEADS,
        ApproverKind.ASSET_OWNER,
        ApproverKind.CI_OWNER,
    }
)


TODAYS_KINDS = frozenset({ApproverKind.PERSON, ApproverKind.REQUESTED_FOR_MANAGER})


def uses_stages(stages: Sequence[ApprovalStage]) -> bool:
    """Whether an approval uses a Professional part of S2a (`catalog`; spec editions, D-133).

    Each part is gated by its own requirement's edition, all Professional:
    REQ-SR-029 (several stages, or a rule other than `any`), REQ-SR-030 (a parallel group),
    REQ-SR-031 (an approver kind beyond a named person and the manager), REQ-SR-032 (a
    condition), REQ-SR-033 (automatic approval: either switch or a rule). Today's single
    stage stays on every edition (the coordinator's condition 5).
    """
    multi_stage = len(stages) > 1 or any(s.rule is not StageRule.ANY for s in stages)  # 029
    parallel = any(s.parallel_group is not None for s in stages)  # 030
    kinds = any(a.kind not in TODAYS_KINDS for s in stages for a in s.approvers)  # 031
    conditional = any(s.condition is not None for s in stages)  # 032
    automatic = any(s.auto_earlier is not None or s.auto_rules for s in stages)  # 033
    return multi_stage or parallel or kinds or conditional or automatic


def stages_problems(
    stages: Sequence[ApprovalStage], questions: Sequence[Question]
) -> list[Problem]:
    """Every stage's problems, at `approval.stages.<n>` (WP-047a S2a; REQ-SR-029..032).

    At most `MAX_STAGES`; each names its approvers as its kind needs; a person answer names a
    "person" question of this form; a condition is the shared DSL over the answers and the
    quantity, checked exactly as form rules are (condition 4).
    """
    if len(stages) > MAX_STAGES:
        return [("approval.stages", "too_many_stages")]
    person_questions = {q.key for q in questions if q.kind is QuestionKind.PERSON}
    fields = frozenset({*(q.key for q in questions), "quantity"})
    found: list[Problem] = []
    for n, stage in enumerate(stages):
        at = f"approval.stages.{n}"
        found += [(p.replace("approval", at, 1), c) for p, c in approval_problems(stage)]
        for i, a in enumerate(stage.approvers):
            here = f"{at}.approvers.{i}"
            if a.kind is ApproverKind.GROUP and a.group_id is None:
                found.append((f"{here}.group_id", "required"))
            if a.kind is ApproverKind.PERSON_ANSWER and a.question_key not in person_questions:
                found.append((f"{here}.question_key", "not_a_person_question"))
        if stage.parallel_group is not None and not PARALLEL_GROUP.fullmatch(stage.parallel_group):
            found.append((f"{at}.parallel_group", "invalid_value"))
        if stage.condition is not None:
            found += condition_problems(stage.condition, fields, f"{at}.condition")
        found += _auto_rule_problems(
            stage.auto_rules, fields | {REQUESTER_GROUPS, ESTIMATED_COST}, at
        )
    return found


# WP-047a S2b (REQ-SR-033): what an automatic rule may read beyond the form, and how many.
REQUESTER_GROUPS = "requester_groups"
# WP-047b S1 (REQ-SR-033 AC2): "approve below a cost" reads the request's estimate (lt/lte).
ESTIMATED_COST = "estimated_cost"
MAX_AUTO_RULES = 5


def _auto_rule_problems(
    auto_rules: Sequence[AutoRule], fields: frozenset[str], at: str
) -> list[Problem]:
    if len(auto_rules) > MAX_AUTO_RULES:
        return [(f"{at}.auto_rules", "too_many_rules")]
    found: list[Problem] = []
    for i, rule in enumerate(auto_rules):
        here = f"{at}.auto_rules.{i}"
        found += name_problems(f"{here}.name", rule.name, required=True)
        found += condition_problems(rule.condition, fields, f"{here}.condition")
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
        if a.kind in _NEEDS_PERSON and a.person_id is None:
            found.append((f"approval.approvers.{i}.person_id", "required"))
        if a.kind is not ApproverKind.PERSON and a.person_id is not None:
            found.append((f"approval.approvers.{i}.person_id", "not_allowed"))
        if a.kind in _NAMES_NOTHING and (a.group_id is not None or a.question_key is not None):
            found.append((f"approval.approvers.{i}", "invalid_value"))
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
    staged = len(rules.stages) > 1
    single = [] if staged else list(rules.stages[:1])
    return (
        question_problems(rules.questions)
        + (stages_problems(rules.stages, rules.questions) if staged else [])
        + ([] if staged else approval_problems(rules.approval))
        + _single_stage_problems(single, rules.questions)
        + plan_problems(rules.plan)
    )


def _single_stage_problems(
    single: Sequence[ApprovalStage], questions: Sequence[Question]
) -> list[Problem]:
    """A single stage's S2a/S2b parts (kinds, condition, rules), at `approval.<field>`.

    Its approvers are checked by `approval_problems`, as before S2a; only what that leaves out
    is added here, so a single stage with a condition or a rule is checked like any stage.
    """
    if not single:
        return []
    prefix = "approval.stages.0"
    found = stages_problems(single, questions)
    own = set(approval_problems(single[0]))
    return [
        (path.replace(prefix, "approval", 1), code)
        for path, code in found
        if (path.replace(prefix, "approval", 1), code) not in own
    ]


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
    return any(stage.approvers for stage in rules.stages) or (
        rules.approval is not None and bool(rules.approval.approvers)
    )


__all__ = [
    "ESTIMATED_COST",
    "LANGUAGES",
    "MAX_AUTO_RULES",
    "REQUESTER_GROUPS",
    "ApprovalStage",
    "Approver",
    "ApproverKind",
    "AutoRule",
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


@dataclass(frozen=True)
class Again:
    """A past request's answers, as the item's form takes them now (REQ-SR-016)."""

    answers: Mapping[str, Any]
    dropped: tuple[str, ...]  # answers to questions the form no longer has (AC2)


def request_again(questions: Sequence[Question], answers: Mapping[str, Any]) -> Again:
    """The earlier answers for a new request of the same item (WP-047a S1, REQ-SR-016).

    Kept: answers to the requester's questions the form still has. Attachments are never
    copied (AC1): the requester adds them again. Dropped and listed (AC2): answers to questions
    the form no longer has at all. An answer to a question the form still has but not for the
    requester (a technician's or an approver's) is in neither list: never shown, never named.
    The record's answers are all the requester's own today (`answer_problems` refuses any other
    at create); a later answer by staff or an approver must be stored apart (WP-047a S4), so a
    removed staff question can never be named here.
    """
    every = {q.key for q in questions}
    current = {q.key: q for q in questions if QuestionAudience.REQUESTER in q.shown_to}
    kept = {
        key: value
        for key, value in answers.items()
        if key in current and current[key].kind is not QuestionKind.ATTACHMENT
    }
    dropped = tuple(sorted(key for key in answers if key not in every))
    return Again(kept, dropped)
