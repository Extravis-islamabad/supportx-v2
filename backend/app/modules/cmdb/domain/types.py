"""CI types (a tree) and states (WP-053 S1). Pure: no I/O.

- **Custom fields** (REQ-CMDB-001) come through the metadata module, never a second custom-field
  system here (§6.6, the coordinator 2026-11-16): a follow-up adds the type-subtree scope to
  metadata, so CIs get field access, sealing, search and reports like every other record.
- **States** (REQ-CMDB-004): `active` or `end_of_life`; end-of-life CIs are kept out of pickers
  when the tenant says so (REQ-CMDB-031).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

API_NAME = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
NAME_MAX = 200
DESCRIPTION_MAX = 10000
LANGUAGES = ("en", "ar", "ur")
TYPE_DEPTH_MAX = 8  # how deep the type tree may go

# Every field code this module's checks give (labelled `errors.field.<code>`; the label check
# reads this set, tests/test_error_labels.py).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "invalid_value",
        "invalid_key",
        "duplicate",
        "not_found",
        "unknown_language",
        "cmdb_ci_type_loop",
        "cmdb_ci_type_too_deep",
    }
)
# Problem codes (labelled `errors.<code>` / `errors.field.<code>`).
TYPE_IN_USE = "cmdb_ci_type_in_use"
STATE_IN_USE = "cmdb_ci_state_in_use"
TYPE_LOOP = "cmdb_ci_type_loop"
TYPE_TOO_DEEP = "cmdb_ci_type_too_deep"
BUILT_IN = "cmdb_built_in_locked"
NOT_FOUND = "cmdb_ci_not_found"
TYPE_NOT_FOUND = "cmdb_ci_type_not_found"
STATE_NOT_FOUND = "cmdb_ci_state_not_found"
ASSET_HAS_CI = "cmdb_asset_has_ci"


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
