"""Record types that automation works on (WP-029; REQ-RUL-008 shape, incidents first).

A module registers each of its record types once, at import: which fields rules may test and
set (with custom fields), and how to check values a rule would set *now* (a group made inactive
since the rule was saved). The engine never reads the module's tables itself (CLAUDE.md rule e).
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.automation.domain.rules import JsonValue, RuleField

FieldsProvider = Callable[[AsyncSession], Awaitable[Mapping[str, RuleField]]]
# field → problem code for the values given (only fields with a problem are returned).
ValueChecker = Callable[[AsyncSession, Mapping[str, JsonValue]], Awaitable[Mapping[str, str]]]


@dataclass(frozen=True)
class RecordType:
    """What automation needs to know about one record type."""

    code: str  # "incident"
    fields: FieldsProvider
    check_values: ValueChecker
    # Category → suggested group (routing, REQ-ASG-001), when the type has categories.
    category_group: Callable[[AsyncSession, str], Awaitable[str | None]] | None = None


_TYPES: dict[str, RecordType] = {}


def register_record_type(record_type: RecordType) -> None:
    """Called by the owning module when it is imported (idempotent)."""
    _TYPES[record_type.code] = record_type


def record_type(code: str) -> RecordType | None:
    """A registered record type, or None."""
    return _TYPES.get(code)


def record_types() -> list[str]:
    """Every registered record type code."""
    return sorted(_TYPES)
