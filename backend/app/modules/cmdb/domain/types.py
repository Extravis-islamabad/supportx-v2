"""CI types, their attributes, states and the values a CI holds (WP-053 S1). Pure: no I/O.

- **Attributes** (REQ-CMDB-001): each CI type defines attribute definitions; a CI holds the
  values of its own type's and every ancestor type's attributes (inherited down the tree).
  Definitions live on the type (`cmdb_ci_types.attributes`), not in the metadata module: the
  metadata module's custom fields are scoped per entity, not per type subtree (lane B's S1
  choice, reported to lane C). A definition can never be `sensitive` yet: no seal port exists
  for the CMDB (`custom_field_sensitive_unsupported`, the coordinator, 2026-11-16).
- **Changing type** (REQ-CMDB-003): the values whose attribute the new type does not hold are
  lost; the preview lists them by key.
- **States** (REQ-CMDB-004): `active` or `end_of_life`; end-of-life CIs are kept out of pickers
  when the tenant says so (REQ-CMDB-031).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

API_NAME = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
NAME_MAX = 200
DESCRIPTION_MAX = 10000
ATTRIBUTES_MAX = 100  # per type
CHOICES_MAX = 100
TEXT_MAX = 2000
LANGUAGES = ("en", "ar", "ur")
TYPE_DEPTH_MAX = 8  # how deep the type tree may go

# Every field code this module's checks give (labelled `errors.field.<code>`; the label check
# reads this set, tests/test_error_labels.py).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "invalid_value",
        "invalid_choice",
        "invalid_key",
        "duplicate",
        "too_many",
        "value_too_long",
        "not_found",
        "unknown_language",
        "unknown_attribute",
        "custom_field_sensitive_unsupported",
        "cmdb_ci_type_loop",
        "cmdb_ci_type_too_deep",
    }
)
# Problem codes (labelled `errors.<code>` / `errors.field.<code>`).
SENSITIVE_UNSUPPORTED = "custom_field_sensitive_unsupported"
TYPE_IN_USE = "cmdb_ci_type_in_use"
STATE_IN_USE = "cmdb_ci_state_in_use"
TYPE_LOOP = "cmdb_ci_type_loop"
TYPE_TOO_DEEP = "cmdb_ci_type_too_deep"
BUILT_IN = "cmdb_built_in_locked"
NOT_FOUND = "cmdb_ci_not_found"
TYPE_NOT_FOUND = "cmdb_ci_type_not_found"
STATE_NOT_FOUND = "cmdb_ci_state_not_found"
ASSET_HAS_CI = "cmdb_asset_has_ci"


class CiAttributeType(StrEnum):
    """What kind of value an attribute holds (`cmdb_attribute_type.<code>`)."""

    TEXT = "text"
    LONG_TEXT = "long_text"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    CHOICE = "choice"


class CiStateCategory(StrEnum):
    """`cmdb_state_category.<code>`."""

    ACTIVE = "active"
    END_OF_LIFE = "end_of_life"


class CiSource(StrEnum):
    """Where a CI came from (`cmdb_ci_source.<code>`)."""

    MANUAL = "manual"
    ASSET_SYNC = "asset_sync"
    IMPORT = "import"
    MONETX = "monetx"


class CiImpact(StrEnum):
    """Business impact and criticality (`cmdb_impact.<code>`)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Built-in types (labelled `cmdb_ci_type.<code>`) and their parents, made for each tenant the
# first time its CMDB is used. Original to SupportX; a tenant adds its own below any of them.
BUILT_IN_TYPES: tuple[tuple[str, str | None, str], ...] = (
    ("business_service", None, "service"),
    ("application", None, "app"),
    ("database", "application", "database"),
    ("hardware", None, "hardware"),
    ("server", "hardware", "server"),
    ("workstation", "hardware", "laptop"),
    ("network_device", "hardware", "network"),
    ("printer", "hardware", "printer"),
)
# Built-in states (`cmdb_ci_state.<code>`), in their order.
BUILT_IN_STATES: tuple[tuple[str, CiStateCategory], ...] = (
    ("planned", CiStateCategory.ACTIVE),
    ("in_use", CiStateCategory.ACTIVE),
    ("under_maintenance", CiStateCategory.ACTIVE),
    ("retired", CiStateCategory.END_OF_LIFE),
)
DEFAULT_STATE = "in_use"


@dataclass(frozen=True)
class Problem:
    """One refused value: the field it is about and a code."""

    field: str
    code: str


def _names_problems(names: object, where: str, *, required: bool) -> list[Problem]:
    if names is None or names == {}:
        return [Problem(where, "required")] if required else []
    if not isinstance(names, Mapping):
        return [Problem(where, "invalid_value")]
    problems: list[Problem] = []
    for language, text in names.items():
        if language not in LANGUAGES:
            problems.append(Problem(f"{where}.{language}", "unknown_language"))
        elif not isinstance(text, str) or not text.strip() or len(text) > NAME_MAX:
            problems.append(Problem(f"{where}.{language}", "invalid_value"))
    if required and not str(names.get("en", "")).strip():
        problems.append(Problem(f"{where}.en", "required"))
    return problems


def attribute_problems(attributes: object) -> list[Problem]:  # noqa: C901 - one rule per part, flat
    """Problems of a type's attribute definitions (keys unique, types known, never sensitive)."""
    if not isinstance(attributes, list):
        return [Problem("attributes", "invalid_value")]
    if len(attributes) > ATTRIBUTES_MAX:
        return [Problem("attributes", "too_many")]
    problems: list[Problem] = []
    seen: set[str] = set()
    for index, definition in enumerate(attributes):
        where = f"attributes[{index}]"
        if not isinstance(definition, Mapping):
            problems.append(Problem(where, "invalid_value"))
            continue
        key = definition.get("key")
        if not isinstance(key, str) or not API_NAME.fullmatch(key):
            problems.append(Problem(f"{where}.key", "invalid_key"))
        elif key in seen:
            problems.append(Problem(f"{where}.key", "duplicate"))
        else:
            seen.add(key)
        if definition.get("type") not in {t.value for t in CiAttributeType}:
            problems.append(Problem(f"{where}.type", "invalid_choice"))
        if definition.get("sensitive"):
            # No seal port for the CMDB yet (the coordinator, 2026-11-16): refused, never stored.
            problems.append(Problem(f"{where}.sensitive", SENSITIVE_UNSUPPORTED))
        problems += _names_problems(definition.get("names"), f"{where}.names", required=True)
        if definition.get("type") == CiAttributeType.CHOICE:
            choices = definition.get("choices")
            if (
                not isinstance(choices, list)
                or not choices
                or len(choices) > CHOICES_MAX
                or not all(isinstance(c, str) and API_NAME.fullmatch(c) for c in choices)
                or len(set(choices)) != len(choices)
            ):
                problems.append(Problem(f"{where}.choices", "invalid_value"))
    return problems


def names_problems(names: object, *, required: bool) -> list[Problem]:
    """Problems of a type's or state's own names (en required for a tenant's own)."""
    return _names_problems(names, "names", required=required)


def chain(type_id: str, parents: Mapping[str, str | None]) -> list[str]:
    """The type and its ancestors, nearest first (a loop is cut where it repeats)."""
    out: list[str] = []
    current: str | None = type_id
    while current is not None and current not in out:
        out.append(current)
        current = parents.get(current)
    return out


def would_loop(type_id: str, new_parent: str | None, parents: Mapping[str, str | None]) -> bool:
    """Whether making `new_parent` the type's parent puts the type below itself."""
    return new_parent is not None and type_id in chain(new_parent, parents)


def depth(type_id: str, parents: Mapping[str, str | None]) -> int:
    """How many levels the type sits at (1 for a top-level type)."""
    return len(chain(type_id, parents))


def inherited(
    type_id: str,
    parents: Mapping[str, str | None],
    attributes: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Every attribute a CI of this type holds: the root type's first, its own last.

    A key defined again below an ancestor keeps the nearest definition (a child may narrow it).
    """
    found: dict[str, dict[str, Any]] = {}
    for ancestor in reversed(chain(type_id, parents)):
        for definition in attributes.get(ancestor, ()):
            found[str(definition["key"])] = {**definition, "defined_on": ancestor}
    return list(found.values())


def lost_on_change(
    custom: Mapping[str, Any], new_attributes: Iterable[Mapping[str, Any]]
) -> list[str]:
    """The keys of values a CI would lose by changing to a type with these attributes."""
    keep = {str(a["key"]) for a in new_attributes}
    return sorted(key for key, value in custom.items() if key not in keep and value is not None)


def _value_problem(definition: Mapping[str, Any], value: Any) -> str | None:  # noqa: ANN401, PLR0911 - a JSON value; one return per type
    kind = definition.get("type")
    if value is None:
        return None
    if kind in {CiAttributeType.TEXT, CiAttributeType.LONG_TEXT}:
        return None if isinstance(value, str) and len(value) <= TEXT_MAX else "invalid_value"
    if kind == CiAttributeType.NUMBER:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return None if ok else "invalid_value"
    if kind == CiAttributeType.BOOLEAN:
        return None if isinstance(value, bool) else "invalid_value"
    if kind == CiAttributeType.DATE:
        try:
            date.fromisoformat(str(value))
        except ValueError:
            return "invalid_value"
        return None
    if kind == CiAttributeType.CHOICE:
        return None if value in (definition.get("choices") or ()) else "invalid_choice"
    return "invalid_value"


def custom_problems(
    custom: Mapping[str, Any], definitions: Iterable[Mapping[str, Any]], *, creating: bool
) -> list[Problem]:
    """Problems of a CI's custom values against the attributes its type holds."""
    by_key = {str(d["key"]): d for d in definitions}
    problems = [
        Problem(f"custom.{key}", "unknown_attribute") for key in custom if key not in by_key
    ]
    for key, definition in by_key.items():
        if key in custom:
            if code := _value_problem(definition, custom[key]):
                problems.append(Problem(f"custom.{key}", code))
        elif creating and definition.get("required"):
            problems.append(Problem(f"custom.{key}", "required"))
    return problems
