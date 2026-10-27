"""The language a system e-mail is written in (mail_recipients, WP-035 scheduled reports)."""

import pytest

from app.modules.identity_access.service.directory import _mail_language


@pytest.mark.parametrize(
    ("code", "language"),
    [
        ("ar", "ar"),
        ("ar-SA", "ar"),  # regional codes from imports or Keycloak keep their language
        ("UR-pk", "ur"),
        ("en-GB", "en"),
        ("fr", "en"),  # a language we do not write mail in falls back to English
        (None, "en"),
        ("", "en"),
    ],
)
def test_mail_language_uses_the_language_part_of_the_code(code: str | None, language: str) -> None:
    assert _mail_language(code) == language
