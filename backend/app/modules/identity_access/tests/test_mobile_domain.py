"""Mobile sign-in rules (ADR-044): challenge format, verifier check, the app's return address."""

import base64
import hashlib

import pytest

from app.modules.identity_access.domain.mobile import (
    MobileStart,
    app_return,
    challenge_for,
    valid_app_version,
    valid_challenge,
    verifier_matches,
)

VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 appendix B


def test_the_challenge_is_the_rfc_7636_s256_value() -> None:
    assert challenge_for(VERIFIER) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    digest = hashlib.sha256(VERIFIER.encode()).digest()
    assert challenge_for(VERIFIER) == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def test_only_43_base64url_characters_are_a_challenge() -> None:
    assert valid_challenge(challenge_for(VERIFIER))
    for bad in ("", "short", "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM=", "a" * 44, "+" * 43):
        assert not valid_challenge(bad), bad


def test_the_verifier_must_be_the_one_the_challenge_came_from() -> None:
    challenge = challenge_for(VERIFIER)
    assert verifier_matches(VERIFIER, challenge)
    assert not verifier_matches(VERIFIER[:-1] + "Y", challenge)
    assert not verifier_matches("too-short", challenge)
    assert not verifier_matches(VERIFIER + " ", challenge)  # outside the RFC alphabet


@pytest.mark.parametrize(
    ("redirect", "expected"),
    [
        ("https://sx.example.com/mobile/auth", "https://sx.example.com/mobile/auth?handoff=abc"),
        (
            "https://sx.example.com/mobile/auth?tenant=x",
            "https://sx.example.com/mobile/auth?tenant=x&handoff=abc",
        ),
    ],
)
def test_the_app_return_address_carries_the_code(redirect: str, expected: str) -> None:
    assert app_return(redirect, handoff="abc") == expected
    assert app_return("https://sx.example.com/mobile/auth", auth_error="login_failed") == (
        "https://sx.example.com/mobile/auth?auth_error=login_failed"
    )


def test_only_digits_and_dots_are_an_app_version() -> None:
    for good in ("1", "1.4", "1.4.2", "2026.11.10.3"):
        assert valid_app_version(good), good
    for bad in ("", "1.", "v1.4", "1.4.2-beta", "<b>1</b>", "1.2.3.4.5", "12345"):
        assert not valid_app_version(bad), bad


def test_a_mobile_start_survives_the_pending_login_and_a_second_round() -> None:
    start = MobileStart(challenge_for(VERIFIER), "android", "1.0.0")
    assert MobileStart.from_pending(start.pending()) == start
    assert start.query() == {
        "mobile_challenge": challenge_for(VERIFIER),
        "mobile_platform": "android",
        "mobile_version": "1.0.0",
    }
    assert MobileStart(challenge_for(VERIFIER)).query() == {
        "mobile_challenge": challenge_for(VERIFIER)
    }
    assert MobileStart.from_pending({"app": "console"}) is None  # a web sign-in
