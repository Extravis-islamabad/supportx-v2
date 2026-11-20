"""Webhook signing (WP-057 S5a; the coordinator's conditions): known-answer vectors.

The expected values were computed independently with `openssl dgst -sha256 -hmac`, not by this
module, so a change to the scheme fails here.
"""

import pytest

from app.shared.crypto.signing import (
    OFFERED_MAX,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign,
    signature,
    verify,
)

KEY_1 = b"whsec_test_key_1"
KEY_2 = b"whsec_test_key_2"
BODY = b'{"seq":1}'
AT = 1_700_000_000
# printf '1700000000.{"seq":1}' | openssl dgst -sha256 -hmac 'whsec_test_key_1'
SIGNED_WITH_1 = "e492df0ed038246be254be51577e594a0c3e3c0f1f977c8a09b088ccee5c0a45"
SIGNED_WITH_2 = "7af78ab6dde1f5a26040e87ec45e9c681e3a82abcde7413ff7c0132cf7343238"
# printf '1700000300.' | openssl dgst -sha256 -hmac 'whsec_test_key_1' (an empty body)
EMPTY_AT_300 = "849c2f0125b895ece2ecfa20b0b1f7ccd145ac72e35542c7be4777b1d79f6022"


def test_known_answers() -> None:
    assert signature([KEY_1], AT, BODY) == f"v1={SIGNED_WITH_1}"
    assert signature([KEY_1], AT + 300, b"") == f"v1={EMPTY_AT_300}"
    assert sign([KEY_1], AT, BODY) == {
        TIMESTAMP_HEADER: str(AT),
        SIGNATURE_HEADER: f"v1={SIGNED_WITH_1}",
    }


def test_a_rotation_signs_with_both_secrets_and_either_verifies() -> None:
    headers = sign([KEY_1, KEY_2], AT, BODY)
    assert headers[SIGNATURE_HEADER] == f"v1={SIGNED_WITH_1},v1={SIGNED_WITH_2}"
    assert verify([KEY_2], headers, BODY, now=AT)  # the receiver already on the new secret
    assert verify([KEY_1], headers, BODY, now=AT)  # or still on the old one


def test_verify_refuses_a_changed_body_a_wrong_secret_or_a_stale_time() -> None:
    headers = sign([KEY_1], AT, BODY)
    assert verify([KEY_1], headers, BODY, now=AT + 299)
    assert not verify([KEY_1], headers, b'{"seq":2}', now=AT)
    assert not verify([KEY_2], headers, BODY, now=AT)
    assert not verify([KEY_1], headers, BODY, now=AT + 301)  # outside the five minutes
    assert not verify([KEY_1], headers, BODY, now=AT - 301)


def test_verify_refuses_another_version_or_missing_headers() -> None:
    assert not verify(
        [KEY_1], {TIMESTAMP_HEADER: str(AT), SIGNATURE_HEADER: f"v0={SIGNED_WITH_1}"}, BODY, now=AT
    )
    assert not verify([KEY_1], {SIGNATURE_HEADER: f"v1={SIGNED_WITH_1}"}, BODY, now=AT)
    assert not verify(
        [KEY_1], {TIMESTAMP_HEADER: "soon", SIGNATURE_HEADER: f"v1={SIGNED_WITH_1}"}, BODY, now=AT
    )
    # Header names are case-insensitive, as HTTP says.
    lower = {TIMESTAMP_HEADER.lower(): str(AT), SIGNATURE_HEADER.lower(): f"v1={SIGNED_WITH_1}"}
    assert verify([KEY_1], lower, BODY, now=AT)


def test_signing_needs_a_secret() -> None:
    with pytest.raises(ValueError, match="at least one secret"):
        signature([], AT, BODY)


def test_verify_takes_only_plain_digits_and_a_few_offered_values() -> None:
    """Lane B (5): " 1700000000", "+1700000000" and "1_700_000_000" are refused."""
    good = sign([KEY_1], AT, BODY)[SIGNATURE_HEADER]
    for odd in (f" {AT}", f"+{AT}", "1_700_000_000", "٣٤٥", ""):
        assert not verify([KEY_1], {TIMESTAMP_HEADER: odd, SIGNATURE_HEADER: good}, BODY, now=AT)
    # Only the first OFFERED_MAX values count: a right one buried past them is not looked at.
    padded = ",".join(["v1=00"] * OFFERED_MAX + [good])
    assert not verify([KEY_1], {TIMESTAMP_HEADER: str(AT), SIGNATURE_HEADER: padded}, BODY, now=AT)
