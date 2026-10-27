"""Rules for the person record that need no database (WP-021, REQ-ADM-002..004)."""

import re
from collections.abc import Mapping
from zoneinfo import available_timezones

LOCALES = frozenset({"en", "ar", "ur"})
REQUEST_VISIBILITY = frozenset({"site"})
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9 ()./-]{3,30}$")
_ZONES = frozenset(available_timezones())

# Field → longest allowed text. Longer values are refused, never cut (D-091).
LENGTHS: dict[str, int] = {
    "first_name": 100,
    "last_name": 100,
    "display_name": 200,
    "email": 254,
    "employee_id": 50,
    "job_title": 200,
    "description": 5000,
    "phone": 50,
    "mobile": 50,
}
TEXT_FIELDS = frozenset(LENGTHS)
UUID_FIELDS = frozenset({"site_id", "department_id", "manager_id"})
# What an admin edits on the person record (the user's own preferences stay in directory.py).
PERSON_FIELDS = TEXT_FIELDS | UUID_FIELDS | {"vip", "locale", "time_zone", "request_visibility"}

Problem = tuple[str, str, dict[str, str | int | float | bool | None]]  # (field, code, params)


def clean_text(value: object) -> str | None:
    """Trimmed text, None when empty."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def full_name(first_name: str, last_name: str | None) -> str:
    """The display name of a person without a custom one: "first last"."""
    return f"{first_name} {last_name}" if last_name else first_name


def person_problems(values: Mapping[str, object]) -> list[Problem]:  # noqa: C901 - one rule per field
    """Checks for the fields present in `values` (already trimmed by `clean_text`)."""
    problems: list[Problem] = []
    if "first_name" in values and not values["first_name"]:
        problems.append(("first_name", "required", {}))
    for field, longest in LENGTHS.items():
        value = values.get(field)
        if isinstance(value, str) and len(value) > longest:
            problems.append((field, "value_too_long", {"max_length": longest}))
    email = values.get("email")
    if isinstance(email, str) and email and not _EMAIL.fullmatch(email):
        problems.append(("email", "email_not_valid", {}))
    for field in ("phone", "mobile"):
        phone = values.get(field)
        if isinstance(phone, str) and phone and not _PHONE.fullmatch(phone):
            problems.append((field, "phone_not_valid", {}))
    locale = values.get("locale")
    if "locale" in values and locale not in LOCALES:
        problems.append(("locale", "invalid_choice", {}))
    zone = values.get("time_zone")
    if isinstance(zone, str) and zone not in _ZONES:
        problems.append(("time_zone", "unknown_time_zone", {}))
    visibility = values.get("request_visibility")
    if visibility is not None and visibility not in REQUEST_VISIBILITY:
        problems.append(("request_visibility", "invalid_choice", {}))
    if "vip" in values and not isinstance(values["vip"], bool):
        problems.append(("vip", "invalid_choice", {}))
    return problems
