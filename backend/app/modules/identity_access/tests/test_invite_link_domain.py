"""A copied invite link, the person's side: token shape and Keycloak's refusals (REQ-SEC-021)."""

import secrets

import pytest

from app.modules.identity_access.domain import invite_link
from app.modules.identity_access.domain.password_policy import MAX_LENGTH


def test_a_copied_token_has_its_shape_and_nothing_else_is_looked_up() -> None:
    assert invite_link.token_shape_ok(secrets.token_urlsafe(32))
    for wrong in ("", "short", "a" * 44, "a" * 42 + "=", "a" * 42 + "/", "a" * 42 + " "):
        assert not invite_link.token_shape_ok(wrong)


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("invalidPasswordMinLengthMessage", "password_too_short"),
        ("invalidPasswordHistoryMessage", "password_used_before"),
        ("invalidPasswordBlacklistedMessage", "password_breached"),
        (" invalidPasswordNotEmailMessage ", "password_is_email"),
        ("somethingNewInKeycloak", "password_rejected"),  # never shown raw
        ("", "password_rejected"),
        (None, "password_rejected"),
    ],
)
def test_keycloaks_refusals_become_labelled_codes(message: str | None, code: str) -> None:
    assert invite_link.refusal(message) == code


def test_a_password_longer_than_keycloak_hashes_is_refused_first() -> None:
    assert not invite_link.too_long("x" * MAX_LENGTH)
    assert invite_link.too_long("x" * (MAX_LENGTH + 1))
