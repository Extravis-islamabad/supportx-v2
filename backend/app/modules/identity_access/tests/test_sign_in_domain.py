"""The sign-in log's words, pure (REQ-AUD-015; domain/sign_in.py)."""

import pytest

from app.modules.identity_access.domain.sign_in import (
    OTHER_REASON,
    SignInOutcome,
    device,
    keycloak_outcome,
    keycloak_reason,
)

CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
EDGE_WIN = CHROME_WIN + " Edg/131.0.0.0"
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (CHROME_WIN, "chrome:windows"),
        (EDGE_WIN, "edge:windows"),  # Edge also says Chrome: the first match wins
        (SAFARI_IPHONE, "safari:ios"),  # an iPhone also says "Mac OS X"
        (FIREFOX_LINUX, "firefox:linux"),
        ("SupportXMobile/1.4.0 (Android 15)", "supportx_app:android"),
        ("curl/8.7.1", None),  # nothing we know: no device, never the raw header
        (None, None),
        ("", None),
    ],
)
def test_the_device_is_a_short_code_never_the_raw_header(
    agent: str | None, expected: str | None
) -> None:
    assert device(agent) == expected


def test_keycloak_errors_become_our_reasons_and_unknown_ones_other() -> None:
    assert keycloak_reason("invalid_user_credentials") == "wrong_password"
    assert keycloak_reason("identity_provider_error") == "identity_provider_refused"
    assert keycloak_reason("something_new_in_keycloak_27") == OTHER_REASON
    assert keycloak_reason(None) is None


@pytest.mark.parametrize(
    ("event_type", "error", "outcome"),
    [
        ("LOGIN", None, SignInOutcome.SUCCESS),
        ("LOGIN_ERROR", "invalid_user_credentials", SignInOutcome.FAILED),
        ("LOGIN_ERROR", "user_temporarily_disabled", SignInOutcome.LOCKED),
        ("LOGIN_ERROR", "invalid_totp", SignInOutcome.MFA_FAILED),
        ("IDENTITY_PROVIDER_LOGIN_ERROR", "identity_provider_error", SignInOutcome.FAILED),
        ("LOGOUT", None, SignInOutcome.SIGNED_OUT),
    ],
)
def test_keycloak_events_map_to_outcomes(
    event_type: str, error: str | None, outcome: SignInOutcome
) -> None:
    assert keycloak_outcome(event_type, error) is outcome
