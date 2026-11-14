"""Automations cannot name a field their author may not see in clear (ADR-047 §8). Pure."""

import uuid
from types import MappingProxyType

from app.modules.automation.domain.field_refs import named_fields, refused, withheld
from app.modules.automation.service.workflow_admin import _access_problems
from app.modules.identity_access import Subject

ACCESS = {
    "incident": {"custom.salary": "masked", "impact_details": "hidden", "urgency": "read_only"}
}


def _author() -> Subject:
    from app.modules.identity_access.domain.field_access import from_json  # noqa: PLC0415

    return Subject(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_keys=frozenset({"tenant_admin"}),
        is_tenant_admin=True,
        grants=MappingProxyType({}),
        field_access=from_json(ACCESS),
    )


def test_names_are_found_anywhere_under_field_keys() -> None:
    conditions = {"all": [{"field": "custom.salary", "op": "eq", "value": 1}]}
    actions = [{"kind": "set", "field": "urgency", "value": "high"}, {"from_field": "subject"}]
    assert named_fields(conditions, actions) == {"custom.salary", "urgency", "subject"}


def test_read_only_is_seen_in_clear_hidden_and_masked_are_not() -> None:
    assert withheld(ACCESS, "incident") == {"custom.salary", "impact_details"}
    assert refused(ACCESS, "incident", [{"field": "urgency"}]) == []  # read-only: they see it
    assert refused(ACCESS, "incident", [{"field": "custom.salary"}]) == ["custom.salary"]
    assert refused(ACCESS, "problem", [{"field": "custom.salary"}]) == []  # another type


def test_a_workflow_step_setting_a_withheld_field_is_a_problem_on_that_step() -> None:
    definition = {
        "nodes": [
            {"id": "s", "type": "start", "config": {}},
            {"id": "set", "type": "field_update", "config": {"values": {"custom.salary": "B7"}}},
            {"id": "if", "type": "condition", "config": {"field": "impact_details"}},
        ]
    }
    assert _access_problems(_author(), "incident", definition) == [
        ("node:set", "field_not_permitted", {"field": "custom.salary"}),
        ("node:if", "field_not_permitted", {"field": "impact_details"}),
    ]
    assert _access_problems(None, "incident", definition) == []  # no author: a system save
