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
import unicodedata
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Final

from markupsafe import Markup, escape

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


# Directional isolates (U+2066..U+2069). A value that starts with an isolate is already isolated.
_ISOLATES = re.compile("[\u2066-\u2069]")
_OPENERS = ("\u2066", "\u2067", FSI)
# Display IDs and thread tokens ("INC-12", "[INC-12]") stay as typed: they are matched and pasted.
_TOKEN = re.compile(r"^\[?[A-Z]{2,10}-\d{1,12}\]?$")


def strip_isolates(text: str) -> str:
    """Text without directional isolates: a pasted "INC-12" with marks still matches."""
    return _ISOLATES.sub("", text)


def _has_rtl_letters(text: str) -> bool:
    return any(unicodedata.bidirectional(char) in {"R", "AL"} for char in text)


def isolate(value: object, language: str) -> str:
    """A filled value as shown on screen: isolated (FSI…PDI) when its direction can differ.

    The rule (also in the console, packages/labels): a string is wrapped when the sentence is
    right-to-left (ar, ur) or the value has right-to-left letters (bidi class R or AL). Numbers,
    display IDs and values already isolated are left as they are.
    """
    if not isinstance(value, str):
        return str(value)
    if not value or value.startswith(_OPENERS) or _TOKEN.match(value):
        return value
    if language in RTL_LANGUAGES or _has_rtl_letters(value):
        return f"{FSI}{value}{PDI}"
    return value


def _plain(value: object) -> str:
    return str(value)


def _lookup_for(key: str, language: str, params: dict[str, object]) -> str:
    count = params.get("count")
    return _lookup(
        key,
        language if language in LANGUAGES else FALLBACK,
        count if isinstance(count, int) else None,
    )


def _render(
    key: str, language: str, params: dict[str, object], fill_one: Callable[[object], str]
) -> str:
    text = _lookup_for(key, language, params)
    if _PARAM.fullmatch(text.strip()):
        # The value is the whole label: nothing around it to keep apart from.
        fill_one = _plain

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            return match.group(0)
        return str(params[name]) if name == "count" else fill_one(params[name])

    return _PARAM.sub(fill, text)


def label(key: str, language: str, **params: object) -> str:
    """The label of `key` in `language` (falling back to English), with `{{params}}` filled.

    `count=<int>` also picks the plural form, like i18next does in the UI. A filled value is
    wrapped in Unicode isolates (FSI/PDI) when its direction can differ from the sentence's (see
    `isolate`), as the console does: a Latin name in Arabic, an Arabic name in English. For text
    that leaves the screen (e-mail subjects and plain text, exported files) use `plain_label`.
    """
    return _render(key, language, params, lambda value: isolate(value, language))


def plain_label(key: str, language: str, **params: object) -> str:
    """`label` with no directional marks at all.

    For e-mail subjects and plain-text parts (marks break thread tokens like "[INC-12]" and show
    in older clients) and exported files (a file is data).
    """
    return strip_isolates(_render(key, language, params, str))


def html_label(key: str, language: str, **params: object) -> Markup:
    """`label` for an e-mail's HTML part: the text escaped, each filled value in `<bdi>`.

    `<bdi>` isolates a value in HTML without invisible characters, which the plain-text part and
    the subject must not carry (see `plain_label`).
    """

    def fill_one(value: object) -> Markup:
        text = strip_isolates(str(value))
        if isolate(text, language) == text or not isinstance(value, str):
            return escape(text)
        return Markup("<bdi>{}</bdi>").format(text)

    parts = _PARAM.split(_lookup_for(key, language, params))
    # _PARAM has one group: even items are text, odd items are parameter names.
    out = Markup("")
    for index, part in enumerate(parts):
        if index % 2 == 0:
            out += escape(part)
        elif part in params:
            out += escape(str(params[part])) if part == "count" else fill_one(params[part])
        else:
            out += escape("{{" + part + "}}")
    return out


__all__ = [
    "FSI",
    "LANGUAGES",
    "PDI",
    "RTL_LANGUAGES",
    "MissingLabelError",
    "has_label",
    "html_label",
    "isolate",
    "label",
    "plain_label",
    "plural_category",
    "strip_isolates",
]
