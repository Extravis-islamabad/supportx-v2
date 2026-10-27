"""Tenant branding rules (WP-017): contrast checks, nearest passing colours, texts, login CSS."""

import pytest

from app.modules.organization.domain.branding import (
    AA,
    DEFAULT_COLOURS,
    CheckCode,
    Colours,
    TextField,
    contrast,
    nearest_passing_gradient,
    nearest_passing_primary,
    normalise_hex,
    parse_hex,
    text_for,
    text_problems,
    worst_on_gradient,
)
from app.modules.organization.domain.login_css import LoginLogos, login_css


def test_the_supportx_default_passes_every_check() -> None:
    assert DEFAULT_COLOURS.passes
    assert DEFAULT_COLOURS.primary == "#7e40d1"  # D-078, generated from palette.json


@pytest.mark.parametrize(
    ("given", "expected"),
    [("#7E40D1", "#7e40d1"), (" #abc ", "#aabbcc"), ("7e40d1", None), ("#12345g", None)],
)
def test_colours_are_normalised_or_refused(given: str, expected: str | None) -> None:
    assert normalise_hex(given) == expected


def test_a_light_primary_fails_white_text_and_names_the_check() -> None:
    yellow = Colours("#ffd60a", ("#ffd60a", "#ffd60a"))
    failed = {check.code for check in yellow.checks() if not check.passed}
    assert CheckCode.TEXT_ON_PRIMARY in failed
    assert CheckCode.TEXT_ON_GRADIENT in failed
    assert not yellow.passes


def test_the_nearest_passing_primary_is_a_darker_shade_that_passes() -> None:
    suggestion = nearest_passing_primary("#1e90ff")  # dodger blue: white text 3.3:1
    assert suggestion is not None
    assert suggestion != "#1e90ff"
    assert all(check.passed for check in Colours(suggestion, (suggestion, suggestion)).checks())
    # The closest: one step lighter fails.
    assert sum(parse_hex(suggestion)) < sum(parse_hex("#1e90ff"))


def test_a_passing_primary_is_its_own_nearest() -> None:
    assert nearest_passing_primary("#7e40d1") == "#7e40d1"


def test_the_nearest_passing_gradient_gives_white_text_aa_along_it() -> None:
    start, end = nearest_passing_gradient(("#7fdbff", "#ffdc00")) or ("", "")
    assert worst_on_gradient((start, end)) >= AA


def test_contrast_is_symmetric_and_bounded() -> None:
    assert contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21)
    assert contrast((255, 255, 255), (0, 0, 0)) == pytest.approx(21)


def test_texts_need_english_known_locales_and_a_length_limit() -> None:
    problems = text_problems(TextField.PRODUCT_NAME, {"ar": "دعم", "fr": "Support"})
    codes = {(p.field, p.code) for p in problems}
    assert ("product_name.fr", "unknown_language") in codes
    assert ("product_name.en", "english_text_required") in codes
    long = text_problems(TextField.PORTAL_NAME, {"en": "x" * 61})
    assert [(p.code, p.params) for p in long] == [("value_too_long", {"max": 60})]
    assert text_problems(TextField.WELCOME_TEXT, {"en": "  ", "ar": ""}) == []


def test_text_falls_back_to_english() -> None:
    assert text_for({"en": "Help", "ar": "مساعدة"}, "ar") == "مساعدة"
    assert text_for({"en": "Help"}, "ur") == "Help"
    assert text_for({}, "en") is None


def test_login_css_carries_the_colours_and_logos_and_refuses_unsafe_urls() -> None:
    css = login_css(
        Colours("#0b5394", ("#0b5394", "#073763")),
        LoginLogos("/a/logo.png?v=1", "/a/logo-dark.png?v=1", "/a/logo-hc.png?v=1"),
    )
    assert "--pf-v5-global--primary-color--100: #0b5394;" in css
    assert 'url("/a/logo-dark.png?v=1")' in css
    with pytest.raises(ValueError, match="evil"):
        login_css(DEFAULT_COLOURS, LoginLogos('evil")', "/b", "/c"))
