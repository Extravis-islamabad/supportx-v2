"""Reply and resolution template text (WP-046a S5a; REQ-INC-041, REQ-INC-042), without I/O.

A template's text is sanitised rich text in which `{{ record.title }}` names a variable of the
type's one catalogue (the same names and labels notifications use). Filling it puts each
variable's value in its place, escaped as text; a variable with no value reads as a clear
placeholder ("not set" in the reader's language), never the variable's name (AC3). A name the
catalogue does not offer is refused when the template is saved, so filling never meets one.
"""

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from html import escape

LANGUAGES = ("en", "ar", "ur")
NAME_MAX = 120
SUBJECT_MAX = 200
BODY_MAX = 100_000
GROUPS_MAX = 50
CATEGORIES_MAX = 50
_TOKEN = re.compile(r"\{\{\s*([a-z_]+(?:\.[a-z_]+)*)\s*\}\}")


class TemplateKind(StrEnum):
    """Where a template is offered."""

    REPLY = "reply"  # the conversation composer (REQ-INC-041)
    RESOLUTION = "resolution"  # the resolution editor (REQ-INC-042)


class TemplateVisibility(StrEnum):
    """Whose a template is."""

    PERSONAL = "personal"  # its owner's only; nobody else reads it, administrators included
    SHARED = "shared"  # everyone (or the listed groups) may use it; the settings right writes it


def variables_in(text: str) -> list[str]:
    """The variable names `text` uses, in order, each once."""
    return list(dict.fromkeys(m.group(1) for m in _TOKEN.finditer(text)))


def unknown_variables(text: str, offered: Iterable[str]) -> list[str]:
    """Names `text` uses that the catalogue does not offer, in order."""
    known = set(offered)
    return [name for name in variables_in(text) if name not in known]


def fill(text: str, values: Mapping[str, str | None], not_set: str) -> str:
    """`text` with every variable replaced by its value as escaped text, or `not_set`."""

    def value(match: re.Match[str]) -> str:
        found = values.get(match.group(1))
        return escape(found) if found else escape(not_set)

    return _TOKEN.sub(value, text)


def pick_language(bodies: Mapping[str, str], wanted: Iterable[str | None]) -> str | None:
    """The first of `wanted` the template has, else any it has (REQ-INC-041 AC2)."""
    for language in wanted:
        if language is not None and bodies.get(language):
            return language
    return next((lang for lang in LANGUAGES if bodies.get(lang)), next(iter(bodies), None))


__all__ = [
    "BODY_MAX",
    "CATEGORIES_MAX",
    "GROUPS_MAX",
    "LANGUAGES",
    "NAME_MAX",
    "SUBJECT_MAX",
    "TemplateKind",
    "TemplateVisibility",
    "fill",
    "pick_language",
    "unknown_variables",
    "variables_in",
]
