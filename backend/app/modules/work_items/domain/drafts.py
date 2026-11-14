"""Kept drafts of unsent create forms (WP-046a S5c; REQ-INC-019). Pure, no I/O.

Lane B's conditions shape the rules here:

1. Only the forms named in `FORMS` keep a server draft; any other key is refused (422), so no
   client can make up keys and rows.
2. A draft is at most `BODY_MAX` bytes of values, checked before sealing.
3. A draft holds form values only: text, numbers, yes/no, and lists of those. Nothing that names
   a file. What it holds is never trusted input: restored into the form, it is checked again by
   the record's own create when the person sends it.
"""

import json
from datetime import timedelta
from typing import Any

FORMS: dict[str, str] = {"incident-new": "incident"}  # form key -> the work item type it makes
BODY_MAX = 64 * 1024
KEPT_FOR = timedelta(days=30)
MAX_KEYS = 200
_FILE_WORDS = frozenset({"file", "attachment"})


class DraftRefused(ValueError):
    """Values a draft may not hold; the code is the field problem."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


NOT_VALUES = "draft_not_values"
TOO_LARGE = "draft_too_large"
# The field codes a refused draft gives (labels: errors.field.*; checked in test_domain).
FIELD_PROBLEMS = frozenset({TOO_LARGE, NOT_VALUES})


def _plain(value: Any) -> bool:  # noqa: ANN401 - JSON
    if value is None or isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list):
        return all(item is None or isinstance(item, bool | int | float | str) for item in value)
    if isinstance(value, dict):  # custom field values: one level of plain values
        return all(isinstance(k, str) and _plain_scalar_or_list(v) for k, v in value.items())
    return False


def _plain_scalar_or_list(value: Any) -> bool:  # noqa: ANN401 - JSON
    if isinstance(value, list):
        return all(item is None or isinstance(item, bool | int | float | str) for item in value)
    return value is None or isinstance(value, bool | int | float | str)


def checked(values: Any) -> str:  # noqa: ANN401 - the request's JSON
    """The values as the JSON text to seal; DraftRefused when they are not plain form values."""
    if not isinstance(values, dict) or len(values) > MAX_KEYS:
        raise DraftRefused(NOT_VALUES)
    for key, value in values.items():
        if not isinstance(key, str) or any(word in key.lower() for word in _FILE_WORDS):
            raise DraftRefused(NOT_VALUES)
        if not _plain(value):
            raise DraftRefused(NOT_VALUES)
    text = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > BODY_MAX:
        raise DraftRefused(TOO_LARGE)
    return text


def form_type(form_key: str) -> str | None:
    """The work item type a known form makes, or None for a key that keeps no draft."""
    return FORMS.get(form_key)
