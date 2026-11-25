"""The tenant's mobile app policy rules (WP-057 S6b; REQ-SEC-047), with no I/O."""

import pytest

from app.modules.identity_access.domain.mobile import (
    REFUSAL_MESSAGE_MAX,
    UNLOCK_AFTER_MAX,
    UNLOCK_AFTER_MIN,
    MobilePolicy,
    clean_message,
    policy_problems,
    refusal_message,
)


def test_with_nothing_set_the_app_may_sign_in_and_clears_its_data_at_sign_out() -> None:
    """Lane B's condition 2: the no-row defaults."""
    policy = MobilePolicy()
    assert (policy.allowed, policy.clear_on_sign_out) == (True, True)
    assert (policy.mfa_required, policy.device_unlock_required) == (False, False)
    assert policy.refusal_message is None


def test_the_message_is_plain_text_on_one_line_and_capped() -> None:
    assert clean_message("  Use the\nweb   app\tinstead. ") == "Use the web app instead."
    # Control and direction characters never reach the phone (a spoofed right-to-left override).
    assert clean_message("Ask\u202e IT\u200b\x07 desk") == "Ask IT desk"
    assert len(clean_message("x" * (REFUSAL_MESSAGE_MAX + 50))) == REFUSAL_MESSAGE_MAX
    assert clean_message("<b>bold</b>") == "<b>bold</b>"  # never interpreted: the app shows text


def test_the_persons_language_then_the_tenant_default_then_the_built_in_text() -> None:
    policy = MobilePolicy(
        allowed=False, refusal_message={"en": "Use the web app.", "ar": "استخدم تطبيق الويب."}
    )
    assert refusal_message(policy, "ar", "en") == "استخدم تطبيق الويب."
    assert refusal_message(policy, "ur", "en") == "Use the web app."  # the tenant's default
    assert refusal_message(MobilePolicy(allowed=False), "en", "en") is None  # the built-in text
    blank = MobilePolicy(allowed=False, refusal_message={"en": "   "})
    assert refusal_message(blank, "en", "en") is None


@pytest.mark.parametrize(
    ("values", "problem"),
    [
        ({"unlock_after_minutes": UNLOCK_AFTER_MIN - 1}, ("unlock_after_minutes", "out_of_range")),
        ({"unlock_after_minutes": UNLOCK_AFTER_MAX + 1}, ("unlock_after_minutes", "out_of_range")),
        ({"unlock_after_minutes": True}, ("unlock_after_minutes", "out_of_range")),
        ({"refusal_message": {"fr": "Non"}}, ("refusal_message", "invalid")),
        ({"refusal_message": {"en": 5}}, ("refusal_message", "invalid")),
        ({"refusal_message": "Use the web"}, ("refusal_message", "invalid")),
        (
            {"refusal_message": {"en": "x" * (REFUSAL_MESSAGE_MAX + 1)}},
            ("refusal_message", "too_long"),
        ),
    ],
)
def test_a_policy_out_of_bounds_is_refused(
    values: dict[str, object], problem: tuple[str, str]
) -> None:
    assert policy_problems(values) == [problem]


def test_a_policy_in_bounds_has_no_problems() -> None:
    assert policy_problems({"unlock_after_minutes": 5, "refusal_message": {"ur": "ویب ایپ"}}) == []
