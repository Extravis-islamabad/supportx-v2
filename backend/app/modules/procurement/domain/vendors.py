"""Vendor fields and their rules (REQ-PUR-001), pure: no I/O."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

NAME_MAX = 200
TEXT_MAX = 2000
SHORT_MAX = 120
URL_MAX = 300
EMAIL_MAX = 254

CURRENCY = re.compile(r"^[A-Z]{3}$")
# One address, plainly shaped: the mail module checks deliverability when it sends.
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^[0-9+()\-.\s]{3,40}$")
WEBSITE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)

# The text fields, with their limits; blank text is stored as NULL.
TEXT_FIELDS: Mapping[str, int] = {
    "contact_person": SHORT_MAX,
    "address": TEXT_MAX,
    "description": TEXT_MAX,
    "email": EMAIL_MAX,
    "phone": SHORT_MAX,
    "fax": SHORT_MAX,
    "website": URL_MAX,
}
FIELDS = ("name", "currency", "is_active", *TEXT_FIELDS)


@dataclass(frozen=True, slots=True)
class Problem:
    """One refusal: the field, a code (`errors.field.<code>`) and its params."""

    field: str
    code: str
    params: Mapping[str, Any] = dataclass_field(default_factory=dict)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()) if not isinstance(value, str) else value.strip()
    return text or None


_PATTERNS = {"email": EMAIL, "phone": PHONE, "fax": PHONE, "website": WEBSITE}


def _clean_text_fields(
    values: Mapping[str, Any], cleaned: dict[str, Any], problems: list[Problem]
) -> None:
    for name, limit in TEXT_FIELDS.items():
        if name not in values:
            continue
        text = _text(values[name])
        if text is not None and len(text) > limit:
            problems.append(Problem(name, "value_too_long", {"max": limit}))
            continue
        pattern = _PATTERNS.get(name)
        if text is not None and pattern is not None and not pattern.match(text):
            problems.append(Problem(name, f"invalid_{'phone' if name == 'fax' else name}"))
            continue
        cleaned[name] = text


def clean_vendor(values: Mapping[str, Any]) -> tuple[dict[str, Any], list[Problem]]:
    """The sent fields, trimmed (blank → None), and what is wrong with them."""
    cleaned: dict[str, Any] = {}
    problems: list[Problem] = []
    if "name" in values:
        name = _text(values["name"])
        if name is None:
            problems.append(Problem("name", "required"))
        elif len(name) > NAME_MAX:
            problems.append(Problem("name", "value_too_long", {"max": NAME_MAX}))
        else:
            cleaned["name"] = " ".join(name.split())
    if "currency" in values:
        currency = _text(values["currency"])
        if currency is not None and not CURRENCY.match(currency):
            problems.append(Problem("currency", "invalid_currency"))
        else:
            cleaned["currency"] = currency
    if "is_active" in values:
        cleaned["is_active"] = bool(values["is_active"])
    _clean_text_fields(values, cleaned, problems)
    return cleaned, problems
