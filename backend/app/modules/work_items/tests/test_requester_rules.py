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


def test_a_custom_field_is_never_editable_even_when_listed() -> None:
    """Lane C's B2: the portal shows requesters no custom field, so none is theirs to write."""
    assert not editable_by_requester("custom.asset_tag", frozenset({"custom.asset_tag"}))


def test_a_field_the_portal_hides_on_this_record_is_not_editable() -> None:
    allowed = frozenset({"subject", "impact"})
    assert editable_by_requester("impact", allowed, frozenset({"subject", "impact"}))
    assert not editable_by_requester("impact", allowed, frozenset({"subject"}))


def test_the_two_lists_never_overlap() -> None:
    assert not (REQUESTER_EDITABLE & STAFF_ONLY_FIELDS)


def test_the_deciders_codes_are_stable() -> None:
    """Who decides an ask (S5 condition 1): stored in events, labelled in the UI."""
    from app.modules.work_items.domain.requester_rules import (  # noqa: PLC0415
        CancellationDeciders,
    )

    assert [d.value for d in CancellationDeciders] == ["assignee", "group", "managers", "none"]
