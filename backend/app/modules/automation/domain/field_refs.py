"""Fields an automation refers to, against what its author may see (ADR-047 §8; slice b2).

A business rule, trigger or workflow that names a field copies or decides on its value. Its
author must be able to see that field in clear: a field their roles hide or mask cannot be
referenced (422 `field_not_permitted`, checked on the server when the definition is saved),
so nobody wires a hidden value into a place they can see. Pure, no I/O.
"""

from collections.abc import Iterable, Mapping
from typing import Any

REFERENCE_KEYS = frozenset({"field", "from_field"})
WITHHELD = frozenset({"hidden", "masked"})


def named_fields(*trees: Any) -> set[str]:  # noqa: ANN401 - JSON definitions
    """Every field name under a `field` or `from_field` key, anywhere in the definitions."""
    found: set[str] = set()

    def walk(node: Any) -> None:  # noqa: ANN401 - JSON
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in REFERENCE_KEYS and isinstance(value, str):
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list | tuple):
            for item in node:
                walk(item)

    for tree in trees:
        walk(tree)
    return found


def withheld(access: Mapping[str, Mapping[str, str]], record_type: str) -> frozenset[str]:
    """The fields of a record type its author does not see in clear (hidden or masked)."""
    return frozenset(f for f, mode in access.get(record_type, {}).items() if mode in WITHHELD)


def refused(
    access: Mapping[str, Mapping[str, str]], record_type: str, trees: Iterable[Any]
) -> list[str]:
    """The fields the definitions name that the author may not see in clear, sorted."""
    return sorted(named_fields(*trees) & withheld(access, record_type))
