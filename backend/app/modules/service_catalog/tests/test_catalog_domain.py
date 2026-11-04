"""Catalog administration rules (WP-031 s1; no I/O)."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.service_catalog.domain.catalog import (
    ItemKind,
    ItemStatus,
    PublishFacts,
    category_problems,
    copy_names,
    due_status,
    hidden_categories,
    icon_problems,
    keyword_problems,
    missing_translations,
    publish_problems,
    schedule_problems,
    subject_from,
    subject_template_problems,
)
from app.modules.service_catalog.domain.items import (
    Audience,
    Question,
    QuestionKind,
    answer_problems,
    question_problems,
)

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def _chain(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def test_categories_nest_four_deep_without_loops() -> None:
    a, b, c, d = _chain(4)
    parents = {a: None, b: a, c: b, d: c}
    assert category_problems(None, c, parents) == []  # a new fourth level
    assert category_problems(None, d, parents) == [("parent_id", "too_deep")]
    assert category_problems(a, d, parents) == [("parent_id", "category_loop")]
    assert category_problems(b, b, parents) == [("parent_id", "category_loop")]
    assert category_problems(None, uuid.uuid4(), parents) == [("parent_id", "not_found")]
    e, f = _chain(2)
    # Moving b (with c and d below it) under e > f makes five levels; under e alone, four.
    assert category_problems(b, f, {**parents, e: None, f: e}) == [("parent_id", "too_deep")]
    assert category_problems(b, e, {**parents, e: None}) == []
    assert category_problems(d, f, {**parents, e: None, f: e}) == []


def test_a_disabled_category_hides_everything_below_it() -> None:
    a, b, c, other = _chain(4)
    parents = {a: None, b: a, c: b, other: None}
    assert hidden_categories([b], parents) == {b, c}
    assert hidden_categories([], parents) == set()


def test_publishing_needs_english_a_category_and_a_group() -> None:
    group, cat, template = _chain(3)
    ready = PublishFacts({"en": "Laptop"}, ItemKind.SERVICE, group, cat, None)
    assert publish_problems(ready) == []
    bare = PublishFacts({"ar": "حاسوب"}, ItemKind.SERVICE, None, None, None)
    assert publish_problems(bare) == [
        ("names.en", "required"),
        ("category_id", "required"),
        ("group_id", "required"),
    ]
    entry = PublishFacts({"en": "Printer broken"}, ItemKind.INCIDENT_TEMPLATE, None, cat, None)
    assert publish_problems(entry) == [("template_id", "required")]
    entry = PublishFacts({"en": "Printer broken"}, ItemKind.INCIDENT_TEMPLATE, None, cat, template)
    assert publish_problems(entry) == []


def test_schedules_are_in_the_future_and_in_order() -> None:
    soon, later = NOW + timedelta(hours=1), NOW + timedelta(days=1)
    assert schedule_problems(ItemStatus.DRAFT, soon, later, NOW) == []
    assert schedule_problems(ItemStatus.DRAFT, later, soon, NOW) == [
        ("retire_at", "before_publish")
    ]
    assert schedule_problems(ItemStatus.PUBLISHED, soon, None, NOW) == [
        ("publish_at", "not_allowed")
    ]
    assert schedule_problems(ItemStatus.DRAFT, NOW, None, NOW) == [("publish_at", "must_be_future")]
    assert schedule_problems(ItemStatus.RETIRED, None, later, NOW) == [("retire_at", "not_allowed")]


def test_the_schedule_publishes_then_retires() -> None:
    past, future = NOW - timedelta(minutes=1), NOW + timedelta(minutes=1)
    assert due_status(ItemStatus.DRAFT, past, None, NOW) is ItemStatus.PUBLISHED
    assert due_status(ItemStatus.DRAFT, future, None, NOW) is ItemStatus.DRAFT
    assert due_status(ItemStatus.PUBLISHED, None, past, NOW) is ItemStatus.RETIRED
    assert due_status(ItemStatus.DRAFT, past, past, NOW) is ItemStatus.RETIRED  # both overdue
    assert due_status(ItemStatus.RETIRED, past, None, NOW) is ItemStatus.RETIRED


def test_missing_translations_are_listed_per_field_and_language() -> None:
    texts = {
        "names": {"en": "Laptop", "ar": "حاسوب"},
        "summaries": {"en": "A laptop"},
        "descriptions": {},  # nothing in English: nothing to translate
    }
    assert missing_translations(texts, ["en", "ar", "ur"]) == [
        ("names", "ur"),
        ("summaries", "ar"),
        ("summaries", "ur"),
    ]
    assert missing_translations(texts, ["en"]) == []


def test_keywords_icons_and_copies() -> None:
    assert keyword_problems({"en": ["notebook", "computer"], "ar": ["لابتوب"]}) == []
    assert keyword_problems({"fr": ["x"]}) == [("keywords.fr", "invalid_choice")]
    assert keyword_problems({"en": [" "]}) == [("keywords.en", "invalid_value")]
    assert keyword_problems({"en": ["x"] * 21}) == [("keywords.en", "too_many_keywords")]
    assert icon_problems("icon", "laptop") == []
    assert icon_problems("icon", "https://example.com/x.png") == [("icon", "invalid_choice")]
    prefix = {"en": "Copy of", "ar": "نسخة من"}
    assert copy_names({"en": "Laptop", "ar": "حاسوب", "ur": ""}, prefix) == {
        "en": "Copy of Laptop",
        "ar": "نسخة من حاسوب",
    }


def test_the_subject_template_names_questions_and_fills_words() -> None:
    questions = [
        Question("system", {"en": "System"}, QuestionKind.CHOICE, options=("erp", "crm")),
        Question("why", {"en": "Why"}, QuestionKind.TEXT),
    ]
    template = "Access to {system} for {person}"
    assert subject_template_problems(template, questions) == []
    assert subject_template_problems("Access to {other}", questions) == [
        ("subject_template", "unknown_placeholder")
    ]
    subject = subject_from(
        template, {"system": "erp"}, person="Sara Ali", words={"erp": "Finance (ERP)"}
    )
    assert subject == "Access to Finance (ERP) for Sara Ali"
    assert subject_from("{why} - {system}", {}, person="x", words={}) == "-"


def test_new_question_kinds_check_their_answers() -> None:
    questions = [
        Question("mail", {"en": "Mail"}, QuestionKind.EMAIL),
        Question("site", {"en": "Site"}, QuestionKind.URL),
        Question("when", {"en": "When"}, QuestionKind.DATETIME),
        Question("ok", {"en": "OK"}, QuestionKind.YES_NO),
        Question("tags", {"en": "Tags"}, QuestionKind.MULTI_CHOICE, options=("a", "b")),
        Question("cost", {"en": "Cost"}, QuestionKind.CURRENCY),
        Question("who", {"en": "Who"}, QuestionKind.PERSON),
        Question("files", {"en": "Files"}, QuestionKind.ATTACHMENT),
    ]
    assert question_problems(questions) == []
    good = {
        "mail": "sara@example.com",
        "site": "https://example.com",
        "when": "2026-11-04T10:00:00+05:00",
        "ok": False,
        "tags": ["a", "b"],
        "cost": 12.5,
        "who": str(uuid.uuid4()),
        "files": [str(uuid.uuid4())],
    }
    assert answer_problems(questions, good) == []
    bad = {
        "mail": "sara",
        "site": "javascript:alert(1)",
        "when": "2026-11-04T10:00:00",
        "ok": "yes",
        "tags": ["c"],
        "cost": True,
        "who": "someone",
        "files": ["x"],
    }
    assert [code for _, code in answer_problems(questions, bad)] == [
        "email_not_valid",
        "url_not_valid",
        "timezone_required",
        "invalid_value",
        "invalid_choice",
        "invalid_number",
        "invalid_value",
        "invalid_value",
    ]


def test_questions_shown_to_others_are_unknown_to_the_requester() -> None:
    internal = Question(
        "asset_tag",
        {"en": "Asset tag"},
        QuestionKind.TEXT,
        shown_to=frozenset({Audience.TECHNICIAN}),
    )
    asked = Question("why", {"en": "Why"}, QuestionKind.TEXT, required=True)
    assert answer_problems([internal, asked], {"why": "x", "asset_tag": "A1"}) == [
        ("answers.asset_tag", "unknown_question")
    ]
    assert answer_problems([internal, asked], {"asset_tag": "A1"}, by=Audience.TECHNICIAN) == []
    # Required but nobody on the form sees it.
    hidden = Question(
        "x", {"en": "X"}, QuestionKind.TEXT, required=True, shown_to=frozenset({Audience.APPROVER})
    )
    assert question_problems([hidden]) == [("questions.0.required", "not_allowed")]


def test_choice_words_and_defaults_are_checked() -> None:
    choice = Question(
        "size",
        {"en": "Size"},
        QuestionKind.CHOICE,
        options=("small", "large"),
        option_labels={"small": {"en": "Small", "ar": "صغير"}, "huge": {"en": "Huge"}},
        default="medium",
    )
    assert question_problems([choice]) == [
        ("questions.0.option_labels.huge", "unknown_option"),
        ("questions.0.default", "invalid_value"),
    ]
