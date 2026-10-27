"""Search normalisation and query words (WP-027, ADR-029): pure, no database."""

import pytest

from app.shared.search import normalize, words
from app.shared.search.domain import LETTERS_FROM, LETTERS_TO, MAX_WORD_LENGTH, MAX_WORDS


def test_letter_tables_line_up() -> None:
    assert len(LETTERS_FROM) == len(LETTERS_TO)


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("أَحْمَد", "احمد"),  # harakat, hamza
        ("إحمد", "احمد"),  # hamza below
        ("آلة", "اله"),  # madda; teh marbuta
        ("مـــر", "مر"),  # tatweel
        ("کی", "كي"),  # Urdu kaf and yeh
        ("ہھے", "ههي"),  # Urdu heh forms, yeh barree
        ("١٢۳", "123"),  # Arabic-Indic and Urdu digits
        ("Café RÉSUMÉ", "cafe resume"),  # accents and case
        ("ﻻ", "لا"),  # presentation-form ligature lam-alef
        ("a\u200bb‌c", "abc"),  # zero-width characters
    ],
)
def test_normalize(typed: str, stored: str) -> None:
    assert normalize(typed) == stored


def test_words_split_dedupe_and_cap() -> None:
    assert words("  Printer, printer; DOWN!! ") == ["printer", "down"]
    assert words("INC-12") == ["inc", "12"]
    assert words("___ ... !!!") == []
    assert len(words(" ".join(f"w{i}" for i in range(20)))) == MAX_WORDS
    assert words("x" * 80) == ["x" * MAX_WORD_LENGTH]
    # Diacritics never split a word in two.
    assert words("طَابِعَة") == ["طابعه"]
