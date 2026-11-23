"""Field access per role (ADR-047; REQ-WI-016, REQ-ADM-026). Pure, no I/O.

A rule is (role, record type, field, mode). Modes, from clearest to strictest: a field with no
rule is `clear`; `read_only` shows it but refuses a person's change; `masked` and `hidden` show
no value (null plus a list naming the field) and imply read-only, as nobody writes what they
cannot see.

Several roles: the clearest mode any of the person's roles gives wins (ADR-047 §2), as grants
only ever add. A restriction therefore holds only when every role the person has carries it.
The same function compiles a person's subject and the effective-access view, so the two never
disagree.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType

RULES_PER_TENANT = 2000  # ADR-047 §1: a 422 `limit_reached` past it
RECORD_TYPE_MAX = 40
FIELD_MAX = 80


class FieldMode(StrEnum):
    """How a person sees one field of one record type."""

    CLEAR = "clear"  # no rule: never stored, only the absence of one
    READ_ONLY = "read_only"
    MASKED = "masked"
    HIDDEN = "hidden"


# Clearest first: the lower the rank, the more a person sees.
_RANK = {FieldMode.CLEAR: 0, FieldMode.READ_ONLY: 1, FieldMode.MASKED: 2, FieldMode.HIDDEN: 3}
RULE_MODES = frozenset({FieldMode.READ_ONLY, FieldMode.MASKED, FieldMode.HIDDEN})

# {record type: {field: mode}}, restricted fields only.
Compiled = Mapping[str, Mapping[str, str]]
EMPTY: Compiled = MappingProxyType({})


def clearest(modes: Iterable[FieldMode]) -> FieldMode:
    """The mode a person gets from all their roles' modes for one field (clearest wins)."""
    found = list(modes)
    return min(found, key=_RANK.__getitem__) if found else FieldMode.CLEAR


def effective(
    role_count: int, rules: Iterable[tuple[str, str, str]]
) -> dict[tuple[str, str], FieldMode]:
    """Each restricted (type, field) for a person with `role_count` roles.

    `rules` are (record type, field, mode), one per role that has a rule for that field. A field
    some role leaves without a rule is clear for the person, so a field is restricted only when
    all `role_count` roles have a rule for it.
    """
    per_field: dict[tuple[str, str], list[FieldMode]] = {}
    for record_type, field, mode in rules:
        per_field.setdefault((record_type, field), []).append(FieldMode(mode))
    result: dict[tuple[str, str], FieldMode] = {}
    for key, modes in per_field.items():
        if role_count == 0 or len(modes) < role_count:
            continue  # a role without a rule: the field is clear for this person
        mode = clearest(modes)
        if mode is not FieldMode.CLEAR:
            result[key] = mode
    return result


def compile_access(role_count: int, rules: Iterable[tuple[str, str, str]]) -> Compiled:
    """The subject's form: {record type: {field: mode}}, restricted fields only."""
    nested: dict[str, dict[str, str]] = {}
    for (record_type, field), mode in sorted(effective(role_count, rules).items()):
        nested.setdefault(record_type, {})[field] = mode.value
    return MappingProxyType(
        {record_type: MappingProxyType(fields) for record_type, fields in nested.items()}
    )


def mode_of(access: Compiled, record_type: str, field: str) -> FieldMode:
    """One field's mode for the person (clear without a rule)."""
    return FieldMode(access.get(record_type, {}).get(field, FieldMode.CLEAR))


def fields_in(access: Compiled, record_type: str, *modes: FieldMode) -> frozenset[str]:
    """The person's fields of a type in any of `modes`."""
    wanted = {m.value for m in modes}
    return frozenset(f for f, m in access.get(record_type, {}).items() if m in wanted)


def unseen(access: Compiled, record_type: str) -> frozenset[str]:
    """Fields whose value the person never gets: hidden or masked."""
    return fields_in(access, record_type, FieldMode.HIDDEN, FieldMode.MASKED)


def unwritable(access: Compiled, record_type: str) -> frozenset[str]:
    """Fields the person may not change: any rule (masked and hidden imply read-only)."""
    return frozenset(access.get(record_type, {}))


def to_json(access: Compiled) -> dict[str, dict[str, str]]:
    """The cache form."""
    return {t: dict(fields) for t, fields in access.items()}


def from_json(data: Mapping[str, Mapping[str, str]] | None) -> Compiled:
    """Inverse of to_json; a subject cached before this existed has none."""
    if not data:
        return EMPTY
    return MappingProxyType(
        {
            t: MappingProxyType({f: FieldMode(m).value for f, m in fields.items()})
            for t, fields in data.items()
        }
    )
