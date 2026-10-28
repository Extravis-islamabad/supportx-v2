"""Labels on the server (D-100 D7, ADR-034): the UI's label dictionary, for text the server writes.

Exports, report emails and notifications must show the same words as the screens (CLAUDE.md
rule d). `resources.json` is generated from `frontend/packages/labels` (`make labels-json`) and
a test on each side fails when it is out of date, so there is one dictionary, never a copy.

    label("priority.p1", "ar")                       -> the Arabic label
    label("errors.report_timeout", "en", seconds=30) -> "{{seconds}}" filled in
    label("licence.days_left", "ar", count=3)        -> the `_few` plural of Arabic

A language without the key falls back to English (as the UI does); a key missing everywhere is a
programming error and raises, so tests catch it instead of a code reaching a user.
"""

import json
import re
from functools import cache
from pathlib import Path
from typing import Final

LANGUAGES: Final = ("en", "ar", "ur")
FALLBACK: Final = "en"
RTL_LANGUAGES: Final = frozenset({"ar", "ur"})
# Unicode isolates (FSI ... PDI): a value filled into right-to-left text keeps its own order, so a
# date, a time zone or a Latin name never reorders its parts (QA WP-035 BUG-04).
FSI: Final = "\u2068"
PDI: Final = "\u2069"
_FILE = Path(__file__).with_name("resources.json")
_PARAM = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_ARABIC_FEW = range(3, 11)
_ARABIC_MANY = range(11, 100)


class MissingLabelError(LookupError):
    """No language has this key."""


@cache
def _dictionary() -> dict[str, dict[str, str]]:
    loaded: dict[str, dict[str, str]] = json.loads(_FILE.read_text(encoding="utf-8"))
    return loaded


def plural_category(language: str, count: int) -> str:
    """CLDR plural category of `count` (integers) for the languages SupportX ships."""
    if language != "ar":
        return "one" if count == 1 else "other"
    exact = {0: "zero", 1: "one", 2: "two"}
    if count in exact:
        return exact[count]
    rest = abs(count) % 100
    if rest in _ARABIC_FEW:
        return "few"
    return "many" if rest in _ARABIC_MANY else "other"


def has_label(key: str) -> bool:
    """Whether any language has `key` (or its plural forms)."""
    english = _dictionary()[FALLBACK]
    return key in english or f"{key}_other" in english


def _lookup(key: str, language: str, count: int | None) -> str:
    languages = (language, FALLBACK) if language != FALLBACK else (FALLBACK,)
    for lang in languages:
        resource = _dictionary().get(lang, {})
        if count is not None:
            for candidate in (f"{key}_{plural_category(lang, count)}", f"{key}_other"):
                if candidate in resource:
                    return resource[candidate]
        if key in resource:
            return resource[key]
    raise MissingLabelError(key)


def label(key: str, language: str, **params: object) -> str:
    """The label of `key` in `language` (falling back to English), with `{{params}}` filled.

    `count=<int>` also picks the plural form, like i18next does in the UI. In Arabic and Urdu
    every filled value is wrapped in Unicode isolates (FSI/PDI), as the console does.
    """
    count = params.get("count")
    text = _lookup(
        key,
        language if language in LANGUAGES else FALLBACK,
        count if isinstance(count, int) else None,
    )
    rtl = language in RTL_LANGUAGES

    def fill(match: re.Match[str]) -> str:
        if match.group(1) not in params:
            return match.group(0)
        value = str(params[match.group(1)])
        return f"{FSI}{value}{PDI}" if rtl else value

    return _PARAM.sub(fill, text)


__all__ = [
    "FSI",
    "LANGUAGES",
    "PDI",
    "RTL_LANGUAGES",
    "MissingLabelError",
    "has_label",
    "label",
    "plural_category",
]
