"""Catalog administration rules (WP-031 s1; REQ-CAT-001, -002, -005, -006, -024; no I/O).

Categories form a tree (at most MAX_DEPTH levels, no loops). Items move through
draft → published → retired, by hand or at a scheduled time; only published items are offered.
Publishing needs an English name and a fulfilment group (plan D9). Every text has an English
value (the fallback); the other tenant languages are listed when missing (D5). Rules return
codes; the labels say the words.
"""

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.modules.service_catalog.domain.items import (
    LANGUAGES,
    NAME_MAX,
    Problem,
    Question,
    name_problems,
)

MAX_DEPTH = 4
SUMMARY_MAX = 300
DESCRIPTION_MAX = 20_000  # sanitised HTML, per language
MAX_KEYWORDS = 20
KEYWORD_MAX = 40
MAX_EXTRA_CATEGORIES = 5
SUBJECT_TEMPLATE_MAX = 200
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class ItemStatus(StrEnum):
    """An item's life (REQ-CAT-024): drafted, offered, then no longer offered."""

    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class ItemKind(StrEnum):
    """What choosing the entry raises (REQ-CAT-003): a service request, or an incident."""

    SERVICE = "service"
    INCIDENT_TEMPLATE = "incident_template"


# A fixed set (no uploads): the console and portal draw each code with their own icon.
ICONS = frozenset(
    {
        "account",
        "access",
        "laptop",
        "monitor",
        "phone",
        "software",
        "mail",
        "network",
        "vpn",
        "printer",
        "building",
        "desk",
        "badge",
        "people",
        "document",
        "leave",
        "onboarding",
        "offboarding",
        "security",
        "help",
        "problem",
        "money",
        "travel",
        "tools",
    }
)


def category_problems(
    category_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
    parents: Mapping[uuid.UUID, uuid.UUID | None],
) -> list[Problem]:
    """The new parent exists, makes no loop and keeps the tree within MAX_DEPTH levels.

    `parents` maps every live category of the tenant to its parent (before this change).
    `category_id` is None for a new category. Its own subtree moves with it, so the deepest
    category below it counts too.
    """
    if parent_id is None:
        return []
    if parent_id not in parents:
        return [("parent_id", "not_found")]
    above = 1  # the parent's level, counting from 1 at the root
    seen: set[uuid.UUID] = set()
    node: uuid.UUID | None = parent_id
    while node is not None:
        if node == category_id or node in seen:
            return [("parent_id", "category_loop")]
        seen.add(node)
        node = parents.get(node)
        if node is not None:
            above += 1
    below = 0 if category_id is None else _height(category_id, parents)
    if above + 1 + below > MAX_DEPTH:
        return [("parent_id", "too_deep")]
    return []


def _height(category_id: uuid.UUID, parents: Mapping[uuid.UUID, uuid.UUID | None]) -> int:
    """Levels below a category (0 for a leaf)."""
    children: dict[uuid.UUID, list[uuid.UUID]] = {}
    for child, parent in parents.items():
        if parent is not None:
            children.setdefault(parent, []).append(child)
    best, stack = 0, [(category_id, 0)]
    seen: set[uuid.UUID] = set()
    while stack:
        node, depth = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        best = max(best, depth)
        stack += [(c, depth + 1) for c in children.get(node, ())]
    return best


def hidden_categories(
    disabled: Iterable[uuid.UUID], parents: Mapping[uuid.UUID, uuid.UUID | None]
) -> set[uuid.UUID]:
    """A disabled category hides everything below it from requesters (plan D1)."""
    off = set(disabled)
    hidden: set[uuid.UUID] = set()
    for node in parents:
        cursor: uuid.UUID | None = node
        seen: set[uuid.UUID] = set()
        while cursor is not None and cursor not in seen:
            if cursor in off:
                hidden.add(node)
                break
            seen.add(cursor)
            cursor = parents.get(cursor)
    return hidden


def text_problems(at: str, texts: Mapping[str, Any] | None, *, limit: int) -> list[Problem]:
    """Optional text per language (JSON from the API): known languages, within `limit`."""
    found: list[Problem] = []
    for lang, text in (texts or {}).items():
        if lang not in LANGUAGES:
            found.append((f"{at}.{lang}", "invalid_choice"))
        elif not isinstance(text, str):
            found.append((f"{at}.{lang}", "invalid_text"))
        elif len(text) > limit:
            found.append((f"{at}.{lang}", "value_too_long"))
    return found


def keyword_problems(keywords: Mapping[str, Sequence[str]] | None) -> list[Problem]:
    """Keywords and synonyms per language (search finds the item by them, plan D12)."""
    found: list[Problem] = []
    for lang, words in (keywords or {}).items():
        at = f"keywords.{lang}"
        if lang not in LANGUAGES:
            found.append((at, "invalid_choice"))
        elif len(words) > MAX_KEYWORDS:
            found.append((at, "too_many_keywords"))
        elif any(not w.strip() or len(w) > KEYWORD_MAX for w in words):
            found.append((at, "invalid_value"))
    return found


def icon_problems(at: str, icon: str | None) -> list[Problem]:
    """One of the fixed icons, or none."""
    return [] if icon is None or icon in ICONS else [(at, "invalid_choice")]


def subject_template_problems(template: str | None, questions: Sequence[Question]) -> list[Problem]:
    """Placeholders name the form's questions, or `person` (the requested-for person)."""
    if template is None:
        return []
    if len(template) > SUBJECT_TEMPLATE_MAX:
        return [("subject_template", "value_too_long")]
    keys = {q.key for q in questions} | {"person"}
    for name in _PLACEHOLDER.findall(template):
        if not _KEY.fullmatch(name) or name not in keys:
            return [("subject_template", "unknown_placeholder")]
    return []


def subject_from(
    template: str, answers: Mapping[str, Any], *, person: str, words: Mapping[str, str]
) -> str:
    """The request's subject from the template (`Access to {system} for {person}`).

    `words` holds the shown words of choice answers (codes never reach a subject). A missing
    answer leaves its placeholder empty; the result is trimmed to the subject's limit.
    """

    def fill(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "person":
            return person
        value = answers.get(key)
        if isinstance(value, bool) or value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(words.get(str(v), str(v)) for v in value)
        return words.get(str(value), str(value))

    return " ".join(_PLACEHOLDER.sub(fill, template).split())[:SUBJECT_TEMPLATE_MAX]


@dataclass(frozen=True)
class PublishFacts:
    """What publishing an item depends on."""

    names: Mapping[str, str]
    kind: ItemKind
    group_id: uuid.UUID | None
    category_id: uuid.UUID | None
    template_id: uuid.UUID | None


def publish_problems(facts: PublishFacts) -> list[Problem]:
    """Why an item may not be published yet (plan D3, D5, D9)."""
    found = name_problems("names", facts.names, required=True)
    if facts.category_id is None:
        found.append(("category_id", "required"))
    if facts.kind is ItemKind.SERVICE and facts.group_id is None:
        found.append(("group_id", "required"))
    if facts.kind is ItemKind.INCIDENT_TEMPLATE and facts.template_id is None:
        found.append(("template_id", "required"))
    return found


def schedule_problems(
    status: ItemStatus, publish_at: datetime | None, retire_at: datetime | None, now: datetime
) -> list[Problem]:
    """A planned publish is for a draft and in the future; retiring comes after publishing."""
    found: list[Problem] = []
    if publish_at is not None:
        if status is not ItemStatus.DRAFT:
            found.append(("publish_at", "not_allowed"))
        elif publish_at <= now:
            found.append(("publish_at", "must_be_future"))
    if retire_at is not None:
        if status is ItemStatus.RETIRED:
            found.append(("retire_at", "not_allowed"))
        elif retire_at <= now:
            found.append(("retire_at", "must_be_future"))
        elif publish_at is not None and retire_at <= publish_at:
            found.append(("retire_at", "before_publish"))
    return found


def due_status(
    status: ItemStatus, publish_at: datetime | None, retire_at: datetime | None, now: datetime
) -> ItemStatus:
    """What the schedule makes of an item at `now` (the schedule job applies it)."""
    if status is ItemStatus.DRAFT and publish_at is not None and publish_at <= now:
        status = ItemStatus.PUBLISHED
    if status is ItemStatus.PUBLISHED and retire_at is not None and retire_at <= now:
        status = ItemStatus.RETIRED
    return status


def missing_translations(
    texts: Mapping[str, Mapping[str, str] | None], languages: Sequence[str]
) -> list[tuple[str, str]]:
    """(field, language) for every text with an English value but none in a tenant language.

    `texts` maps each field path ("names", "questions.0.label") to its values per language.
    Requesters see English where a language is missing (plan D5).
    """
    wanted = [lang for lang in languages if lang != "en" and lang in LANGUAGES]
    found: list[tuple[str, str]] = []
    for at, given in texts.items():
        values = given or {}
        if not (values.get("en") or "").strip():
            continue
        found += [(at, lang) for lang in wanted if not (values.get(lang) or "").strip()]
    return found


def copy_names(names: Mapping[str, str], prefix: Mapping[str, str]) -> dict[str, str]:
    """The names of a copy ("Copy of …" per language, within NAME_MAX)."""
    return {
        lang: f"{prefix.get(lang, prefix['en'])} {text}"[:NAME_MAX]
        for lang, text in names.items()
        if text
    }


__all__ = [
    "ICONS",
    "MAX_DEPTH",
    "ItemKind",
    "ItemStatus",
    "PublishFacts",
    "category_problems",
    "copy_names",
    "due_status",
    "hidden_categories",
    "icon_problems",
    "keyword_problems",
    "missing_translations",
    "publish_problems",
    "schedule_problems",
    "subject_from",
    "subject_template_problems",
    "text_problems",
]
