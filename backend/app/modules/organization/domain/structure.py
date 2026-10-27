"""Rules for sites, departments and groups that need no database (WP-021)."""

import re
import uuid
from collections.abc import Mapping
from zoneinfo import available_timezones

LANGUAGES = frozenset({"en", "ar", "ur"})
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9 ()./-]{3,30}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$")
_ZONES = frozenset(available_timezones())

Problem = tuple[str, str]  # (field, code)


def text(value: object) -> str | None:
    """Trimmed text, None when empty."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def detail_problems(values: Mapping[str, object]) -> list[Problem]:
    """Checks shared by sites, groups and departments for the fields that are present."""
    problems: list[Problem] = []
    email = values.get("email")
    if isinstance(email, str) and email and not _EMAIL.fullmatch(email):
        problems.append(("email", "email_not_valid"))
    phone = values.get("phone")
    if isinstance(phone, str) and phone and not _PHONE.fullmatch(phone):
        problems.append(("phone", "phone_not_valid"))
    zone = values.get("time_zone")
    if isinstance(zone, str) and zone and zone not in _ZONES:
        problems.append(("time_zone", "unknown_time_zone"))
    language = values.get("default_language")
    if isinstance(language, str) and language and language not in LANGUAGES:
        problems.append(("default_language", "invalid_choice"))
    code = values.get("code")
    if isinstance(code, str) and code and not _CODE.fullmatch(code):
        problems.append(("code", "invalid_code"))
    return problems


def ancestor_loop(
    unit_id: uuid.UUID, parent_id: uuid.UUID | None, parents: Mapping[uuid.UUID, uuid.UUID | None]
) -> list[uuid.UUID] | None:
    """The loop that making `parent_id` the parent of `unit_id` would close, else None.

    `parents` maps every unit to its current parent. The loop is returned from `unit_id` round
    to it again, so the message can name it (REQ-ADM-039 AC3, REQ-ADM-035 AC1).
    """
    if parent_id is None:
        return None
    path = [unit_id]
    current: uuid.UUID | None = parent_id
    seen = {unit_id}
    while current is not None:
        path.append(current)
        if current == unit_id:
            return path
        if current in seen:  # an existing loop elsewhere: not this change's doing
            return None
        seen.add(current)
        current = parents.get(current)
    return None
