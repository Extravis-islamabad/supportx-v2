"""Custom fields: types, definitions and value rules (WP-026; REQ-INC-014, REQ-ADM-041).

Pure domain code, no I/O. A definition says what a field is (type, labels and help per
language, choices, default, validation); values are stored in the record's typed JSON column
(architecture.md §6.6). Every value is checked here, on the server, whatever path it came by
(form, API, rules later). A definition that could never work is refused when it is saved
(REQ-WI-009 AC4). The key is stable and made once from the English name; screens never show it
(REQ-INC-014 AC3), only the API view does.
"""

import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

LABEL_MAX = 120
HELP_MAX = 500
TEXT_MAX = 250
LONG_TEXT_MAX = 10_000
OPTION_MAX = 100
FIELDS_PER_ENTITY = 100
KEY_MAX = 40
NUMBER_LIMIT = Decimal(10) ** 15
LANGUAGES = frozenset({"en", "ar", "ur"})
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
# A repeated group that itself repeats, such as (a+)+ or (\w*)*: patterns run on every save, and
# these can backtrack for minutes on a short text. Refused when the field is defined.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*}][^()]*\)\s*[+*{]")
# A letter or digit in any script (\w without the underscore).
_NAMED = re.compile(r"[^\W_]")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9 ()./-]{3,30}$")
_URL = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class FieldType(StrEnum):
    """What a custom field holds."""

    TEXT = "text"
    LONG_TEXT = "long_text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    CURRENCY = "currency"
    DATE = "date"
    DATETIME = "datetime"
    CHOICE = "choice"
    MULTI_CHOICE = "multi_choice"
    YES_NO = "yes_no"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    PERSON = "person"


# Free text a person typed: what search reads (D-087; choices are codes, people are IDs).
SEARCHABLE = frozenset(
    {FieldType.TEXT, FieldType.LONG_TEXT, FieldType.EMAIL, FieldType.PHONE, FieldType.URL}
)
CHOICES = frozenset({FieldType.CHOICE, FieldType.MULTI_CHOICE})
NUMBERS = frozenset({FieldType.INTEGER, FieldType.DECIMAL, FieldType.CURRENCY})
TEXTS = frozenset({FieldType.TEXT, FieldType.LONG_TEXT})


class ChoiceDisplay(StrEnum):
    """How a single choice is shown on forms."""

    LIST = "list"
    RADIO = "radio"


class CustomFieldEntity(StrEnum):
    """Records that carry custom fields (only incidents exist yet; others join as they come)."""

    INCIDENT = "incident"


# entity → the permission that lets someone see the entity's fields (forms need them).
VIEW_PERMISSION: Mapping[CustomFieldEntity, str] = {CustomFieldEntity.INCIDENT: "incidents.view"}
# Where each entity's records (and their `custom` values) live: for the index worker (D-088).
ENTITY_TABLE: Mapping[CustomFieldEntity, str] = {CustomFieldEntity.INCIDENT: "work_items"}


class IndexState(StrEnum):
    """Promotion to an index (REQ-INC-014 AC2), built by the index worker (D-087, D-088)."""

    NONE = "none"
    PENDING = "pending"
    BUILDING = "building"
    ACTIVE = "active"
    FAILED = "failed"


class IndexFailure(StrEnum):
    """Why an index could not be built, as admins read it; the database's text is only logged."""

    TIMED_OUT = "timed_out"
    BUSY = "busy"
    DISK_FULL = "disk_full"
    OUT_OF_MEMORY = "out_of_memory"
    VALUE_TOO_LARGE = "value_too_large"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class Choice:
    """One value of a choice field. Retired: kept for old records, not offered."""

    code: str
    labels: Mapping[str, str]
    retired: bool = False


@dataclass(frozen=True)
class Validation:
    """Optional rules beyond the type."""

    required: bool = False
    min: Decimal | None = None
    max: Decimal | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None


@dataclass(frozen=True)
class Definition:
    """A custom field as rules see it."""

    key: str
    type: FieldType
    choices: Sequence[Choice] = field(default_factory=tuple)
    validation: Validation = field(default_factory=Validation)
    retired: bool = False

    def choice_codes(self, *, offered_only: bool) -> set[str]:
        """Codes of the choices (offered only: without the retired ones)."""
        return {c.code for c in self.choices if not (offered_only and c.retired)}


Problem = tuple[str, str]  # (path, code)


def empty(value: Any) -> bool:  # noqa: ANN401 - any JSON value
    """No value: None, empty text or an empty list."""
    return value is None or value in ("", [])


# --- keys -----------------------------------------------------------------------------------------


def key_from(name: str, taken: set[str]) -> str:
    """A stable key from an English name: "Contract type" → contract_type (then _2, _3 ...)."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[: KEY_MAX - 4] or "field"
    if not slug[0].isalpha():
        slug = f"f_{slug}"[: KEY_MAX - 4]
    if len(slug) < 2:  # noqa: PLR2004 - keys are at least two characters
        slug = f"{slug}_f"
    key, n = slug, 2
    while key in taken:
        key, n = f"{slug}_{n}", n + 1
    return key


def is_key(value: str) -> bool:
    """A valid stable key (lowercase letters, digits and _, starting with a letter)."""
    return _KEY.fullmatch(value) is not None


# --- values ---------------------------------------------------------------------------------------


def _number(value: Any) -> Decimal | None:  # noqa: ANN401 - JSON value
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or abs(number) >= NUMBER_LIMIT:
        return None
    return number


# Own codes: `invalid_email` is already the mail module's (it lists the addresses).
_FORMAT_PROBLEM: Mapping[FieldType, str] = {
    FieldType.EMAIL: "email_not_valid",
    FieldType.PHONE: "phone_not_valid",
    FieldType.URL: "url_not_valid",
}


def clean_value(  # noqa: C901, PLR0911, PLR0912 - one rule per type, flat
    definition: Definition,
    value: Any,  # noqa: ANN401 - JSON value
    *,
    current: Any = None,  # noqa: ANN401 - the record's value now (a retired choice may stay)
) -> tuple[Any, list[str]]:
    """The value as stored (JSON), plus problem codes. Empty values clean to None."""
    kind = definition.type
    if empty(value):
        return None, []
    if kind in TEXTS or kind in {FieldType.EMAIL, FieldType.PHONE, FieldType.URL}:
        if not isinstance(value, str):
            return None, ["invalid_value"]
        text = value.strip() if kind != FieldType.LONG_TEXT else value.strip("\n ")
        if kind != FieldType.LONG_TEXT:
            text = " ".join(text.split())
        if not text:
            return None, []
        limit = LONG_TEXT_MAX if kind == FieldType.LONG_TEXT else TEXT_MAX
        rules = definition.validation
        if len(text) > (rules.max_length or limit) or len(text) > limit:
            return text, ["value_too_long"]
        if rules.min_length is not None and len(text) < rules.min_length:
            return text, ["value_too_short"]
        checks = {FieldType.EMAIL: _EMAIL, FieldType.PHONE: _PHONE, FieldType.URL: _URL}
        if kind in checks and not checks[kind].fullmatch(text):
            return text, [_FORMAT_PROBLEM[kind]]
        if rules.pattern and not re.fullmatch(rules.pattern, text):
            return text, ["pattern_mismatch"]
        return text, []
    if kind in NUMBERS:
        number = _number(value)
        if number is None:
            return None, ["invalid_value"]
        if kind == FieldType.INTEGER and number != number.to_integral_value():
            # Never rounded quietly: the person is told (QA BUG-03).
            return None, ["whole_number_required"]
        rules = definition.validation
        if rules.min is not None and number < rules.min:
            return None, ["below_minimum"]
        if rules.max is not None and number > rules.max:
            return None, ["above_maximum"]
        # Stored as a JSON number (whole numbers as int), so filters can compare numerically.
        return (int(number) if number == number.to_integral_value() else float(number)), []
    if kind == FieldType.DATE:
        try:
            return date.fromisoformat(str(value)).isoformat(), []
        except ValueError:
            return None, ["invalid_value"]
    if kind == FieldType.DATETIME:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return None, ["invalid_value"]
        if moment.tzinfo is None:
            return None, ["timezone_required"]
        # Stored in UTC: one text order, one cast result for every session (filters, indexes).
        return moment.astimezone(UTC).isoformat(), []
    if kind == FieldType.YES_NO:
        return (value, []) if isinstance(value, bool) else (None, ["invalid_value"])
    if kind == FieldType.CHOICE:
        offered = definition.choice_codes(offered_only=True)
        if not isinstance(value, str):
            return None, ["invalid_choice"]
        if value in offered or value == current:
            return value, []
        return None, ["invalid_choice"]
    if kind == FieldType.MULTI_CHOICE:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return None, ["invalid_choice"]
        kept = set(current) if isinstance(current, list) else set()
        offered = definition.choice_codes(offered_only=True) | kept
        codes = list(dict.fromkeys(value))  # once each, in the order given
        if any(code not in offered for code in codes):
            return None, ["invalid_choice"]
        return codes, []
    if kind == FieldType.PERSON:
        try:
            return str(uuid.UUID(str(value))), []
        except ValueError:
            return None, ["invalid_value"]
    return None, ["invalid_value"]  # pragma: no cover - every type is handled above


def clean_values(
    definitions: Mapping[str, Definition],
    values: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[Problem]]:
    """Cleaned values by key (None = cleared) and problems as (`custom.<key>`, code)."""
    current = current or {}
    cleaned: dict[str, Any] = {}
    problems: list[Problem] = []
    for key, raw in values.items():
        definition = definitions.get(key)
        if definition is None:
            problems.append((f"custom.{key}", "unknown_field"))
            continue
        if definition.retired and raw != current.get(key) and not empty(raw):
            problems.append((f"custom.{key}", "field_retired"))
            continue
        value, codes = clean_value(definition, raw, current=current.get(key))
        problems += [(f"custom.{key}", code) for code in codes]
        if not codes:
            cleaned[key] = value
    return cleaned, problems


def missing_required(
    definitions: Mapping[str, Definition],
    values: Mapping[str, Any],
    *,
    creating: bool,
    current: Mapping[str, Any] | None = None,
) -> list[Problem]:
    """Fields required by their own definition.

    On create every active required field must have a value; on later edits a required field
    can never be emptied, but one made required later blocks nothing else (as D-086 for
    templates).
    """
    current = current or {}
    problems: list[Problem] = []
    for key, definition in definitions.items():
        if not definition.validation.required or definition.retired:
            continue
        emptied = key in values and empty(values[key]) and not empty(current.get(key))
        if (creating and empty(values.get(key))) or (not creating and emptied):
            problems.append((f"custom.{key}", "required"))
    return problems


# --- definitions ----------------------------------------------------------------------------------


def labels_problems(raw: Any, path: str, *, required: bool, limit: int) -> list[Problem]:  # noqa: ANN401, PLR0911 - JSON; one rule per check
    """Translations {en, ar, ur}: English required where asked, known languages, lengths."""
    if raw is None:
        return [(path, "english_label_required")] if required else []
    if not isinstance(raw, Mapping):
        return [(path, "invalid_value")]
    if set(raw) - LANGUAGES:
        return [(path, "unknown_language")]
    if required and not str(raw.get("en") or "").strip():
        return [(path, "english_label_required")]
    if any(str(v).strip() and not _NAMED.search(str(v)) for v in raw.values()):
        # A name of punctuation only says nothing on a form (QA BUG-05).
        return [(path, "name_needs_letters")]
    if any(len(str(v)) > limit for v in raw.values()):
        return [(path, "value_too_long")]
    return []


def definition_problems(  # noqa: C901, PLR0912 - one rule per setting, flat
    kind: FieldType,
    *,
    choices: Sequence[Choice],
    validation: Validation,
    default: Any,  # noqa: ANN401 - JSON value
    currency: str | None,
) -> list[Problem]:
    """A definition that could never work (REQ-WI-009 AC4)."""
    problems: list[Problem] = []
    if kind in CHOICES:
        if not [c for c in choices if not c.retired]:
            problems.append(("choices", "choices_required"))
        codes = [c.code for c in choices]
        if len(codes) != len(set(codes)) or any(not is_key(c) for c in codes):
            problems.append(("choices", "invalid_choice"))
        if len(choices) > OPTION_MAX:
            problems.append(("choices", "too_many_items"))
        for i, choice in enumerate(choices):
            problems += labels_problems(
                choice.labels, f"choices[{i}].labels", required=True, limit=LABEL_MAX
            )
    elif choices:
        problems.append(("choices", "not_allowed"))
    if (validation.min is not None or validation.max is not None) and kind not in NUMBERS:
        problems.append(("validation", "not_allowed"))
    if (
        validation.min is not None
        and validation.max is not None
        and validation.min > validation.max
    ):
        problems.append(("validation.max", "invalid_range"))
    lengths = (validation.min_length, validation.max_length)
    if any(n is not None for n in lengths) and kind not in TEXTS:
        problems.append(("validation", "not_allowed"))
    if any(n is not None and n < 0 for n in lengths):
        problems.append(("validation", "invalid_range"))
    if (
        validation.min_length is not None
        and validation.max_length is not None
        and validation.min_length > validation.max_length
    ):
        problems.append(("validation.max_length", "invalid_range"))
    if validation.pattern is not None:
        if kind not in TEXTS:
            problems.append(("validation.pattern", "not_allowed"))
        else:
            try:
                re.compile(validation.pattern)
            except re.error:
                problems.append(("validation.pattern", "invalid_pattern"))
            else:
                if _NESTED_QUANTIFIER.search(validation.pattern):
                    problems.append(("validation.pattern", "pattern_too_complex"))
    if kind == FieldType.CURRENCY:
        if currency is None or not _CURRENCY.fullmatch(currency):
            problems.append(("currency", "invalid_currency"))
    elif currency is not None:
        problems.append(("currency", "not_allowed"))
    if not empty(default):
        if kind == FieldType.PERSON:
            problems.append(("default", "no_default_allowed"))
        else:
            probe = Definition(key="probe", type=kind, choices=choices, validation=validation)
            _, codes = clean_value(probe, default)
            problems += [("default", code) for code in codes]
    return problems


# Addresses and numbers are also searched by their parts ("ops", "example", "1234567"): the
# search vector keeps an email or a web address as one token (QA BUG-02).
_PARTS = re.compile(r"[@./:?#=&_+\-()]+")
_SPLIT = frozenset({FieldType.EMAIL, FieldType.URL, FieldType.PHONE})


def search_text(definitions: Mapping[str, Definition], values: Mapping[str, Any]) -> str:
    """The free text a record's custom values add to search (`work_items.custom_text`)."""
    texts: list[str] = []
    for key, definition in definitions.items():
        value = values.get(key)
        if definition.type not in SEARCHABLE or not isinstance(value, str):
            continue
        texts.append(value)
        if definition.type in _SPLIT:
            texts.append(" ".join(_PARTS.sub(" ", value).split()))
    return " ".join(texts)


def problem_params(definition: Definition, code: str) -> dict[str, str | int]:
    """The limit a value problem names ("Maximum is 1000.5", QA BUG-03 and C3)."""
    rules = definition.validation
    if code == "above_maximum" and rules.max is not None:
        return {"max": str(rules.max)}
    if code == "below_minimum" and rules.min is not None:
        return {"min": str(rules.min)}
    if code == "value_too_short" and rules.min_length is not None:
        return {"min": rules.min_length}
    if code == "value_too_long":
        limit = LONG_TEXT_MAX if definition.type == FieldType.LONG_TEXT else TEXT_MAX
        return {"max": min(rules.max_length or limit, limit)}
    return {}


# Every field problem code this module returns (errors.field.<code> labels, checked in CI by
# tests/test_error_labels.py, which reads FIELD_PROBLEMS sets).
FIELD_PROBLEMS = frozenset(
    {
        "above_maximum",
        "below_minimum",
        "choices_required",
        "duplicate_name",
        "email_not_valid",
        "english_label_required",
        "field_retired",
        "invalid_choice",
        "invalid_currency",
        "invalid_key",
        "invalid_pattern",
        "invalid_range",
        "invalid_value",
        "key_cannot_change",
        "no_default_allowed",
        "not_allowed",
        "order_must_list_every_value",
        "name_needs_letters",
        "pattern_mismatch",
        "pattern_too_complex",
        "phone_not_valid",
        "required",
        "timezone_required",
        "too_many_items",
        "type_cannot_change",
        "unknown_field",
        "unknown_language",
        "url_not_valid",
        "user_not_found",
        "value_too_long",
        "value_too_short",
        "whole_number_required",
    }
)
