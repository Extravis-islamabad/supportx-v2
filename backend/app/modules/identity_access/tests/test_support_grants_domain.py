"""Vendor support grants (WP-057 S4c-1, D-173): the pure rules."""

import dataclasses
from datetime import UTC, datetime, timedelta

from app.modules.identity_access.domain.support_grants import (
    MAX_TOTAL,
    Access,
    GrantRequest,
    Verification,
    domain_allowed,
    due_to_end,
    email_domain,
    extended_end,
    grant_problems,
    support_username,
    window,
)

NOW = datetime(2026, 11, 18, 9, tzinfo=UTC)
GOOD = GrantRequest(
    engineer_name="Omar Engineer",
    engineer_email="omar@extravis.com",
    reason="Ticket stuck in a workflow",
    ticket_ref="EXT-1042",
    access=Access.VIEW,
    change_reason=None,
    unmask_personal=False,
    hours=None,
    ip_allowlist=[],
    verification=Verification.EMAIL,
    confirmation_note=None,
)
DOMAINS = ("extravis.com",)


def _codes(request: GrantRequest, *, open_grants: int = 0, opted_out: bool = False) -> set[str]:
    return {
        code
        for _, code in grant_problems(
            request, allowed_domains=DOMAINS, open_grants=open_grants, opted_out=opted_out
        )
    }


def test_a_good_request_has_no_problem() -> None:
    assert _codes(GOOD) == set()


def test_only_the_allowed_domains_and_their_subdomains() -> None:
    """Lane B (1): an Extravis address, or the grant is refused."""
    assert domain_allowed("omar@extravis.com", DOMAINS)
    assert domain_allowed("omar@support.EXTRAVIS.com", DOMAINS)
    assert not domain_allowed("omar@extravis.com.evil.test", DOMAINS)
    assert not domain_allowed("omar@notextravis.com", DOMAINS)
    assert "support_email_domain_not_allowed" in _codes(
        dataclasses.replace(GOOD, engineer_email="omar@gmail.com")
    )
    assert "invalid_email" in _codes(dataclasses.replace(GOOD, engineer_email="omar extravis.com"))
    assert email_domain("a@b@extravis.com") is None


def test_the_opt_out_and_the_limit_refuse() -> None:
    assert "vendor_support_disabled" in _codes(GOOD, opted_out=True)
    assert "support_grants_limit" in _codes(GOOD, open_grants=3)
    assert _codes(GOOD, open_grants=2) == set()


def test_view_and_change_needs_its_own_reason() -> None:
    """D-173 (6): ticked deliberately, with a reason."""
    change = dataclasses.replace(GOOD, access=Access.VIEW_AND_CHANGE)
    assert "required" in _codes(change)
    assert _codes(dataclasses.replace(change, change_reason="Fix the SLA rule")) == set()


def test_an_out_of_band_confirmation_needs_its_note() -> None:
    """D-173 (5): when air-gapped, the admin says how they confirmed the engineer."""
    oob = dataclasses.replace(GOOD, verification=Verification.OUT_OF_BAND)
    assert "required" in _codes(oob)
    assert _codes(dataclasses.replace(oob, confirmation_note="Called Extravis back")) == set()


def test_24_hours_by_default_72_at_most() -> None:
    assert window(NOW, None) == (NOW, NOW + timedelta(hours=24))
    assert "support_grant_length" in _codes(dataclasses.replace(GOOD, hours=73))
    assert "support_grant_length" in _codes(dataclasses.replace(GOOD, hours=0))
    assert _codes(dataclasses.replace(GOOD, hours=72)) == set()


def test_an_extension_never_passes_72_hours_from_the_start() -> None:
    end = NOW + timedelta(hours=24)
    assert extended_end(NOW, end, 48) == NOW + MAX_TOTAL
    assert extended_end(NOW, end, 49) is None
    assert extended_end(NOW, end, 0) is None


def test_a_grant_is_due_to_end_once_its_time_is_up() -> None:
    assert due_to_end("active", NOW, NOW)
    assert due_to_end("pending_verification", NOW - timedelta(seconds=1), NOW)
    assert not due_to_end("active", NOW + timedelta(seconds=1), NOW)
    assert not due_to_end("revoked", NOW - timedelta(hours=1), NOW)


def test_the_account_name_is_per_grant() -> None:
    assert support_username("0193") == "extravis-support-0193"
