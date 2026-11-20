"""Vendor support grants (WP-057 S4c-1, D-173): the pure rules."""

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity_access.domain import support_grants
from app.modules.identity_access.domain.support_grants import (
    MAX_TOTAL,
    WITH_MAIL,
    Access,
    Delivery,
    GrantRequest,
    Verification,
    account_email,
    actions_for,
    admin_could_act_as_engineer,
    delivery_for,
    domain_allowed,
    due_to_end,
    email_domain,
    extended_end,
    grant_problems,
    link_lifespan_seconds,
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
    assert "support_email_invalid" in _codes(
        dataclasses.replace(GOOD, engineer_email="omar extravis.com")
    )
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


def test_the_account_address_is_per_grant_and_reaches_the_same_mailbox() -> None:
    """Lane B (1): one function, lowercase, the grant's UUID as hex, the real address's domain."""
    grant = uuid.UUID("0193f0aa-0000-7000-8000-00000000abcd")
    made = account_email("Omar@Extravis.com", grant)
    assert made == f"omar+sx-{grant.hex}@extravis.com"
    assert made is not None
    assert made.split("@")[1] == "extravis.com"  # same domain as the real address
    other = account_email("omar@extravis.com", uuid.UUID(int=1))
    assert other != made  # a second grant, a new address


def test_a_tagged_or_too_long_address_is_refused() -> None:
    """Lane B (1): never a second tag, never past 64 characters before the @."""
    grant = uuid.UUID(int=7)
    assert account_email("omar+old@extravis.com", grant) is None
    assert account_email(("o" * 30) + "@extravis.com", grant) is None  # 30 + 36 > 64
    assert account_email(("o" * 28) + "@extravis.com", grant) is not None  # 28 + 36 = 64
    assert "support_email_not_taggable" in _codes(
        dataclasses.replace(GOOD, engineer_email="omar+x@extravis.com")
    )


def test_one_place_decides_how_the_engineer_gets_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-177: with mail, the engineer's own actions e-mail; without, the admin's password."""
    oob = Verification.OUT_OF_BAND
    assert delivery_for(oob, mail_available=True) is Delivery.ONE_TIME_PASSWORD
    assert delivery_for(Verification.EMAIL, mail_available=False) is Delivery.ONE_TIME_PASSWORD
    assert WITH_MAIL is Delivery.ACTIONS_EMAIL
    assert delivery_for(Verification.EMAIL, mail_available=True) is Delivery.ACTIONS_EMAIL
    assert admin_could_act_as_engineer(Delivery.ONE_TIME_PASSWORD)
    assert not admin_could_act_as_engineer(Delivery.ACTIONS_EMAIL)
    # Still one value: the function follows it.
    monkeypatch.setattr(support_grants, "WITH_MAIL", Delivery.ONE_TIME_PASSWORD)
    assert support_grants.delivery_for(Verification.EMAIL, mail_available=True) is (
        Delivery.ONE_TIME_PASSWORD
    )


def test_the_required_actions_and_the_link_lifespan() -> None:
    assert actions_for(Verification.EMAIL) == ("VERIFY_EMAIL", "UPDATE_PASSWORD", "CONFIGURE_TOTP")
    assert "VERIFY_EMAIL" not in actions_for(Verification.OUT_OF_BAND)
    assert link_lifespan_seconds(NOW, NOW + timedelta(hours=72)) == 24 * 3600
    assert link_lifespan_seconds(NOW, NOW + timedelta(hours=2)) == 2 * 3600
    assert link_lifespan_seconds(NOW, NOW) == 60


def test_the_fallback_login_and_link_token() -> None:
    """D-177 fallback: a generated login, a single-use link kept only as its hash."""
    grant = uuid.UUID("0193f0aa-0000-7000-8000-00000000abcd")
    assert support_grants.support_login(grant) == f"sx-support-{grant.hex}"
    assert "@" not in support_grants.support_login(grant)
    token, stored = support_grants.new_link_token()
    assert token.encode() not in stored
    later = NOW + timedelta(hours=1)
    assert support_grants.link_usable(stored, token, later, None, NOW)
    assert not support_grants.link_usable(stored, token + "x", later, None, NOW)
    assert not support_grants.link_usable(stored, token, NOW, None, NOW)  # expired
    assert not support_grants.link_usable(stored, token, later, NOW, NOW)  # used
    assert not support_grants.link_usable(None, token, later, None, NOW)
    assert len(support_grants.mail_subject_id(grant)) == 8
