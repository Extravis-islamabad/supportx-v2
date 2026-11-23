"""An item's approval stages (WP-047a S2a; REQ-SR-029..032): the model and its checks, no I/O."""

import uuid

from app.modules.service_catalog.domain.items import (
    MAX_AUTO_RULES,
    MAX_STAGES,
    ApprovalStage,
    Approver,
    ApproverKind,
    AutoRule,
    ItemRules,
    Question,
    QuestionKind,
    StageRule,
    needs_approval,
    rules_problems,
    stages_problems,
    uses_stages,
)
from app.modules.service_catalog.service.catalog import stages_of

PERSON = uuid.UUID("01900000-0000-7000-8000-0000000000a1")
GROUP = uuid.UUID("01900000-0000-7000-8000-0000000000b1")
QUESTIONS = (
    Question("model", {"en": "Model"}, QuestionKind.CHOICE, required=True, options=("air", "pro")),
    Question("buddy", {"en": "Who helps"}, QuestionKind.PERSON, required=False),
)


def _stage(*approvers: Approver, **over: object) -> ApprovalStage:
    return ApprovalStage(approvers=approvers, **over)  # type: ignore[arg-type]  # test-only kwargs


MANAGER = Approver(ApproverKind.REQUESTED_FOR_MANAGER)


def test_an_item_saved_before_s2a_reads_as_its_one_stage_unchanged() -> None:
    """The coordinator's condition 5: no data step; the old shape is stage 1, rule `any`."""
    old = {
        "approvers": [{"kind": "requested_for_manager", "person_id": None}],
        "backup_id": str(PERSON),
        "comments_required": True,
        "self_approval": False,
    }
    (only,) = stages_of(old)
    assert only.approvers == (MANAGER,)
    assert (only.backup_id, only.comments_required, only.self_approval) == (PERSON, True, False)
    assert (only.rule, only.parallel_group, only.condition) == (StageRule.ANY, None, None)
    assert stages_of(None) == ()
    assert stages_of({}) == ()


def test_the_new_shape_keeps_every_stage_in_order() -> None:
    stored = {
        "stages": [
            {"approvers": [{"kind": "requested_for_manager"}]},
            {"approvers": [{"kind": "group", "group_id": str(GROUP)}], "rule": "majority"},
            {
                "approvers": [{"kind": "department_head"}],
                "condition": {"field": "model", "op": "eq", "value": "pro"},
                "parallel_group": "finance",
            },
        ]
    }
    first, second, third = stages_of(stored)
    assert first.approvers == (MANAGER,)
    assert (second.rule, second.approvers[0].group_id) == (StageRule.MAJORITY, GROUP)
    assert third.condition == {"field": "model", "op": "eq", "value": "pro"}
    assert third.parallel_group == "finance"


def test_requests_take_up_to_ten_stages() -> None:
    """REQ-SR-029 AC4 and the coordinator's condition 4 (the staged types keep 5)."""
    assert MAX_STAGES == 10
    ten = [_stage(MANAGER) for _ in range(10)]
    assert stages_problems(ten, QUESTIONS) == []
    assert stages_problems([*ten, _stage(MANAGER)], QUESTIONS) == [
        ("approval.stages", "too_many_stages")
    ]


def test_each_kind_names_what_it_needs_and_nothing_else() -> None:
    stages = [
        _stage(Approver(ApproverKind.PERSON)),
        _stage(Approver(ApproverKind.GROUP)),
        _stage(Approver(ApproverKind.PERSON_ANSWER, question_key="model")),  # not a person question
        _stage(Approver(ApproverKind.DEPARTMENT_HEAD, person_id=PERSON)),
        _stage(Approver(ApproverKind.PERSON_ANSWER, question_key="buddy")),  # fine
        _stage(Approver(ApproverKind.CI_OWNER, group_id=GROUP)),
    ]
    assert set(stages_problems(stages, QUESTIONS)) == {
        ("approval.stages.0.approvers.0.person_id", "required"),
        ("approval.stages.1.approvers.0.group_id", "required"),
        ("approval.stages.2.approvers.0.question_key", "not_a_person_question"),
        ("approval.stages.3.approvers.0.person_id", "not_allowed"),
        ("approval.stages.5.approvers.0", "invalid_value"),
    }


def test_a_condition_is_the_forms_dsl_over_the_answers_and_the_quantity() -> None:
    """The coordinator's condition 4: the same validator as form rules."""
    good = _stage(
        MANAGER,
        condition={
            "and": [
                {"field": "quantity", "op": "ne", "value": 1},
                {"field": "model", "op": "eq", "value": "pro"},
            ]
        },
    )
    unknown = _stage(MANAGER, condition={"field": "salary", "op": "eq", "value": 1})
    bad_op = _stage(MANAGER, condition={"field": "model", "op": "gt", "value": 1})
    assert stages_problems([good], QUESTIONS) == []
    assert stages_problems([unknown], QUESTIONS) == [
        ("approval.stages.0.condition.field", "not_a_form_field")
    ]
    assert stages_problems([bad_op], QUESTIONS) == [
        ("approval.stages.0.condition.op", "invalid_choice")
    ]


def test_a_parallel_group_is_a_short_code() -> None:
    assert stages_problems([_stage(MANAGER, parallel_group="Finance team")], QUESTIONS) == [
        ("approval.stages.0.parallel_group", "invalid_value")
    ]


def test_rules_check_stages_only_when_there_are_several() -> None:
    one = ItemRules(questions=QUESTIONS, approval=_stage(MANAGER), stages=(_stage(MANAGER),))
    many = ItemRules(
        questions=QUESTIONS,
        approval=_stage(MANAGER),
        stages=(_stage(MANAGER), _stage(Approver(ApproverKind.GROUP))),
    )
    assert rules_problems(one) == []
    assert rules_problems(many) == [("approval.stages.1.approvers.0.group_id", "required")]
    assert needs_approval(many)
    assert not needs_approval(ItemRules(questions=QUESTIONS))


def test_each_professional_part_is_named_by_its_requirement() -> None:
    """Per-REQ editions: today's one stage is every edition's; 029-032 are Professional."""
    today = _stage(MANAGER, Approver(ApproverKind.PERSON, PERSON))
    assert not uses_stages([today])
    assert not uses_stages([])
    assert uses_stages([today, today])  # REQ-SR-029: several stages
    assert uses_stages([_stage(MANAGER, rule=StageRule.ALL)])  # REQ-SR-029: a rule
    assert uses_stages([_stage(MANAGER, parallel_group="pair")])  # REQ-SR-030
    assert uses_stages([_stage(Approver(ApproverKind.GROUP, group_id=GROUP))])  # REQ-SR-031
    assert uses_stages([_stage(MANAGER, condition={"field": "model"})])  # REQ-SR-032


def test_a_single_stage_body_with_stages_null_is_the_single_stage() -> None:
    """The API model sends `stages: null` on today's body: it must read as that one stage."""
    body = {"approvers": [{"kind": "requested_for_manager"}], "stages": None}
    (only,) = stages_of(body)
    assert only.approvers == (MANAGER,)
    assert len(stages_of({**body, "stages": []})) == 1


# --- WP-047a S2b (REQ-SR-033): automatic approval --------------------------------------------


def test_automatic_approval_is_professional() -> None:
    """Either switch or a rule makes the approval use stages (`catalog`), like S2a's parts."""
    assert not uses_stages([_stage(MANAGER)])
    assert uses_stages([_stage(MANAGER, auto_earlier=False)])  # overriding the tenant too
    rule = AutoRule({"en": "Small"}, {"field": "quantity", "op": "eq", "value": 1})
    assert uses_stages([_stage(MANAGER, auto_rules=(rule,))])


def test_an_automatic_rule_needs_a_name_and_a_condition_over_known_fields() -> None:
    good = AutoRule(
        {"en": "Help desk"}, {"field": "requester_groups", "op": "eq", "value": str(GROUP)}
    )
    nameless = AutoRule({"ar": "x"}, {"field": "model", "op": "eq", "value": "air"})
    unknown = AutoRule({"en": "x"}, {"field": "salary", "op": "eq", "value": 1})
    found = stages_problems(
        [_stage(MANAGER, auto_rules=(good, nameless, unknown)), _stage(MANAGER)], QUESTIONS
    )
    assert found == [
        ("approval.stages.0.auto_rules.1.name.en", "required"),
        ("approval.stages.0.auto_rules.2.condition.field", "not_a_form_field"),
    ]
    too_many = (good,) * (MAX_AUTO_RULES + 1)
    assert stages_problems([_stage(MANAGER, auto_rules=too_many)], QUESTIONS) == [
        ("approval.stages.0.auto_rules", "too_many_rules")
    ]


def test_a_single_stage_has_its_condition_and_rules_checked_too() -> None:
    """Fixed in S2b: a lone stage's condition and rules were not checked before saving."""
    bad = {"field": "salary", "op": "eq", "value": 1}
    rules = ItemRules(
        questions=QUESTIONS,
        approval=_stage(MANAGER, condition=bad),
        stages=(_stage(MANAGER, condition=bad),),
    )
    assert rules_problems(rules) == [("approval.condition.field", "not_a_form_field")]


def test_the_auto_settings_survive_reading_and_storing() -> None:
    stored = {
        "approvers": [{"kind": "requested_for_manager", "person_id": None}],
        "auto_earlier": True,
        "auto_rules": [
            {"name": {"en": "Small"}, "condition": {"field": "quantity", "op": "eq", "value": 1}}
        ],
    }
    (stage,) = stages_of(stored)
    assert stage.auto_earlier is True
    assert [dict(r.name) for r in stage.auto_rules] == [{"en": "Small"}]
