"""A person's field access on CIs (ADR-047), pure: their compiled rules in, what they get out.

Only CI custom fields are rule-able (service/field_catalogue.py); fields are named
`custom.<key>`. Hidden values never reach the person; masked ones are listed apart so the page
says "masked"; any rule makes the field read-only for them.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

CUSTOM = "custom."
MASKED: dict[str, bool] = {"masked": True}  # a masked history value, as work items show it


@dataclass(frozen=True)
class Unseen:
    """What a person may not read on CIs: hidden, and masked (shown as masked)."""

    hidden: frozenset[str] = frozenset()
    masked: frozenset[str] = frozenset()

    @property
    def all(self) -> frozenset[str]:
        """Every field whose value is withheld."""
        return self.hidden | self.masked

    def custom_keys(self) -> frozenset[str]:
        """The withheld custom fields' keys (without the `custom.` prefix)."""
        return frozenset(f[len(CUSTOM) :] for f in self.all if f.startswith(CUSTOM))


def unseen(access: Mapping[str, Mapping[str, str]], record_type: str) -> Unseen:
    """The record type's withheld fields for a person."""
    fields = access.get(record_type, {})
    hidden = frozenset(f for f, m in fields.items() if m == "hidden")
    masked = frozenset(f for f, m in fields.items() if m == "masked") - hidden
    return Unseen(hidden, masked)


def read_only(access: Mapping[str, Mapping[str, str]], record_type: str) -> frozenset[str]:
    """Fields the person may not change: any rule (masked and hidden imply read-only)."""
    return frozenset(access.get(record_type, {}))


def without(custom: Mapping[str, Any] | None, keys: frozenset[str]) -> dict[str, Any]:
    """Custom values with the withheld keys taken out."""
    return {k: v for k, v in (custom or {}).items() if k not in keys}


def refused(changed: Iterable[str], locked: frozenset[str]) -> list[str]:
    """The changed fields (`custom.<key>`) the person may not change."""
    return sorted(f for f in changed if f in locked)


def flat(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """A snapshot's fields with its custom values as `custom.<key>`, for history and compare."""
    out = {k: v for k, v in snapshot.items() if k != "custom"}
    custom = snapshot.get("custom")
    if isinstance(custom, Mapping):
        out.update({f"{CUSTOM}{k}": v for k, v in custom.items()})
    return out


def dropped(custom: Mapping[str, Any], kept: Iterable[str], known: Iterable[str]) -> list[str]:
    """Keys holding a value that a type change would drop: live fields outside the new scope.

    `known`: every live field of the entity (values of fields removed earlier are not ours to
    judge; they stay as they are). `kept`: the fields that apply to the new type.
    """
    keep, live = set(kept), set(known)
    return sorted(k for k, v in custom.items() if v is not None and k in live and k not in keep)
