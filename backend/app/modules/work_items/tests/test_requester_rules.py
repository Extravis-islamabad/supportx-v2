"""Requester cancel and edit rules (WP-046b S5; REQ-INC-148): the pure domain."""

import pytest

from app.modules.work_items.domain.requester_rules import (
    REQUESTER_EDITABLE,
    STAFF_ONLY_FIELDS,
    CancellationState,
    RequesterCancel,
    editable_by_requester,
)


def test_off_is_the_default_and_the_codes_are_stable() -> None:
    assert [c.value for c in RequesterCancel] == ["off", "direct", "ask"]
    assert [s.value for s in CancellationState] == ["pending", "approved", "declined", "withdrawn"]


@pytest.mark.parametrize("field", sorted(STAFF_ONLY_FIELDS))
def test_a_staff_only_field_is_never_editable_even_when_allowed(field: str) -> None:
    """The coordinator's test: a tenant setting can never open a staff-only field."""
    assert not editable_by_requester(field, frozenset({field}))


def test_a_reporting_field_is_editable_only_when_the_tenant_allows_it() -> None:
    assert editable_by_requester("subject", frozenset({"subject"}))
    assert not editable_by_requester("subject", frozenset())
    assert not editable_by_requester("description", frozenset({"subject"}))
    assert not editable_by_requester("not_a_field", frozenset({"not_a_field"}))


def test_custom_fields_follow_the_tenant_list() -> None:
    assert editable_by_requester("custom.asset_tag", frozenset({"custom.asset_tag"}))
    assert not editable_by_requester("custom.asset_tag", frozenset())


def test_the_two_lists_never_overlap() -> None:
    assert not (REQUESTER_EDITABLE & STAFF_ONLY_FIELDS)
