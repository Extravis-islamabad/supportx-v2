"""Mobile sign-in rules (ADR-042): challenge format, verifier check, the app's return address."""

import base64
import hashlib

import pytest

from app.modules.identity_access.domain.mobile import (
    app_return,
    challenge_for,
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
        ("supportx://auth", "supportx://auth?handoff=abc"),
        ("supportx://auth?tenant=x", "supportx://auth?tenant=x&handoff=abc"),
    ],
)
def test_the_app_return_address_carries_the_code(redirect: str, expected: str) -> None:
    assert app_return(redirect, handoff="abc") == expected
    assert app_return("supportx://auth", auth_error="login_failed") == (
        "supportx://auth?auth_error=login_failed"
    )
