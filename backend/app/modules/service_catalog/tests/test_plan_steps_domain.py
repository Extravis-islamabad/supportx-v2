"""A fulfilment plan's WP-047a S5 parts (REQ-SR-047..050, -056): checked when the item is saved."""

import uuid

from app.modules.service_catalog.domain.items import (
    PlannedTask,
    Question,
    QuestionKind,
    TaskField,
    TaskFieldKind,
    TaskOwnerKind,
    plan_problems,
)

T = {"en": "Step"}


def _step(**over: object) -> PlannedTask:
    return PlannedTask(T, **over)  # type: ignore[arg-type]  # the test's own overrides


def test_steps_wait_only_for_steps_that_exist_and_never_in_a_loop() -> None:
    ok = [_step(key="licence"), _step(key="account", waits_for=("licence",))]
    assert plan_problems(ok) == []
    assert ("plan.1.waits_for", "invalid_choice") in plan_problems(
        [_step(key="a"), _step(key="b", waits_for=("nope",))]
    )
    assert ("plan.0.key", "required") in plan_problems([_step(waits_for=("a",))])
    loop = [_step(key="a", waits_for=("b",)), _step(key="b", waits_for=("a",))]
    assert plan_problems(loop) == [("plan", "plan_waits_in_a_loop")]
    twins = [_step(key="a"), _step(key="a")]
    assert ("plan.1.key", "invalid_value") in plan_problems(twins)


def test_a_condition_reads_the_form_and_an_owner_names_what_it_needs() -> None:
    remote = Question(key="remote", label={"en": "Remote?"}, kind=QuestionKind.YES_NO)
    boss = Question(key="boss", label={"en": "Manager"}, kind=QuestionKind.PERSON)
    good = _step(condition={"field": "remote", "op": "eq", "value": True})
    assert plan_problems([good], [remote, boss]) == []
    stray = _step(condition={"field": "salary", "op": "eq", "value": 1})
    assert plan_problems([stray], [remote]) != []
    assert ("plan.0.owner_id", "required") in plan_problems(
        [_step(owner_kind=TaskOwnerKind.PERSON)]
    )
    assert ("plan.0.question_key", "not_a_person_question") in plan_problems(
        [_step(owner_kind=TaskOwnerKind.PERSON_ANSWER, question_key="remote")], [remote, boss]
    )
    named = _step(owner_kind=TaskOwnerKind.PERSON_ANSWER, question_key="boss")
    assert plan_problems([named], [remote, boss]) == []
    person = _step(owner_kind=TaskOwnerKind.PERSON, owner_id=uuid.uuid4())
    assert plan_problems([person]) == []


def test_task_fields_are_few_unique_and_a_choice_has_options() -> None:
    field = TaskField(key="account", label={"en": "Account name"}, required=True)
    assert plan_problems([_step(fields=(field,))]) == []
    many = tuple(TaskField(key=f"f{i}", label={"en": "F"}) for i in range(11))
    assert plan_problems([_step(fields=many)]) == [("plan.0.fields", "too_many_values")]
    twice = (field, field)
    assert ("plan.0.fields.1.key", "invalid_value") in plan_problems([_step(fields=twice)])
    bare = TaskField(key="size", label={"en": "Size"}, kind=TaskFieldKind.CHOICE)
    assert ("plan.0.fields.0.options", "required") in plan_problems([_step(fields=(bare,))])
