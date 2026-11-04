"""A catalog item's rules (WP-030 s1; no I/O)."""

import uuid

from app.modules.service_catalog.domain.items import (
    ApprovalStage,
    Approver,
    ApproverKind,
    ItemRules,
    PlannedTask,
    Question,
    QuestionKind,
    answer_problems,
    approval_problems,
    name_problems,
    needs_approval,
    plan_problems,
    question_problems,
)

EN = {"en": "Laptop model"}


def test_names_need_english_and_known_languages() -> None:
    assert name_problems("name", {"ar": "حاسوب"}, required=True) == [("name.en", "required")]
    assert name_problems("name", {"en": "x", "fr": "y"}, required=True) == [
        ("name.fr", "invalid_choice")
    ]
    assert name_problems("name", {"en": "x" * 121}, required=True) == [
        ("name.en", "value_too_long")
    ]
    assert name_problems("description", None, required=False) == []


def test_questions_have_unique_keys_and_choices_have_options() -> None:
    good = [
        Question("model", EN, QuestionKind.CHOICE, required=True, options=("air", "pro")),
        Question("reason", {"en": "Why"}, QuestionKind.LONG_TEXT),
    ]
    assert question_problems(good) == []
    bad = [
        Question("Model", EN, QuestionKind.TEXT),
        Question("size", EN, QuestionKind.CHOICE),
        Question("size", EN, QuestionKind.TEXT, options=("x",)),
    ]
    assert question_problems(bad) == [
        ("questions.0.key", "invalid_key"),
        ("questions.1.options", "required"),
        ("questions.2.key", "duplicate"),
        ("questions.2.options", "not_allowed"),
    ]


def test_answers_follow_the_questions() -> None:
    questions = [
        Question("model", EN, QuestionKind.CHOICE, required=True, options=("air", "pro")),
        Question("count", {"en": "How many"}, QuestionKind.NUMBER),
        Question("needed", {"en": "Needed by"}, QuestionKind.DATE),
    ]
    assert answer_problems(questions, {"model": "air", "count": 2, "needed": "2026-12-01"}) == []
    assert answer_problems(questions, {"count": True, "needed": "soon", "colour": "red"}) == [
        ("answers.colour", "unknown_question"),
        ("answers.model", "required"),
        ("answers.count", "invalid_number"),
        ("answers.needed", "invalid_date"),
    ]
    assert answer_problems(questions, {"model": "mini"}) == [("answers.model", "invalid_choice")]


def test_an_approval_stage_names_its_approvers() -> None:
    someone = uuid.uuid4()
    ok = ApprovalStage(
        (Approver(ApproverKind.PERSON, someone), Approver(ApproverKind.REQUESTED_FOR_MANAGER))
    )
    assert approval_problems(ok) == []
    assert approval_problems(ApprovalStage(())) == [("approval.approvers", "required")]
    assert approval_problems(
        ApprovalStage(
            (Approver(ApproverKind.PERSON), Approver(ApproverKind.REQUESTED_FOR_MANAGER, someone))
        )
    ) == [
        ("approval.approvers.0.person_id", "required"),
        ("approval.approvers.1.person_id", "not_allowed"),
    ]
    assert needs_approval(ItemRules(approval=ok))
    assert not needs_approval(ItemRules())


def test_plan_tasks_have_titles() -> None:
    assert plan_problems([PlannedTask({"en": "Image the laptop"})]) == []
    assert plan_problems([PlannedTask({"ar": "تجهيز"})]) == [("plan.0.title.en", "required")]
