"""Which lifecycle events one save of a record represents (WP-064, D-150, ADR-045).

Every save of a registered record type writes ONE audit entry listing all the events it stands
for (Haider: a save that does several things is one entry naming all of them). This table turns a
save (its kind and the fields it changed) into those event codes. Pure: no I/O.

The before and after values are not here: they stay in record history (`field_changes`). Only
the field names (and a trash flag's direction) decide the events.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# A kind of save (app/shared/history ChangeKind) -> its event, where the kind alone names one.
_KIND_EVENTS: Mapping[str, str] = {
    "created": "created",
    "deleted": "deleted",
    "restored": "restored",
    "status": "status_changed",
    "child_added": "part_added",
    "child_changed": "part_changed",
    "child_removed": "part_removed",
}
UPDATED = "updated"  # a save that matches no other event


@dataclass(frozen=True)
class RecordAudit:
    """One record type's lifecycle events."""

    record_type: str
    module: str
    # The kinds of save this type has (a subset of _KIND_EVENTS; "updated" is always possible).
    kinds: frozenset[str]
    # Field name -> event. Order matters: earlier events come first in the entry's list.
    fields: Mapping[str, str] = field(default_factory=dict)
    # A boolean field whose change is a move to the trash (False -> True) or a restore.
    trash_field: str | None = None

    def events(self) -> frozenset[str]:
        """Every event code this type can produce."""
        names = {_KIND_EVENTS[k] for k in self.kinds} | {UPDATED, *self.fields.values()}
        if self.trash_field is not None:
            names |= {"deleted", "restored"}
        return frozenset(f"{self.record_type}.{name}" for name in names)


@dataclass(frozen=True)
class FieldDiff:
    """One changed field of a save: its name, old and new value."""

    name: str
    old: object
    new: object


ASSET = RecordAudit(
    record_type="asset",
    module="assets",
    kinds=frozenset({"created", "deleted"}),
    fields={
        "state_id": "moved",  # moved to another state: the code the move route already writes
        "site_id": "relocated",
        "location": "relocated",
        "product_id": "product_changed",
    },
    trash_field="deleted",
)

RECORD_TYPES: Mapping[str, RecordAudit] = {r.record_type: r for r in (ASSET,)}


def events_of(
    spec: RecordAudit, kind: str, changed: Iterable[FieldDiff], route_action: str | None = None
) -> tuple[str, ...]:
    """The save's event codes, most significant first, without repeats.

    `route_action` is the code of the route that made the save (its `audited(...)` action). It
    comes first and becomes the entry's action, so everything that found the route's own entry
    before (filters, saved searches, exports, the SIEM stream) finds this one.
    """
    changes = list(changed)
    names = {c.name for c in changes}
    trash = next((c for c in changes if c.name == spec.trash_field), None)
    found: list[str] = []
    if trash is not None and bool(trash.new) != bool(trash.old):
        found.append("deleted" if trash.new else "restored")
    elif kind in spec.kinds:
        found.append(_KIND_EVENTS[kind])
    if kind != "created":  # a new record's first values are not changes of state or place
        found.extend(event for name, event in spec.fields.items() if name in names)
    if not found:
        found.append(UPDATED)
    codes = [f"{spec.record_type}.{name}" for name in found]
    if route_action is not None:
        codes.insert(0, route_action)
    return tuple(dict.fromkeys(codes))


def lifecycle_codes() -> frozenset[str]:
    """Every code the table can produce (each is in the audit catalogue, with labels)."""
    return frozenset().union(*(spec.events() for spec in RECORD_TYPES.values()))
