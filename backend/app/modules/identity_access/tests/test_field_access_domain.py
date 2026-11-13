"""Field access per role, compiled (ADR-047 §2, §3). Pure, no I/O."""

import uuid
from types import MappingProxyType

from app.modules.identity_access.domain.field_access import (
    EMPTY,
    FieldMode,
    clearest,
    compile_access,
    effective,
    from_json,
    mode_of,
    to_json,
    unseen,
    unwritable,
)
from app.modules.identity_access.domain.policy import Subject

T = "incident"


def test_the_clearest_mode_of_the_roles_wins() -> None:
    assert clearest([FieldMode.HIDDEN, FieldMode.READ_ONLY]) is FieldMode.READ_ONLY
    assert clearest([FieldMode.HIDDEN, FieldMode.MASKED]) is FieldMode.MASKED
    assert clearest([]) is FieldMode.CLEAR


def test_a_field_is_restricted_only_when_every_role_restricts_it() -> None:
    rules = [(T, "custom.salary", "hidden"), (T, "custom.salary", "masked"), (T, "cost", "hidden")]
    # Two roles: salary has a rule in both (masked wins), cost in one only (clear).
    assert effective(2, rules) == {(T, "custom.salary"): FieldMode.MASKED}
    # One role carrying both rules for salary cannot happen (one live rule per role and field);
    # with a third role and no rule there, salary is clear too.
    assert effective(3, rules) == {}


def test_no_roles_restrict_nothing() -> None:
    assert effective(0, [(T, "x", "hidden")]) == {}


def test_the_compiled_form_and_its_questions() -> None:
    access = compile_access(1, [(T, "a", "hidden"), (T, "b", "masked"), (T, "c", "read_only")])
    assert mode_of(access, T, "a") is FieldMode.HIDDEN
    assert mode_of(access, T, "z") is FieldMode.CLEAR
    assert mode_of(access, "problem", "a") is FieldMode.CLEAR
    assert unseen(access, T) == {"a", "b"}
    assert unwritable(access, T) == {"a", "b", "c"}  # hidden and masked are read-only too


def test_the_subject_keeps_its_field_access_in_the_cache_form() -> None:
    access = compile_access(1, [(T, "custom.salary", "hidden")])
    subject = Subject(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_keys=frozenset({"technician"}),
        is_tenant_admin=False,
        grants=MappingProxyType({}),
        field_access=access,
    )
    again = Subject.from_dict(subject.to_dict())
    assert to_json(again.field_access) == {T: {"custom.salary": "hidden"}}


def test_a_subject_cached_before_field_access_has_none() -> None:
    old = Subject(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_keys=frozenset(),
        is_tenant_admin=False,
        grants=MappingProxyType({}),
    ).to_dict()
    del old["field_access"]
    assert Subject.from_dict(old).field_access == EMPTY
    assert from_json(None) == EMPTY
