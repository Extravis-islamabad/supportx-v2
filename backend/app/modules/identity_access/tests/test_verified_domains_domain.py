"""Verified domains, the pure rules (WP-057 S5d; lane B's conditions)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity_access.domain import verified_domains as vd

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("Acme.COM", "acme.com"),
        ("@acme.com.", "acme.com"),
        ("  mail.acme.co.uk ", "mail.acme.co.uk"),
        ("مثال.السعودية", "xn--mgbh0fb.xn--mgberp4a5d4ar"),
    ],
)
def test_domains_are_normalised(raw: str, kept: str) -> None:
    assert vd.normalise(raw) == kept


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "domain_invalid"),
        ("localhost", "domain_single_label"),
        ("gmail.com", "domain_public_mail"),
        ("co.uk", "domain_public_suffix"),
        ("com.pk", "domain_public_suffix"),
        ("-acme.com", "domain_invalid"),
        ("acme..com", "domain_invalid"),
        ("a" * 64 + ".com", "domain_invalid"),
    ],
)
def test_domains_no_company_can_own_are_refused(raw: str, code: str) -> None:
    with pytest.raises(vd.DomainProblem) as refused:
        vd.normalise(raw)
    assert refused.value.code == code


def test_a_token_is_32_bytes_shown_once_and_kept_as_its_hash() -> None:
    token = vd.new_token()
    assert len(token.value) >= 52  # 32 bytes in base32
    assert token.digest == vd.digest_of(token.value)
    assert token.value not in token.digest.hex()
    assert vd.new_token().value != token.value


def test_only_the_exact_record_proves() -> None:
    token = vd.new_token()
    right = vd.record_value(token.value)
    assert vd.record_name("acme.com") == "_supportx.acme.com"
    assert vd.proves([right], token.digest)
    assert vd.proves(['"' + right + '"'], token.digest)  # as some resolvers quote it
    assert vd.proves(["v=spf1 -all", right], token.digest)
    assert not vd.proves([right + "x"], token.digest)
    assert not vd.proves([f"other={token.value}"], token.digest)
    assert not vd.proves(["supportx-verification=" + vd.new_token().value], token.digest)
    assert not vd.proves(["supportx-verification=٣"], token.digest)  # never a non-ASCII token


def test_a_domain_lapses_only_after_three_failures_over_72_hours() -> None:
    since = NOW - timedelta(hours=73)
    assert vd.lapses(3, since, NOW)
    assert not vd.lapses(2, since, NOW)  # not enough failures
    assert not vd.lapses(5, NOW - timedelta(hours=10), NOW)  # not long enough
    assert not vd.lapses(3, None, NOW)


def test_which_domains_the_schedule_checks() -> None:
    day = timedelta(days=1)
    pending = vd.DomainState.PENDING
    assert vd.due(pending, None, NOW - day, NOW)
    assert not vd.due(pending, NOW - timedelta(hours=2), NOW - day, NOW)  # once a day
    assert not vd.due(pending, None, NOW - timedelta(days=8), NOW)  # then "Check now" only
    verified = vd.DomainState.VERIFIED
    assert vd.due(verified, NOW - timedelta(days=31), NOW - timedelta(days=60), NOW)
    assert not vd.due(verified, NOW - day, NOW - timedelta(days=60), NOW)
    assert not vd.due(vd.DomainState.LAPSED, None, NOW - day, NOW)


def test_keycloak_domains_follow_a_verify_and_an_unverify() -> None:
    routed = [{"name": "acme.test", "verified": False, "identityProviderAlias": "x"}]
    assert vd.kc_verified(routed, "acme.test")[0] == {
        "name": "acme.test",
        "verified": True,
        "identityProviderAlias": "x",
    }
    assert vd.kc_verified([], "new.test") == [{"name": "new.test", "verified": True}]
    kept = vd.kc_unverified([{**routed[0], "verified": True}], "acme.test")
    assert kept == [{**routed[0], "verified": False}]  # single tenant: the routing stays
    assert vd.kc_without(routed, "acme.test") == []  # multi-tenant: gone
