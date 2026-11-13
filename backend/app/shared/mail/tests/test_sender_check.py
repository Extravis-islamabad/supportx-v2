"""Sender verification from Authentication-Results (WP-046a S6; lane B's blocking conditions)."""

import email
import email.policy
from email.message import EmailMessage

import pytest

from app.shared.mail.domain.sender_check import (
    MAX_HEADERS,
    Unreadable,
    aligned,
    from_domain,
    read_header,
    sender_verified,
)

MX = "mx.example.net"  # the tenant's own mail server

# Shapes as Gmail and Microsoft 365 write them (values shortened, structure kept).
GMAIL = (
    "mx.google.com;\r\n"
    "       dkim=pass header.i=@acme.test header.s=s1 header.b=AbCdEf12;\r\n"
    "       spf=pass (google.com: domain of sara@acme.test designates 192.0.2.1 as permitted"
    " sender) smtp.mailfrom=sara@acme.test;\r\n"
    "       dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=acme.test"
)
M365 = (
    "spf=pass (sender IP is 192.0.2.1)\r\n smtp.mailfrom=acme.test; dkim=pass (signature was"
    " verified)\r\n header.d=acme.test;dmarc=pass action=none\r\n header.from=acme.test;"
    "compauth=pass reason=100"
)


def message(*results: str, sender: str = "Sara <sara@acme.test>", **extra: str) -> EmailMessage:
    lines = [f"Authentication-Results: {r}" for r in results]
    lines += [f"{name.replace('_', '-')}: {value}" for name, value in extra.items()]
    raw = "\r\n".join([*lines, f"From: {sender}", "Subject: hi", "", "body", ""])
    parsed = email.message_from_bytes(raw.encode(), policy=email.policy.default)
    assert isinstance(parsed, EmailMessage)
    return parsed


def ok(msg: EmailMessage, *, trusted: tuple[str, ...] = (MX,), provider: bool = False) -> bool:
    return sender_verified(msg, trusted=trusted, trust_provider=provider)


# --- what passes -------------------------------------------------------------------------------


def test_dmarc_pass_from_the_trusted_server_verifies() -> None:
    assert ok(message(f"{MX}; dmarc=pass header.from=acme.test"))


def test_spf_and_an_aligned_dkim_verify_without_dmarc() -> None:
    assert ok(message(f"{MX}; spf=pass smtp.mailfrom=acme.test; dkim=pass header.d=mail.acme.test"))


def test_real_gmail_header_verifies_when_gmail_is_trusted() -> None:
    assert ok(message(GMAIL), trusted=("mx.google.com",))


def test_real_m365_header_needs_the_provider_switch() -> None:
    assert not ok(message(M365))
    assert ok(message(M365), trusted=(), provider=True)


def test_a_failing_second_signature_does_not_spoil_an_aligned_pass() -> None:
    assert ok(
        message(
            f"{MX}; spf=pass smtp.mailfrom=acme.test; dkim=fail header.d=acme.test;"
            " dkim=pass header.d=acme.test"
        )
    )


def test_comments_nested_and_mixed_case_are_read() -> None:
    header = f"{MX.upper()} (our (inner) server); DMARC=Pass (p=none) Header.From=Acme.Test"
    assert ok(message(header))


# --- what never verifies -----------------------------------------------------------------------


def test_nothing_is_trusted_by_default() -> None:
    assert not ok(message(f"{MX}; dmarc=pass header.from=acme.test"), trusted=())


def test_a_forged_from_with_no_results_header() -> None:
    assert not ok(message(sender="Boss <ceo@acme.test>"))


def test_a_header_from_a_server_we_do_not_trust_is_ignored() -> None:
    assert not ok(message("mx.attacker.test; dmarc=pass header.from=acme.test"))


def test_a_forged_trusted_header_below_the_real_one_is_not_believed() -> None:
    real = f"{MX}; dmarc=fail header.from=acme.test"
    forged = f"{MX}; dmarc=pass header.from=acme.test"
    assert not ok(message(real, forged))


def test_two_trusted_headers_that_disagree_verify_nothing() -> None:
    assert not ok(message(f"{MX}; dmarc=pass header.from=acme.test", f"{MX}; dmarc=fail"))


def test_dmarc_fail() -> None:
    header = f"{MX}; spf=pass smtp.mailfrom=acme.test; dmarc=fail header.from=acme.test"
    assert not ok(message(header))


def test_dmarc_pass_for_another_domain() -> None:
    assert not ok(message(f"{MX}; dmarc=pass header.from=other.test"))


def test_dkim_of_a_different_domain_does_not_align() -> None:
    assert not ok(message(f"{MX}; spf=pass; dkim=pass header.d=attacker.test"))


def test_spf_alone_is_not_enough() -> None:
    assert not ok(message(f"{MX}; spf=pass smtp.mailfrom=acme.test"))


def test_arc_and_original_results_are_never_read() -> None:
    msg = message(
        f"{MX}; dmarc=fail header.from=acme.test",
        ARC_Authentication_Results=f"i=1; {MX}; dmarc=pass header.from=acme.test",
        Authentication_Results_Original=f"{MX}; dmarc=pass header.from=acme.test",
    )
    assert not ok(msg)
    only_arc = message(ARC_Authentication_Results=f"i=1; {MX}; dmarc=pass header.from=acme.test")
    assert not ok(only_arc)


def test_provider_header_counts_only_when_it_is_topmost() -> None:
    lower = message(f"{MX}; dmarc=fail", M365)
    assert not ok(lower, trusted=(), provider=True)


def test_provider_switch_off_ignores_an_id_less_header() -> None:
    assert not ok(message(M365), trusted=(MX,), provider=False)


@pytest.mark.parametrize(
    "sender",
    [
        "a@acme.test, b@acme.test",  # two addresses
        "not an address",
        "",
    ],
)
def test_from_must_be_one_address(sender: str) -> None:
    assert not ok(message(f"{MX}; dmarc=pass header.from=acme.test", sender=sender))


def test_two_from_headers() -> None:
    raw = (
        f"Authentication-Results: {MX}; dmarc=pass header.from=acme.test\r\n"
        "From: sara@acme.test\r\nFrom: ceo@acme.test\r\nSubject: x\r\n\r\nbody\r\n"
    )
    msg = email.message_from_bytes(raw.encode(), policy=email.policy.default)
    assert from_domain(msg) is None
    assert not sender_verified(msg, trusted=(MX,))


def test_unbalanced_comment_is_doubt() -> None:
    assert not ok(message(f"{MX} (broken; dmarc=pass header.from=acme.test"))


def test_too_many_headers_is_doubt() -> None:
    many = [f"{MX}; dmarc=pass header.from=acme.test"] * (MAX_HEADERS + 1)
    assert not ok(message(*many))


def test_too_long_a_header_is_doubt() -> None:
    with pytest.raises(Unreadable):
        read_header(f"{MX}; dmarc=pass header.from=acme.test " + "x" * 9_000)


# --- alignment ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("signer", "author", "expected"),
    [
        ("acme.test", "acme.test", True),
        ("mail.acme.test", "acme.test", True),
        ("acme.test", "mail.acme.test", True),
        ("badacme.test", "acme.test", False),
        ("a.acme.test", "b.acme.test", False),  # siblings: no Public Suffix List, no guess
        ("", "acme.test", False),
    ],
)
def test_alignment(signer: str, author: str, expected: bool) -> None:
    assert aligned(signer, author) is expected


def test_reading_a_header() -> None:
    header = read_header(GMAIL.replace("\r\n", ""))
    assert header.authserv_id == "mx.google.com"
    assert [(r.method, r.result) for r in header.results] == [
        ("dkim", "pass"),
        ("spf", "pass"),
        ("dmarc", "pass"),
    ]
    assert read_header(M365.replace("\r\n", "")).authserv_id is None


def test_quoted_values_and_escapes_are_kept_whole() -> None:
    header = read_header(
        f'{MX}; dmarc=pass reason="all \\"good\\" (really); ok" header.from="acme.test"'
    )
    assert [(r.method, r.result) for r in header.results] == [("dmarc", "pass")]
    assert header.results[0].properties["header.from"] == "acme.test"


def test_a_comment_with_an_escaped_parenthesis() -> None:
    assert ok(message(f"{MX} (a \\) b); dmarc=pass header.from=acme.test"))


def test_none_means_no_results() -> None:
    assert read_header(f"{MX}; none").results == ()
    assert not ok(message(f"{MX}; none"))


@pytest.mark.parametrize(
    "value",
    [
        f"{MX}) ; dmarc=pass header.from=acme.test",  # a closing parenthesis with no opening
        f'{MX}; dmarc=pass reason="unterminated',  # an unterminated quoted string
        "",  # nothing at all
        f"{MX}; dmarc= header.from=acme.test",  # a result without its value
    ],
)
def test_unreadable_headers(value: str) -> None:
    with pytest.raises(Unreadable):
        read_header(value)


def test_dkim_identity_without_a_domain_tag() -> None:
    assert ok(message(f"{MX}; spf=pass; dkim=pass header.i=@acme.test"))


def test_an_unreadable_header_anywhere_is_doubt() -> None:
    assert not ok(message(f"{MX}; dmarc=pass header.from=acme.test", f"{MX}) ; dmarc=pass"))


# --- quoted values never become results or properties (lane B's review of #485) ---------------


def test_a_quoted_reason_naming_a_domain_does_not_sign_for_it() -> None:
    header = f'{MX}; spf=pass; dkim=pass reason="ok header.d=acme.test" header.d=evil.test'
    assert not ok(message(header))


def test_a_quoted_reason_naming_the_from_domain_does_not_pass_dmarc() -> None:
    header = f'{MX}; dmarc=pass reason="x header.from=acme.test" header.from=evil.test'
    assert not ok(message(header))


def test_an_escaped_quote_cannot_open_a_forged_result() -> None:
    header = f'{MX}; dmarc=fail reason="a\\";dmarc=pass header.from=acme.test"'
    assert not ok(message(header))
    assert [(r.method, r.result) for r in read_header(header).results] == [("dmarc", "fail")]


def test_a_second_value_of_one_property_is_doubt() -> None:
    header = f"{MX}; spf=pass; dkim=pass header.d=acme.test header.d=evil.test"
    assert not ok(message(header))
    with pytest.raises(Unreadable):
        read_header(header)


def test_a_stray_word_is_doubt() -> None:
    with pytest.raises(Unreadable):
        read_header(f"{MX}; dmarc=pass header.from=acme.test trailing")


def test_a_legitimate_quoted_reason_with_spaces_still_verifies() -> None:
    header = f'{MX}; dmarc=pass reason="aligned; all good (yes)" header.from=acme.test'
    assert ok(message(header))


@pytest.mark.parametrize(
    "value",
    [
        f'{MX}; dkim=pass header.d=ac"me.test"',  # a quote inside a bare value
        f'{MX}; dkim=pass header.d="acme.test"x',  # text after the closing quote
        f"{MX} not-a-version; dmarc=pass header.from=acme.test",  # the id's second word
        f'{MX}; "dmarc"=pass',  # a quoted name
    ],
)
def test_misplaced_quotes_and_words_are_doubt(value: str) -> None:
    with pytest.raises(Unreadable):
        read_header(value)


def test_the_id_may_carry_a_version() -> None:
    assert read_header(f"{MX} 1; dmarc=pass header.from=acme.test").authserv_id == MX
